from __future__ import annotations

from dataclasses import dataclass, field
import logging
import threading
import time
from typing import TYPE_CHECKING

from t212ai.app.logging import log_event
from t212ai.scheduler import (
    SchedulerWorker,
    SchedulerWorkerResult,
    build_scheduler_adapter_registry,
)

if TYPE_CHECKING:
    from .runtime import AppRuntime


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class EmbeddedSchedulerWorker:
    runtime: AppRuntime
    poll_every_seconds: int = 60
    limit: int = 100
    lease_seconds: int | None = None
    stale_run_after_seconds: int | None = None
    max_llm_runs_per_pass: int | None = None
    _stop_event: threading.Event = field(init=False, repr=False)
    _thread: threading.Thread | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        self.poll_every_seconds = max(1, int(self.poll_every_seconds))
        self.limit = max(1, int(self.limit))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        if self.runtime.scheduled_process_service is None:
            log_event(
                LOGGER,
                "scheduler.embedded_worker.unavailable",
                "warning",
                component="scheduler",
                step="embedded_worker_start",
                status="unavailable",
                error_code="scheduler_service_unavailable",
            )
            return False
        if self._thread is not None and self._thread.is_alive():
            return True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="t212ai-scheduler-worker",
            daemon=True,
        )
        self._thread.start()
        log_event(
            LOGGER,
            "scheduler.embedded_worker.start",
            component="scheduler",
            step="embedded_worker_start",
            status="started",
            poll_every_seconds=self.poll_every_seconds,
            limit=self.limit,
        )
        return True

    def stop(self, *, timeout_seconds: float = 10.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.0, float(timeout_seconds)))
        log_event(
            LOGGER,
            "scheduler.embedded_worker.stop",
            component="scheduler",
            step="embedded_worker_stop",
            status="stopped",
        )

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            started = time.monotonic()
            try:
                result = run_scheduler_once(
                    self.runtime,
                    limit=self.limit,
                    lease_seconds=self.lease_seconds,
                    stale_run_after_seconds=self.stale_run_after_seconds,
                    max_llm_runs_per_pass=self.max_llm_runs_per_pass,
                )
                log_event(
                    LOGGER,
                    "scheduler.embedded_worker.pass",
                    component="scheduler",
                    step="embedded_worker_pass",
                    status="ok",
                    duration_ms=int((time.monotonic() - started) * 1000),
                    due_count=result.due_count,
                    claimed_count=result.claimed_count,
                    processed_count=result.processed_count,
                    completed_count=result.completed_count,
                    skipped_count=result.skipped_count,
                    failed_count=result.failed_count,
                    recovered_count=result.recovered_count,
                )
            except Exception as exc:  # pragma: no cover - defensive loop guard
                log_event(
                    LOGGER,
                    "scheduler.embedded_worker.error",
                    "error",
                    component="scheduler",
                    step="embedded_worker_pass",
                    status="error",
                    duration_ms=int((time.monotonic() - started) * 1000),
                    error_type=exc.__class__.__name__,
                )
            self._stop_event.wait(self.poll_every_seconds)


def build_embedded_scheduler_worker(runtime: AppRuntime) -> EmbeddedSchedulerWorker | None:
    settings = runtime.settings
    if not settings.scheduler_embedded_worker_enabled:
        return None
    if runtime.scheduled_process_service is None:
        return None
    return EmbeddedSchedulerWorker(
        runtime,
        poll_every_seconds=settings.scheduler_embedded_worker_poll_every_seconds,
        limit=settings.scheduler_embedded_worker_limit,
        lease_seconds=settings.scheduler_lease_seconds,
        stale_run_after_seconds=settings.scheduler_stale_run_after_seconds,
        max_llm_runs_per_pass=settings.scheduler_max_llm_runs_per_pass,
    )


def run_scheduler_once(
    runtime: AppRuntime,
    *,
    limit: int = 100,
    lease_seconds: int | None = None,
    stale_run_after_seconds: int | None = None,
    max_llm_runs_per_pass: int | None = None,
) -> SchedulerWorkerResult:
    if runtime.scheduled_process_service is None:
        raise RuntimeError("Scheduler runtime is not available.")
    worker = SchedulerWorker(
        runtime.scheduled_process_service,
        adapters=build_scheduler_adapter_registry(
            company_agent=getattr(runtime, "company_agent", None),
            market_agent=getattr(runtime, "market_agent", None),
            market_data_service=getattr(runtime, "market_data_service", None),
            community_research_service=getattr(runtime, "community_research_service", None),
            disclosure_service=getattr(runtime, "disclosure_service", None),
            search_service=getattr(runtime, "search_service", None),
            market_signal_service=getattr(runtime, "market_signal_service", None),
            broker_read_service=getattr(runtime, "broker_read_service", None),
            broker_execution_service=getattr(runtime, "broker_execution_service", None),
            pending_action_service=getattr(runtime, "pending_action_service", None),
            proposal_service=getattr(runtime, "proposal_service", None),
            broker_provider=getattr(
                getattr(runtime, "settings", None),
                "broker_provider",
                "broker",
            ),
        ),
        notification_service=getattr(runtime, "scheduler_notification_service", None),
        worker_id=getattr(getattr(runtime, "settings", None), "scheduler_worker_id", None),
        lease_seconds=lease_seconds
        or getattr(getattr(runtime, "settings", None), "scheduler_lease_seconds", 1800),
        stale_run_after_seconds=stale_run_after_seconds
        or getattr(
            getattr(runtime, "settings", None),
            "scheduler_stale_run_after_seconds",
            3600,
        ),
        max_llm_runs_per_pass=(
            max_llm_runs_per_pass
            if max_llm_runs_per_pass is not None
            else getattr(
                getattr(runtime, "settings", None),
                "scheduler_max_llm_runs_per_pass",
                0,
            )
        ),
    )
    return worker.run_once(limit=limit)
