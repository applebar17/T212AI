"""Background supervisor for scheduled Alpaca news stream monitors."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from t212ai.agent.history import ChatHistoryJournal, ChatHistoryManager
from t212ai.agent.news_judge import NewsIngestionJudgeAgent
from t212ai.agent.schemas import AgentRequest, AgentResponse
from t212ai.alpaca import (
    AlpacaStreamClient,
    AlpacaStreamEvent,
    AlpacaStreamSubscription,
    CleanedNewsPacket,
    clean_alpaca_news_event,
)
from t212ai.app.logging import log_event
from t212ai.scheduler.models import ScheduledEventType, ScheduledProcess
from t212ai.scheduler.notification import SchedulerNotificationService
from t212ai.scheduler.service import ScheduledProcessClaim, ScheduledProcessService

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class AlpacaNewsStreamSupervisor:
    scheduler_service: ScheduledProcessService
    stream_client: AlpacaStreamClient
    news_judge_agent: NewsIngestionJudgeAgent
    notification_service: SchedulerNotificationService | None = None
    history_manager: ChatHistoryManager | None = None
    poll_seconds: int = 30
    lease_seconds: int = 120
    worker_id: str | None = None
    _stop_event: threading.Event = field(init=False, repr=False)
    _thread: threading.Thread | None = field(init=False, default=None, repr=False)
    _workers: dict[str, _MonitorWorkerHandle] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self.poll_seconds = max(1, int(self.poll_seconds))
        self.lease_seconds = max(10, int(self.lease_seconds))
        self.worker_id = str(self.worker_id or "").strip() or f"alpaca_news_{uuid4().hex[:8]}"
        self._stop_event = threading.Event()

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="t212ai-alpaca-news-supervisor",
            daemon=True,
        )
        self._thread.start()
        log_event(
            LOGGER,
            "alpaca_news.supervisor.start",
            component="scheduler",
            step="alpaca_news_supervisor_start",
            status="started",
            poll_seconds=self.poll_seconds,
            lease_seconds=self.lease_seconds,
        )
        return True

    def stop(self, *, timeout_seconds: float = 10.0) -> None:
        self._stop_event.set()
        for handle in list(self._workers.values()):
            handle.stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.0, float(timeout_seconds)))
        for handle in list(self._workers.values()):
            if handle.thread.is_alive():
                handle.thread.join(timeout=1.0)
        log_event(
            LOGGER,
            "alpaca_news.supervisor.stop",
            component="scheduler",
            step="alpaca_news_supervisor_stop",
            status="stopped",
        )

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._sync_workers()
            except Exception as exc:  # pragma: no cover - loop guard
                log_event(
                    LOGGER,
                    "alpaca_news.supervisor.error",
                    "error",
                    component="scheduler",
                    step="alpaca_news_supervisor_pass",
                    status="error",
                    error_type=exc.__class__.__name__,
                )
            self._stop_event.wait(self.poll_seconds)

    def _sync_workers(self) -> None:
        active_processes = self.scheduler_service.list_processes(
            statuses=["active"],
            kinds=["alpaca_news_monitor"],
            limit=250,
        )
        active_by_id = {process.process_id: process for process in active_processes}
        now = _utc_now()

        for process_id, handle in list(self._workers.items()):
            process = active_by_id.get(process_id)
            should_stop = (
                process is None
                or not handle.thread.is_alive()
                or _process_window_ended(process, now)
            )
            if should_stop:
                handle.stop_event.set()
                if not handle.thread.is_alive():
                    self._workers.pop(process_id, None)

        for process in active_processes:
            if process.process_id in self._workers:
                continue
            try:
                spec = _monitor_spec(process)
            except Exception as exc:
                self.scheduler_service.mark_failed(
                    process.process_id,
                    reason=f"Invalid Alpaca news monitor spec: {exc}.",
                    now=now,
                )
                continue
            if spec.start_at > now:
                continue
            if spec.end_at <= now:
                self.scheduler_service.mark_completed(
                    process.process_id,
                    reason="Alpaca news monitor window ended before worker start.",
                    now=now,
                )
                continue
            claim = self.scheduler_service.claim_process(
                process.process_id,
                worker_id=str(self.worker_id),
                lease_seconds=self.lease_seconds,
                now=now,
            )
            if claim is None:
                continue
            stop_event = threading.Event()
            thread = threading.Thread(
                target=self._run_claimed_process,
                args=(claim, stop_event),
                name=f"t212ai-alpaca-news-{process.process_id}",
                daemon=True,
            )
            self._workers[process.process_id] = _MonitorWorkerHandle(
                thread=thread,
                stop_event=stop_event,
                lease_token=claim.lease_token,
            )
            thread.start()
            log_event(
                LOGGER,
                "alpaca_news.worker.start",
                component="scheduler",
                step="alpaca_news_worker_start",
                status="started",
                process_id=process.process_id,
                symbol_count=len(spec.symbols),
            )

    def _run_claimed_process(
        self,
        claim: ScheduledProcessClaim,
        stop_event: threading.Event,
    ) -> None:
        try:
            asyncio.run(self._run_claimed_process_async(claim, stop_event))
        finally:
            self.scheduler_service.release_process_lease(
                claim.process.process_id,
                claim.lease_token,
            )
            self._workers.pop(claim.process.process_id, None)

    async def _run_claimed_process_async(
        self,
        claim: ScheduledProcessClaim,
        stop_event: threading.Event,
    ) -> None:
        process = claim.process
        spec = _monitor_spec(process)
        run = self.scheduler_service.record_run_started(
            process.process_id,
            due_at=None,
            metadata={"kind": process.kind.value, "workerId": self.worker_id},
        )
        stats = _MonitorStats()
        seen_dedupe_keys: set[str] = set()
        rate_window: deque[float] = deque()
        stream = self.stream_client.connect_and_subscribe(
            AlpacaStreamSubscription(news=_subscription_symbols(spec.symbols)),
            stream="news",
        )
        iterator = stream.__aiter__()
        status = "completed"
        error_message: str | None = None
        try:
            while not stop_event.is_set():
                now = _utc_now()
                if now >= spec.end_at:
                    break
                self.scheduler_service.refresh_process_lease(
                    process.process_id,
                    claim.lease_token,
                    lease_seconds=self.lease_seconds,
                    now=now,
                )
                event = await _next_event_with_timeout(
                    iterator,
                    timeout_seconds=min(15.0, max(1.0, self.lease_seconds / 2)),
                )
                if event is None:
                    continue
                if event.news is None:
                    continue
                packet = clean_alpaca_news_event(event)
                if not _symbol_filter_matches(spec.symbols, packet.symbols):
                    stats.skipped_symbol += 1
                    log_event(
                        LOGGER,
                        "alpaca_news.event.skipped",
                        component="scheduler",
                        step="alpaca_news_worker",
                        status="skipped",
                        process_id=process.process_id,
                        run_id=run.run_id,
                        reason_code="symbol_filter",
                        monitor_symbols=spec.symbols,
                        packet_symbols=packet.symbols,
                        dedupe_key=packet.dedupe_key,
                        headline=_preview(packet.headline),
                    )
                    continue
                if packet.dedupe_key in seen_dedupe_keys:
                    stats.duplicate += 1
                    continue
                seen_dedupe_keys.add(packet.dedupe_key)
                if not _allow_event(rate_window, spec.max_events_per_minute):
                    stats.rate_limited += 1
                    continue
                stats.received += 1
                log_event(
                    LOGGER,
                    "alpaca_news.event.received",
                    component="scheduler",
                    step="alpaca_news_worker",
                    status="received",
                    process_id=process.process_id,
                    run_id=run.run_id,
                    monitor_symbols=spec.symbols,
                    packet_symbols=packet.symbols,
                    dedupe_key=packet.dedupe_key,
                    headline=_preview(packet.headline),
                )
                response = self._judge_packet(
                    process=process,
                    spec=spec,
                    packet=packet,
                    run_id=run.run_id,
                )
                stats.judged += 1
                if response.metadata.get("relevant") == "True":
                    stats.relevant += 1
                if response.metadata.get("user_visible") == "True":
                    stats.user_visible += 1
                self._handle_judge_response(
                    process=process,
                    spec=spec,
                    packet=packet,
                    response=response,
                    run_id=run.run_id,
                )
        except Exception as exc:
            status = "failed"
            error_message = f"{exc.__class__.__name__}: {exc}"
            log_event(
                LOGGER,
                "alpaca_news.worker.error",
                "error",
                component="scheduler",
                step="alpaca_news_worker",
                status="error",
                process_id=process.process_id,
                run_id=run.run_id,
                error_type=exc.__class__.__name__,
            )
        finally:
            close = getattr(stream, "aclose", None)
            if callable(close):
                await close()

        metadata = stats.metadata()
        if status == "failed":
            self.scheduler_service.record_run_failed(
                run.run_id,
                error_code="alpaca_news_stream_failed",
                error_message=error_message or "Alpaca news stream failed.",
                metadata=metadata,
            )
            return
        if stop_event.is_set() and _utc_now() < spec.end_at:
            self.scheduler_service.record_run_skipped(
                run.run_id,
                reason_code="alpaca_news_supervisor_stopped",
                reason_message="Alpaca news monitor worker stopped before window end.",
                metadata=metadata,
            )
            return
        self.scheduler_service.record_run_completed(
            run.run_id,
            matched=stats.relevant > 0,
            output_summary=_stats_summary(stats),
            metadata=metadata,
        )

    def _judge_packet(
        self,
        *,
        process: ScheduledProcess,
        spec: _MonitorSpec,
        packet: CleanedNewsPacket,
        run_id: str,
    ) -> AgentResponse:
        chat_id = str(spec.chat_id or "").strip() or None
        history = (
            self.history_manager.get_context_window(chat_id)
            if self.history_manager is not None and chat_id
            else None
        )
        request = AgentRequest(
            user_message=json.dumps(
                {"streamedNews": packet.model_dump(by_alias=True, mode="json")},
                ensure_ascii=True,
                sort_keys=True,
            ),
            chat_id=chat_id,
            trigger_type="alpaca_news_stream",
            history=history,
            orchestrator_guidance="Judge this Alpaca news stream event.",
            metadata={
                "process_id": process.process_id,
                "run_id": run_id,
                "symbols": ",".join(spec.symbols),
                "timezone": spec.timezone,
                "task_guidelines": spec.task_guidelines,
                "order_proposals_enabled": str(spec.order_proposals_enabled),
                "news_dedupe_key": packet.dedupe_key,
            },
        )
        return self.news_judge_agent.handle(request)

    def _handle_judge_response(
        self,
        *,
        process: ScheduledProcess,
        spec: _MonitorSpec,
        packet: CleanedNewsPacket,
        response: AgentResponse,
        run_id: str,
    ) -> None:
        result = response.artifacts.get("news_judge_result")
        result = result if isinstance(result, dict) else {}
        relevant = str(response.metadata.get("relevant") or "").lower() == "true"
        user_visible = str(response.metadata.get("user_visible") or "").lower() == "true"
        if relevant:
            self.scheduler_service.record_event(
                process.process_id,
                run_id=run_id,
                event_type=ScheduledEventType.TRIGGER_MATCHED,
                message="Alpaca news monitor judged a relevant event.",
                details={
                    "dedupeKey": packet.dedupe_key,
                    "headline": _preview(packet.headline),
                    "symbols": packet.symbols,
                    "userVisible": user_visible,
                    "summary": _preview(str(result.get("summary") or response.final_answer)),
                    "actionsTaken": result.get("actionsTaken") or [],
                },
            )
        if not relevant:
            return
        if user_visible and spec.notification_enabled:
            self._notify(process, spec, response, run_id=run_id)
            return
        self._record_background_history(spec, response)

    def _notify(
        self,
        process: ScheduledProcess,
        spec: _MonitorSpec,
        response: AgentResponse,
        *,
        run_id: str,
    ) -> None:
        if self.notification_service is None:
            self._record_background_history(spec, response)
            return
        approval = response.artifacts.get("telegram_approval_request")
        self.notification_service.send_process_notification(
            process_id=process.process_id,
            run_id=run_id,
            message=response.final_answer,
            metadata={
                "kind": process.kind.value,
                "source": "alpaca_news_monitor",
                "relevant": response.metadata.get("relevant"),
                "userVisible": response.metadata.get("user_visible"),
            },
            target_chat_ids=([int(spec.chat_id)] if spec.chat_id is not None else None),
            approval_payload=approval if isinstance(approval, dict) else None,
        )

    def _record_background_history(
        self,
        spec: _MonitorSpec,
        response: AgentResponse,
    ) -> None:
        if self.history_manager is None or spec.chat_id is None:
            return
        ChatHistoryJournal(self.history_manager).record_outbound(
            spec.chat_id,
            response.final_answer,
            source="scheduler_alpaca_news_monitor",
            metadata={
                "notification_kind": "background",
                "relevant": response.metadata.get("relevant"),
                "user_visible": response.metadata.get("user_visible"),
            },
        )


@dataclass(slots=True)
class _MonitorSpec:
    symbols: list[str]
    start_at: datetime
    end_at: datetime
    timezone: str
    task_guidelines: str
    order_proposals_enabled: bool
    max_events_per_minute: int
    notification_enabled: bool
    chat_id: int | None


@dataclass(slots=True)
class _MonitorWorkerHandle:
    thread: threading.Thread
    stop_event: threading.Event
    lease_token: str


@dataclass(slots=True)
class _MonitorStats:
    received: int = 0
    judged: int = 0
    relevant: int = 0
    user_visible: int = 0
    duplicate: int = 0
    skipped_symbol: int = 0
    rate_limited: int = 0

    def metadata(self) -> dict[str, object]:
        return {
            "received": self.received,
            "judged": self.judged,
            "relevant": self.relevant,
            "userVisible": self.user_visible,
            "duplicate": self.duplicate,
            "skippedSymbol": self.skipped_symbol,
            "rateLimited": self.rate_limited,
        }


async def _next_event_with_timeout(
    iterator: Any,
    *,
    timeout_seconds: float,
) -> AlpacaStreamEvent | None:
    try:
        return await asyncio.wait_for(iterator.__anext__(), timeout=timeout_seconds)
    except TimeoutError:
        return None
    except StopAsyncIteration:
        return None


def _monitor_spec(process: ScheduledProcess) -> _MonitorSpec:
    inputs = process.inputs
    symbols = _clean_symbols(inputs.get("symbols") or []) or ["*"]
    return _MonitorSpec(
        symbols=symbols,
        start_at=_parse_utc(inputs.get("startAt")),
        end_at=_parse_utc(inputs.get("endAt")),
        timezone=str(inputs.get("timezone") or "UTC"),
        task_guidelines=str(inputs.get("taskGuidelines") or ""),
        order_proposals_enabled=bool(inputs.get("orderProposalsEnabled")),
        max_events_per_minute=max(1, int(inputs.get("maxEventsPerMinute") or 30)),
        notification_enabled=bool(process.notification.get("enabled", True)),
        chat_id=_optional_int(
            inputs.get("chatId") or process.notification.get("chatId")
        ),
    )


def _process_window_ended(process: ScheduledProcess, now: datetime) -> bool:
    try:
        return _monitor_spec(process).end_at <= now
    except Exception:
        return True


def _allow_event(rate_window: deque[float], max_events_per_minute: int) -> bool:
    now = time.monotonic()
    cutoff = now - 60.0
    while rate_window and rate_window[0] < cutoff:
        rate_window.popleft()
    if len(rate_window) >= max_events_per_minute:
        return False
    rate_window.append(now)
    return True


def _subscription_symbols(symbols: list[str]) -> list[str]:
    return ["*"] if not symbols or _has_wildcard(symbols) else symbols


def _symbol_filter_matches(monitor_symbols: list[str], packet_symbols: list[str]) -> bool:
    if not monitor_symbols or _has_wildcard(monitor_symbols):
        return True
    return not set(monitor_symbols).isdisjoint(packet_symbols)


def _has_wildcard(symbols: list[str]) -> bool:
    return any(str(symbol or "").strip() == "*" for symbol in symbols)


def _stats_summary(stats: _MonitorStats) -> str:
    return (
        "Alpaca news monitor completed: "
        f"received={stats.received} judged={stats.judged} "
        f"relevant={stats.relevant} userVisible={stats.user_visible}."
    )


def _parse_utc(value: Any) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("monitor datetime is required")
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _clean_symbols(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        return []
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        symbol = str(value or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        output.append(symbol)
    return output


def _optional_int(value: Any) -> int | None:
    if value is None or not str(value).strip():
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def _preview(value: Any, *, limit: int = 240) -> str | None:
    text = " ".join(str(value or "").split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."
