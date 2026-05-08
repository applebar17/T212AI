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
    build_scheduler_adapter_registry,
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


class NotifyingAdapter:
    def run(self, process: ScheduledProcess) -> ScheduledAdapterResult:
        return ScheduledAdapterResult(
            status=ScheduledRunStatus.COMPLETED,
            matched=True,
            output_summary=f"Completed {process.process_id}.",
            notification_message="TSLA crossed the configured threshold.",
            notification_metadata={"symbol": "TSLA"},
        )


class ApprovalNotifyingAdapter:
    def run(self, process: ScheduledProcess) -> ScheduledAdapterResult:
        return ScheduledAdapterResult(
            status=ScheduledRunStatus.COMPLETED,
            matched=True,
            output_summary=f"Completed {process.process_id}.",
            notification_message="Approve guarded setup.",
            notification_metadata={"symbol": "TSLA"},
            notification_target_chat_ids=(123,),
            notification_approval_payload={
                "actionId": "pa_test",
                "text": "Approve guarded setup.",
                "approveCallbackData": "pa:approve:pa_test",
                "rejectCallbackData": "pa:reject:pa_test",
            },
        )


class RaisingAdapter:
    def run(self, process: ScheduledProcess) -> ScheduledAdapterResult:
        del process
        raise RuntimeError("adapter exploded")


class FakeNotificationService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def send_process_notification(self, **kwargs):
        self.calls.append(dict(kwargs))
        return object()


def _service(tmp_path: Path, name: str = "scheduler-worker.db") -> ScheduledProcessService:
    engine = build_engine(f"sqlite:///{tmp_path / name}")
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


def _create_due_market_signal_capture(service: ScheduledProcessService):
    return service.create_process(
        title="Semiconductor signal capture",
        kind="market_signal_capture",
        execution_mode="llm_assisted",
        schedule={"type": "polling", "pollEverySeconds": 3600},
        trigger={
            "type": "market_signal_capture",
            "query": "semiconductor AI capex risks",
            "symbols": ["NVDA"],
            "sectors": ["semiconductors"],
            "tags": ["ai_capex"],
        },
        inputs={
            "query": "semiconductor AI capex risks",
            "symbols": ["NVDA"],
            "sectors": ["semiconductors"],
            "tags": ["ai_capex"],
            "maxSignals": 3,
            "searchTimeRange": "day",
        },
        action={"type": "notify_only"},
        lifecycle={"completionPolicy": "keep_running"},
        safety={"brokerActionsAllowed": False},
        now=BASE_NOW,
    )


def _create_due_trade_setup_monitor(service: ScheduledProcessService):
    return service.create_process(
        title="TSLA guarded setup",
        kind="trade_setup_monitor",
        execution_mode="llm_assisted",
        schedule={"type": "polling", "pollEverySeconds": 300},
        trigger={"type": "below_price", "symbol": "TSLA", "value": 180},
        inputs={"symbol": "TSLA"},
        action={"type": "notify_or_propose", "proposalCreationAllowed": False},
        lifecycle={"completionPolicy": "complete_on_first_match"},
        safety={"brokerActionsAllowed": False},
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
        "brokerai scheduler run: due=0 claimed=0 processed=0 completed=0 "
        "skipped=0 failed=0 recovered=0"
    )


def test_scheduler_worker_skips_due_process_without_adapter(tmp_path: Path) -> None:
    service = _service(tmp_path)
    process = _create_due_process(service)
    notifications = FakeNotificationService()
    worker = SchedulerWorker(service, notification_service=notifications)

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
    assert notifications.calls == []


def test_scheduler_worker_registry_skips_instrument_monitor_without_market_data(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    process = _create_due_process(service)
    worker = SchedulerWorker(
        service,
        adapters=build_scheduler_adapter_registry(market_data_service=None),
    )

    result = worker.run_once(now=BASE_NOW)
    updated = service.get_process(process.process_id)

    assert result.skipped_count == 1
    assert result.runs[0].code == "market_data_unavailable"
    assert "adapter_unavailable" not in result.render_text()
    assert updated is not None
    assert updated.failure_count == 0


def test_scheduler_worker_registry_skips_market_signal_capture_without_memory(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    _create_due_market_signal_capture(service)
    worker = SchedulerWorker(
        service,
        adapters=build_scheduler_adapter_registry(),
    )

    result = worker.run_once(now=BASE_NOW)
    updated = service.list_processes(kinds=["market_signal_capture"])[0]

    assert result.skipped_count == 1
    assert result.runs[0].code == "market_signal_memory_unavailable"
    assert "adapter_unavailable" not in result.render_text()
    assert updated.failure_count == 0


def test_scheduler_worker_registry_skips_trade_setup_without_market_data(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    _create_due_trade_setup_monitor(service)
    worker = SchedulerWorker(
        service,
        adapters=build_scheduler_adapter_registry(),
    )

    result = worker.run_once(now=BASE_NOW)

    assert result.skipped_count == 1
    assert result.runs[0].code == "market_data_unavailable"
    assert "adapter_unavailable" not in result.render_text()


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


def test_scheduler_worker_sends_adapter_requested_notification(tmp_path: Path) -> None:
    service = _service(tmp_path)
    process = _create_due_process(service)
    notifications = FakeNotificationService()
    worker = SchedulerWorker(
        service,
        adapters={"instrument_monitor": NotifyingAdapter()},
        notification_service=notifications,
    )

    result = worker.run_once(now=BASE_NOW)

    assert result.completed_count == 1
    assert len(notifications.calls) == 1
    call = notifications.calls[0]
    assert call["process_id"] == process.process_id
    assert call["run_id"] == result.runs[0].run_id
    assert call["message"] == "TSLA crossed the configured threshold."
    assert call["metadata"] == {
        "kind": "instrument_monitor",
        "runStatus": "completed",
        "matched": True,
        "symbol": "TSLA",
    }


def test_scheduler_worker_propagates_approval_notification_payload(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    process = _create_due_process(service)
    notifications = FakeNotificationService()
    worker = SchedulerWorker(
        service,
        adapters={"instrument_monitor": ApprovalNotifyingAdapter()},
        notification_service=notifications,
    )

    result = worker.run_once(now=BASE_NOW)

    assert result.completed_count == 1
    call = notifications.calls[0]
    assert call["process_id"] == process.process_id
    assert call["target_chat_ids"] == (123,)
    assert call["approval_payload"]["actionId"] == "pa_test"
    assert call["approval_payload"]["approveCallbackData"] == "pa:approve:pa_test"


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


def test_scheduler_worker_uses_leases_and_releases_after_run(tmp_path: Path) -> None:
    service = _service(tmp_path)
    process = _create_due_process(service)
    worker = SchedulerWorker(
        service,
        adapters={"instrument_monitor": CompletingAdapter()},
        worker_id="worker-a",
        lease_seconds=60,
    )

    result = worker.run_once(now=BASE_NOW)
    claims = service.claim_due_processes(
        worker_id="worker-b",
        lease_seconds=60,
        now=BASE_NOW + timedelta(seconds=61),
    )

    assert result.claimed_count == 1
    assert result.completed_count == 1
    assert [claim.process.process_id for claim in claims] == [process.process_id]


def test_scheduler_worker_recovers_stale_runs_before_processing(tmp_path: Path) -> None:
    service = _service(tmp_path)
    process = _create_due_process(service)
    stale_run = service.record_run_started(
        process.process_id,
        now=BASE_NOW - timedelta(hours=2),
    )
    worker = SchedulerWorker(
        service,
        adapters={"instrument_monitor": CompletingAdapter()},
        stale_run_after_seconds=3600,
    )

    result = worker.run_once(now=BASE_NOW)
    runs = {run.run_id: run for run in service.list_runs(process.process_id)}

    assert result.recovered_count == 1
    assert runs[stale_run.run_id].status == ScheduledRunStatus.FAILED
    assert runs[stale_run.run_id].error_code == "stale_run_recovered"


def test_scheduler_worker_llm_cap_is_unlimited_by_default_and_optional_when_positive(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    deterministic = _create_due_process(service)
    llm_one = _create_due_market_signal_capture(service)
    llm_two = _create_due_trade_setup_monitor(service)
    worker = SchedulerWorker(
        service,
        adapters={
            "instrument_monitor": CompletingAdapter(),
            "market_signal_capture": CompletingAdapter(),
            "trade_setup_monitor": CompletingAdapter(),
        },
        max_llm_runs_per_pass=1,
    )

    result = worker.run_once(now=BASE_NOW)
    by_process = {run.process_id: run for run in result.runs}

    assert result.completed_count == 2
    assert result.skipped_count == 1
    assert by_process[deterministic.process_id].status == ScheduledRunStatus.COMPLETED
    assert by_process[llm_one.process_id].status == ScheduledRunStatus.COMPLETED
    assert by_process[llm_two.process_id].code == "scheduler_llm_budget_exhausted"

    service = _service(tmp_path, "scheduler-worker-unlimited.db")
    _create_due_market_signal_capture(service)
    _create_due_trade_setup_monitor(service)
    unlimited = SchedulerWorker(
        service,
        adapters={
            "market_signal_capture": CompletingAdapter(),
            "trade_setup_monitor": CompletingAdapter(),
        },
        max_llm_runs_per_pass=0,
    ).run_once(now=BASE_NOW)
    assert unlimited.completed_count == 2
    assert unlimited.skipped_count == 0
