"""Scheduler worker skeleton."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from t212ai.genai.tracing import set_trace_metadata, traceable

from .models import ScheduledProcess, ScheduledRunStatus
from .service import ScheduledProcessService


@dataclass(frozen=True, slots=True)
class ScheduledAdapterResult:
    status: ScheduledRunStatus
    matched: bool = False
    output_summary: str | None = None
    code: str | None = None
    message: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


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
                f"processed={self.processed_count} "
                f"completed={self.completed_count} "
                f"skipped={self.skipped_count} "
                f"failed={self.failed_count}"
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
    ) -> None:
        self.service = service
        self.adapters = dict(adapters or {})

    @traceable(name="scheduler.run_once", run_type="chain")
    def run_once(
        self,
        *,
        limit: int = 100,
        now: datetime | None = None,
    ) -> SchedulerWorkerResult:
        started_at = _ensure_aware(now) if now is not None else _utc_now()
        due_processes = self.service.list_due_processes(now=started_at, limit=limit)
        set_trace_metadata(
            agent_step="scheduler_run_once",
            step_kind="chain",
            due_count=len(due_processes),
            adapter_count=len(self.adapters),
        )
        summaries: list[SchedulerProcessRunSummary] = []
        for process in due_processes:
            summaries.append(self._run_process(process, now=started_at))
        finished_at = _utc_now()
        return SchedulerWorkerResult(
            started_at=started_at,
            finished_at=finished_at,
            due_count=len(due_processes),
            runs=summaries,
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
            metadata={"kind": process.kind.value},
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
            return SchedulerProcessRunSummary(
                process_id=process.process_id,
                kind=process.kind.value,
                run_id=run_id,
                status=completed.status,
                code=result.code,
                message=result.message or result.output_summary or "Completed.",
            )
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
            return SchedulerProcessRunSummary(
                process_id=process.process_id,
                kind=process.kind.value,
                run_id=run_id,
                status=skipped.status,
                code=skipped.error_code,
                message=message,
            )
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
            return SchedulerProcessRunSummary(
                process_id=process.process_id,
                kind=process.kind.value,
                run_id=run_id,
                status=failed.status,
                code=failed.error_code,
                message=message,
            )
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


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
