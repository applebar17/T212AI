from __future__ import annotations

from pathlib import Path

from t212ai.persistence.database import build_engine, build_session_factory, ensure_schema
from t212ai.scheduler import (
    ScheduledProcessService,
    SchedulerManagementRuntime,
    build_scheduler_management_tool_mapping,
    scheduler_archive_process,
    scheduler_create_process,
    scheduler_list_processes,
    scheduler_pause_process,
    scheduler_resume_process,
)


def _service(tmp_path: Path) -> ScheduledProcessService:
    engine = build_engine(f"sqlite:///{tmp_path / 'scheduler-management.db'}")
    ensure_schema(engine)
    return ScheduledProcessService(build_session_factory(engine))


def test_scheduler_management_tools_create_list_pause_resume_and_archive(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    runtime = SchedulerManagementRuntime(service=service)

    created = scheduler_create_process(
        title="TSLA threshold monitor",
        description="Watch a threshold.",
        kind="instrument_monitor",
        execution_mode="deterministic",
        schedule={"type": "polling", "pollEverySeconds": 60},
        trigger={"type": "below_price", "symbol": "TSLA", "value": 180},
        inputs={"symbols": ["TSLA"]},
        llm_scope={},
        action={},
        notification={"mode": "telegram"},
        lifecycle={"completionPolicy": "keep_running"},
        safety={},
        runtime=runtime,
    )

    assert created.status == "ok"
    process_id = created.data["process"]["processId"]
    assert process_id.startswith("sched_")

    listed = scheduler_list_processes(
        statuses=["active"],
        kinds=["instrument_monitor"],
        limit=10,
        runtime=runtime,
    )
    assert listed.status == "ok"
    assert listed.data["count"] == 1
    assert process_id in listed.output

    paused = scheduler_pause_process(process_id=process_id, runtime=runtime)
    assert paused.status == "ok"
    assert paused.data["process"]["status"] == "paused"

    resumed = scheduler_resume_process(process_id=process_id, runtime=runtime)
    assert resumed.status == "ok"
    assert resumed.data["process"]["status"] == "active"

    archived = scheduler_archive_process(process_id=process_id, runtime=runtime)
    assert archived.status == "ok"
    assert archived.data["process"]["status"] == "archived"
    assert service.get_process(process_id) is not None


def test_scheduler_management_tools_return_verbose_errors(tmp_path: Path) -> None:
    runtime = SchedulerManagementRuntime(service=_service(tmp_path))

    result = scheduler_pause_process(process_id="sched_missing", runtime=runtime)

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "scheduler_management_error"
    assert "exact process id" in result.error.hint


def test_scheduler_management_tools_report_missing_service() -> None:
    runtime = SchedulerManagementRuntime(service=None)

    result = scheduler_list_processes(
        statuses=None,
        kinds=None,
        limit=10,
        runtime=runtime,
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "scheduled_processes_unavailable"


def test_scheduler_management_tool_mapping_exposes_expected_handlers(
    tmp_path: Path,
) -> None:
    mapping = build_scheduler_management_tool_mapping(_service(tmp_path))

    assert set(mapping) == {
        "scheduler_create_process",
        "scheduler_list_processes",
        "scheduler_pause_process",
        "scheduler_resume_process",
        "scheduler_archive_process",
    }
