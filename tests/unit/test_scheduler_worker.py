from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from t212ai.persistence.database import build_engine, build_session_factory, ensure_schema
from t212ai.scheduler import (
    ScheduledAdapterResult,
    ScheduledProcess,
    ScheduledProcessService,
    ScheduledRunStatus,
    SchedulerWorker,
)


BASE_NOW = datetime(2026, 5, 7, 9, 0, tzinfo=UTC)


class CompletingAdapter:
    def run(self, process: ScheduledProcess) -> ScheduledAdapterResult:
        return ScheduledAdapterResult(
            status=ScheduledRunStatus.COMPLETED,
            matched=True,
            output_summary=f"Completed {process.process_id}.",
            message="Adapter completed.",
            metadata={"adapter": "fake"},
        )


class RaisingAdapter:
    def run(self, process: ScheduledProcess) -> ScheduledAdapterResult:
        del process
        raise RuntimeError("adapter exploded")


def _service(tmp_path: Path) -> ScheduledProcessService:
    engine = build_engine(f"sqlite:///{tmp_path / 'scheduler-worker.db'}")
    ensure_schema(engine)
    return ScheduledProcessService(build_session_factory(engine))


def _create_due_process(service: ScheduledProcessService):
    return service.create_process(
        title="TSLA watch",
        kind="instrument_monitor",
        execution_mode="deterministic",
        schedule={"type": "polling", "pollEverySeconds": 60},
        trigger={"type": "below_price", "symbol": "TSLA", "value": 180},
        lifecycle={"completionPolicy": "keep_running"},
        now=BASE_NOW,
    )


def test_scheduler_worker_returns_zero_counts_without_due_processes(tmp_path: Path) -> None:
    service = _service(tmp_path)
    worker = SchedulerWorker(service)

    result = worker.run_once(now=BASE_NOW)

    assert result.due_count == 0
    assert result.processed_count == 0
    assert result.completed_count == 0
    assert result.skipped_count == 0
    assert result.failed_count == 0
    assert result.render_text() == (
        "brokerai scheduler run: due=0 processed=0 completed=0 skipped=0 failed=0"
    )


def test_scheduler_worker_skips_due_process_without_adapter(tmp_path: Path) -> None:
    service = _service(tmp_path)
    process = _create_due_process(service)
    worker = SchedulerWorker(service)

    result = worker.run_once(now=BASE_NOW)
    updated = service.get_process(process.process_id)
    runs = service.list_runs(process.process_id)

    assert result.due_count == 1
    assert result.skipped_count == 1
    assert result.runs[0].code == "adapter_unavailable"
    assert "No scheduler adapter is registered" in result.runs[0].message
    assert "adapter_unavailable" in result.render_text()
    assert runs[0].status == ScheduledRunStatus.SKIPPED
    assert updated is not None
    assert updated.next_run_at == BASE_NOW + timedelta(seconds=60)
    assert updated.failure_count == 0


def test_scheduler_worker_records_completed_adapter_result(tmp_path: Path) -> None:
    service = _service(tmp_path)
    process = _create_due_process(service)
    worker = SchedulerWorker(
        service,
        adapters={"instrument_monitor": CompletingAdapter()},
    )

    result = worker.run_once(now=BASE_NOW)
    updated = service.get_process(process.process_id)
    runs = service.list_runs(process.process_id)

    assert result.due_count == 1
    assert result.completed_count == 1
    assert result.runs[0].message == "Adapter completed."
    assert runs[0].status == ScheduledRunStatus.COMPLETED
    assert runs[0].matched is True
    assert updated is not None
    assert updated.next_run_at == BASE_NOW + timedelta(seconds=60)


def test_scheduler_worker_records_adapter_failure(tmp_path: Path) -> None:
    service = _service(tmp_path)
    process = _create_due_process(service)
    worker = SchedulerWorker(
        service,
        adapters={"instrument_monitor": RaisingAdapter()},
    )

    result = worker.run_once(now=BASE_NOW)
    updated = service.get_process(process.process_id)
    runs = service.list_runs(process.process_id)

    assert result.due_count == 1
    assert result.failed_count == 1
    assert result.runs[0].code == "adapter_error"
    assert "RuntimeError: adapter exploded" == result.runs[0].message
    assert runs[0].status == ScheduledRunStatus.FAILED
    assert updated is not None
    assert updated.failure_count == 1
    assert updated.next_run_at == BASE_NOW + timedelta(seconds=60)
