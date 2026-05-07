from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from t212ai.persistence.database import build_engine, build_session_factory, ensure_schema
from t212ai.scheduler import (
    SCHEDULER_AGENT_TOOLBOX,
    ScheduledProcessService,
    SchedulerManagementRuntime,
    build_scheduler_agent_tool_mapping,
    build_scheduler_management_tool_mapping,
    scheduler_archive_process,
    scheduler_create_process,
    scheduler_instrument_monitor_create,
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


def test_scheduler_instrument_monitor_create_applies_defaults(tmp_path: Path) -> None:
    service = _service(tmp_path)
    runtime = SchedulerManagementRuntime(
        service=service,
        default_timezone="UTC",
        default_poll_every_seconds=300,
        clock=lambda: datetime(2026, 5, 7, 10, 30, tzinfo=timezone.utc),
    )

    result = scheduler_instrument_monitor_create(
        title=None,
        description="Alert on downside threshold.",
        symbol="tsla",
        trigger_type="below_price",
        value=180,
        lookback_period="1mo",
        lookback_interval="1d",
        auto_adjust=False,
        poll_every_seconds=None,
        timezone=None,
        expires_at=None,
        notification_enabled=True,
        broker_actions_allowed=False,
        runtime=runtime,
    )

    assert result.status == "ok"
    assert "No broker action" in result.output
    process_id = result.data["process"]["processId"]
    process = service.get_process(process_id)
    assert process is not None
    assert process.kind.value == "instrument_monitor"
    assert process.execution_mode.value == "deterministic"
    assert process.status.value == "active"
    assert process.schedule.type.value == "polling"
    assert process.schedule.poll_every_seconds == 300
    assert process.trigger == {"type": "below_price", "symbol": "TSLA", "value": 180.0}
    assert process.lifecycle.completion_policy.value == "complete_on_first_match"
    assert process.lifecycle.expires_at == datetime(2026, 5, 7, 23, 59, 59, tzinfo=timezone.utc)
    assert process.notification == {"enabled": True}
    assert process.safety.broker_actions_allowed is False


def test_scheduler_instrument_monitor_create_rejects_invalid_inputs(tmp_path: Path) -> None:
    runtime = SchedulerManagementRuntime(service=_service(tmp_path))

    missing_value = scheduler_instrument_monitor_create(
        title=None,
        description="",
        symbol="TSLA",
        trigger_type="above_price",
        value=None,
        lookback_period="1mo",
        lookback_interval="1d",
        auto_adjust=False,
        poll_every_seconds=None,
        timezone=None,
        expires_at=None,
        notification_enabled=True,
        broker_actions_allowed=False,
        runtime=runtime,
    )
    missing_symbol = scheduler_instrument_monitor_create(
        title=None,
        description="",
        symbol="",
        trigger_type="above_price",
        value=200,
        lookback_period="1mo",
        lookback_interval="1d",
        auto_adjust=False,
        poll_every_seconds=None,
        timezone=None,
        expires_at=None,
        notification_enabled=True,
        broker_actions_allowed=False,
        runtime=runtime,
    )
    unsupported = scheduler_instrument_monitor_create(
        title=None,
        description="",
        symbol="TSLA",
        trigger_type="unsupported",
        value=200,
        lookback_period="1mo",
        lookback_interval="1d",
        auto_adjust=False,
        poll_every_seconds=None,
        timezone=None,
        expires_at=None,
        notification_enabled=True,
        broker_actions_allowed=False,
        runtime=runtime,
    )
    unsafe = scheduler_instrument_monitor_create(
        title=None,
        description="",
        symbol="TSLA",
        trigger_type="above_price",
        value=200,
        lookback_period="1mo",
        lookback_interval="1d",
        auto_adjust=False,
        poll_every_seconds=None,
        timezone=None,
        expires_at=None,
        notification_enabled=True,
        broker_actions_allowed=True,
        runtime=runtime,
    )

    for result in (missing_value, missing_symbol, unsupported, unsafe):
        assert result.status == "error"
        assert result.error is not None
        assert result.error.code == "invalid_instrument_monitor_spec"


def test_scheduler_agent_tool_mapping_is_constrained(tmp_path: Path) -> None:
    mapping = build_scheduler_agent_tool_mapping(_service(tmp_path))

    assert set(mapping) == {
        "scheduler_instrument_monitor_create",
        "scheduler_list_processes",
        "scheduler_pause_process",
        "scheduler_resume_process",
        "scheduler_archive_process",
    }
    assert "scheduler_create_process" not in SCHEDULER_AGENT_TOOLBOX.tools_by_name
