"""Scheduler worker skeleton."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from t212ai.genai.tracing import set_trace_metadata, traceable

from .models import ScheduledEventType, ScheduledProcess, ScheduledRunStatus
from .notification import SchedulerNotificationService
from .service import ScheduledProcessClaim, ScheduledProcessService


@dataclass(frozen=True, slots=True)
class ScheduledAdapterResult:
    status: ScheduledRunStatus
    matched: bool = False
    output_summary: str | None = None
    code: str | None = None
    message: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    notification_message: str | None = None
    notification_metadata: dict[str, object] = field(default_factory=dict)
    notification_target_chat_ids: tuple[int, ...] = ()
    notification_approval_payload: dict[str, object] | None = None


class ScheduledProcessAdapter(Protocol):
    def run(self, process: ScheduledProcess) -> ScheduledAdapterResult:
        """Run a due scheduled process and return a deterministic outcome."""


@dataclass(frozen=True, slots=True)
class SchedulerProcessRunSummary:
    process_id: str
    kind: str
    run_id: str
    status: ScheduledRunStatus
    code: str | None
    message: str


@dataclass(frozen=True, slots=True)
class SchedulerWorkerResult:
    started_at: datetime
    finished_at: datetime
    due_count: int
    claimed_count: int = 0
    recovered_count: int = 0
    runs: list[SchedulerProcessRunSummary] = field(default_factory=list)

    @property
    def processed_count(self) -> int:
        return len(self.runs)

    @property
    def completed_count(self) -> int:
        return sum(1 for run in self.runs if run.status == ScheduledRunStatus.COMPLETED)

    @property
    def skipped_count(self) -> int:
        return sum(1 for run in self.runs if run.status == ScheduledRunStatus.SKIPPED)

    @property
    def failed_count(self) -> int:
        return sum(1 for run in self.runs if run.status == ScheduledRunStatus.FAILED)

    def render_text(self) -> str:
        lines = [
            (
                "brokerai scheduler run: "
                f"due={self.due_count} "
                f"claimed={self.claimed_count} "
                f"processed={self.processed_count} "
                f"completed={self.completed_count} "
                f"skipped={self.skipped_count} "
                f"failed={self.failed_count} "
                f"recovered={self.recovered_count}"
            )
        ]
        for run in self.runs:
            code = run.code or "none"
            lines.append(
                f"- {run.process_id} {run.kind}: {run.status.value} ({code}) {run.message}"
            )
        return "\n".join(lines)


class SchedulerWorker:
    """Loads due scheduled processes and records deterministic skeleton outcomes."""

    def __init__(
        self,
        service: ScheduledProcessService,
        *,
        adapters: dict[str, ScheduledProcessAdapter] | None = None,
        notification_service: SchedulerNotificationService | None = None,
        worker_id: str | None = None,
        lease_seconds: int = 1800,
        stale_run_after_seconds: int = 3600,
        recover_stale_runs: bool = True,
        max_llm_runs_per_pass: int = 0,
    ) -> None:
        self.service = service
        self.adapters = dict(adapters or {})
        self.notification_service = notification_service
        self.worker_id = str(worker_id or "").strip() or f"scheduler_worker_{uuid4().hex[:8]}"
        self.lease_seconds = max(1, int(lease_seconds))
        self.stale_run_after_seconds = max(1, int(stale_run_after_seconds))
        self.recover_stale_runs = bool(recover_stale_runs)
        self.max_llm_runs_per_pass = max(0, int(max_llm_runs_per_pass))

    @traceable(name="scheduler.run_once", run_type="chain")
    def run_once(
        self,
        *,
        limit: int = 100,
        now: datetime | None = None,
    ) -> SchedulerWorkerResult:
        started_at = _ensure_aware(now) if now is not None else _utc_now()
        recovered_count = 0
        if self.recover_stale_runs:
            recovered = self.service.recover_stale_runs(
                stale_after_seconds=self.stale_run_after_seconds,
                now=started_at,
                limit=limit,
                dry_run=False,
            )
            recovered_count = recovered.changed_count
        due_count = len(self.service.list_due_processes(now=started_at, limit=limit))
        claims = self.service.claim_due_processes(
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
            now=started_at,
            limit=limit,
        )
        set_trace_metadata(
            agent_step="scheduler_run_once",
            step_kind="chain",
            worker_id=self.worker_id,
            due_count=due_count,
            claimed_count=len(claims),
            recovered_count=recovered_count,
            adapter_count=len(self.adapters),
            max_llm_runs_per_pass=self.max_llm_runs_per_pass,
        )
        summaries: list[SchedulerProcessRunSummary] = []
        llm_runs_started = 0
        for claim in claims:
            process = claim.process
            if _is_llm_process(process) and self.max_llm_runs_per_pass > 0:
                if llm_runs_started >= self.max_llm_runs_per_pass:
                    summaries.append(
                        self._skip_process_for_llm_budget(
                            claim,
                            now=started_at,
                        )
                    )
                    continue
                llm_runs_started += 1
            summaries.append(self._run_claimed_process(claim, now=started_at))
        finished_at = _utc_now()
        return SchedulerWorkerResult(
            started_at=started_at,
            finished_at=finished_at,
            due_count=due_count,
            claimed_count=len(claims),
            recovered_count=recovered_count,
            runs=summaries,
        )

    def _run_claimed_process(
        self,
        claim: ScheduledProcessClaim,
        *,
        now: datetime,
    ) -> SchedulerProcessRunSummary:
        try:
            return self._run_process(claim.process, now=now)
        finally:
            self.service.release_process_lease(
                claim.process.process_id,
                claim.lease_token,
            )

    def _skip_process_for_llm_budget(
        self,
        claim: ScheduledProcessClaim,
        *,
        now: datetime,
    ) -> SchedulerProcessRunSummary:
        try:
            run = self.service.record_run_started(
                claim.process.process_id,
                due_at=claim.process.next_run_at,
                now=now,
                metadata={"kind": claim.process.kind.value, "workerId": self.worker_id},
            )
            message = (
                "Scheduler skipped this LLM-assisted process because "
                "SCHEDULER_MAX_LLM_RUNS_PER_PASS was reached."
            )
            skipped = self.service.record_run_skipped(
                run.run_id,
                reason_code="scheduler_llm_budget_exhausted",
                reason_message=message,
                metadata={
                    "kind": claim.process.kind.value,
                    "workerId": self.worker_id,
                    "maxLlmRunsPerPass": self.max_llm_runs_per_pass,
                },
                now=now,
            )
            return SchedulerProcessRunSummary(
                process_id=claim.process.process_id,
                kind=claim.process.kind.value,
                run_id=run.run_id,
                status=skipped.status,
                code=skipped.error_code,
                message=message,
            )
        finally:
            self.service.release_process_lease(
                claim.process.process_id,
                claim.lease_token,
            )

    def _run_process(
        self,
        process: ScheduledProcess,
        *,
        now: datetime,
    ) -> SchedulerProcessRunSummary:
        run = self.service.record_run_started(
            process.process_id,
            due_at=process.next_run_at,
            now=now,
            metadata={"kind": process.kind.value, "workerId": self.worker_id},
        )
        adapter = self.adapters.get(process.kind.value)
        if adapter is None:
            message = f"No scheduler adapter is registered for process kind '{process.kind.value}'."
            skipped = self.service.record_run_skipped(
                run.run_id,
                reason_code="adapter_unavailable",
                reason_message=message,
                metadata={"kind": process.kind.value},
                now=now,
            )
            return SchedulerProcessRunSummary(
                process_id=process.process_id,
                kind=process.kind.value,
                run_id=run.run_id,
                status=skipped.status,
                code=skipped.error_code,
                message=message,
            )
        try:
            result = adapter.run(process)
        except Exception as exc:  # pragma: no cover - defensive path covered by tests
            message = f"{exc.__class__.__name__}: {exc}"
            failed = self.service.record_run_failed(
                run.run_id,
                error_code="adapter_error",
                error_message=message,
                metadata={"kind": process.kind.value},
                now=now,
            )
            return SchedulerProcessRunSummary(
                process_id=process.process_id,
                kind=process.kind.value,
                run_id=run.run_id,
                status=failed.status,
                code=failed.error_code,
                message=message,
            )
        return self._record_adapter_result(process, run.run_id, result, now=now)

    def _record_adapter_result(
        self,
        process: ScheduledProcess,
        run_id: str,
        result: ScheduledAdapterResult,
        *,
        now: datetime,
    ) -> SchedulerProcessRunSummary:
        if result.status == ScheduledRunStatus.COMPLETED:
            completed = self.service.record_run_completed(
                run_id,
                matched=result.matched,
                output_summary=result.output_summary,
                metadata=dict(result.metadata),
                now=now,
            )
            summary = SchedulerProcessRunSummary(
                process_id=process.process_id,
                kind=process.kind.value,
                run_id=run_id,
                status=completed.status,
                code=result.code,
                message=result.message or result.output_summary or "Completed.",
            )
            self._send_result_notification(process, run_id, result)
            return summary
        if result.status == ScheduledRunStatus.SKIPPED:
            code = result.code or "adapter_skipped"
            message = result.message or result.output_summary or "Skipped."
            skipped = self.service.record_run_skipped(
                run_id,
                reason_code=code,
                reason_message=message,
                metadata=dict(result.metadata),
                now=now,
            )
            summary = SchedulerProcessRunSummary(
                process_id=process.process_id,
                kind=process.kind.value,
                run_id=run_id,
                status=skipped.status,
                code=skipped.error_code,
                message=message,
            )
            self._send_result_notification(process, run_id, result)
            return summary
        if result.status == ScheduledRunStatus.FAILED:
            code = result.code or "adapter_failed"
            message = result.message or result.output_summary or "Failed."
            failed = self.service.record_run_failed(
                run_id,
                error_code=code,
                error_message=message,
                metadata=dict(result.metadata),
                now=now,
            )
            summary = SchedulerProcessRunSummary(
                process_id=process.process_id,
                kind=process.kind.value,
                run_id=run_id,
                status=failed.status,
                code=failed.error_code,
                message=message,
            )
            self._send_result_notification(process, run_id, result)
            return summary
        message = f"Adapter returned unsupported status '{result.status.value}'."
        failed = self.service.record_run_failed(
            run_id,
            error_code="unsupported_adapter_status",
            error_message=message,
            metadata=dict(result.metadata),
            now=now,
        )
        return SchedulerProcessRunSummary(
            process_id=process.process_id,
            kind=process.kind.value,
            run_id=run_id,
            status=failed.status,
            code=failed.error_code,
            message=message,
        )

    def _send_result_notification(
        self,
        process: ScheduledProcess,
        run_id: str,
        result: ScheduledAdapterResult,
    ) -> None:
        if self.notification_service is None:
            return
        message = str(result.notification_message or "").strip()
        if not message:
            return
        metadata = {
            "kind": process.kind.value,
            "runStatus": result.status.value,
            "matched": result.matched,
            **dict(result.notification_metadata),
        }
        try:
            self.notification_service.send_process_notification(
                process_id=process.process_id,
                run_id=run_id,
                message=message,
                metadata=metadata,
                target_chat_ids=result.notification_target_chat_ids,
                approval_payload=result.notification_approval_payload,
            )
        except Exception as exc:  # pragma: no cover - defensive audit fallback
            try:
                self.service.record_event(
                    process.process_id,
                    run_id=run_id,
                    event_type=ScheduledEventType.NOTIFICATION_FAILED,
                    message=f"Scheduler notification service failed: {exc}.",
                    details={
                        "errorCode": "notification_service_error",
                        "errorType": exc.__class__.__name__,
                        "metadata": metadata,
                    },
                )
            except Exception:
                return


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_llm_process(process: ScheduledProcess) -> bool:
    return process.execution_mode.value in {"llm_assisted", "llm_planned"}
