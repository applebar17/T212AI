from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import inspect, select

from t212ai.persistence.database import build_engine, build_session_factory, ensure_schema
from t212ai.scheduler import (
    ScheduledEventType,
    ScheduledProcessLockRow,
    ScheduledProcessRow,
    ScheduledProcessService,
    ScheduledProcessStatus,
    ScheduledRunStatus,
)


BASE_NOW = datetime(2026, 5, 7, 9, 0, tzinfo=UTC)


def _service(tmp_path: Path, name: str = "scheduler.db"):
    engine = build_engine(f"sqlite:///{tmp_path / name}")
    ensure_schema(engine)
    session_factory = build_session_factory(engine)
    return ScheduledProcessService(session_factory), engine, session_factory


def _lifecycle(policy: str = "keep_running", **updates):
    data = {"completionPolicy": policy}
    data.update(updates)
    return data


def _polling(seconds: int = 60):
    return {"type": "polling", "pollEverySeconds": seconds}


def _create_process(
    service: ScheduledProcessService,
    *,
    now: datetime = BASE_NOW,
    schedule=None,
    lifecycle=None,
    safety=None,
    title: str = "Test process",
):
    return service.create_process(
        title=title,
        kind="instrument_monitor",
        execution_mode="deterministic",
        schedule=schedule or _polling(),
        trigger={"type": "below_price", "symbol": "TSLA", "value": 180},
        inputs={"symbols": ["TSLA"]},
        lifecycle=lifecycle or _lifecycle(),
        safety=safety or {},
        now=now,
    )


def test_scheduler_service_creates_process_and_persists_compact_json(tmp_path: Path) -> None:
    service, _, session_factory = _service(tmp_path)

    process = _create_process(service, title="TSLA price watch")

    assert process.process_id.startswith("sched_")
    assert process.status == ScheduledProcessStatus.ACTIVE
    assert process.schedule.poll_every_seconds == 60
    assert process.safety.broker_actions_allowed is False
    assert process.next_run_at == BASE_NOW

    fetched = service.get_process(process.process_id)
    assert fetched is not None
    assert fetched.trigger["symbol"] == "TSLA"
    assert fetched.inputs["symbols"] == ["TSLA"]

    with session_factory() as session:
        row = session.scalar(
            select(ScheduledProcessRow).where(
                ScheduledProcessRow.process_id == process.process_id
            )
        )
        assert row is not None
        assert row.schedule_json == '{"pollEverySeconds":60,"type":"polling"}'
        assert row.trigger_json == '{"symbol":"TSLA","type":"below_price","value":180}'


def test_scheduler_validation_rejects_invalid_specs(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path)

    with pytest.raises(ValueError, match="title is required"):
        _create_process(service, title="")
    with pytest.raises(ValueError, match="Unsupported ScheduledProcessKind"):
        service.create_process(
            title="Bad kind",
            kind="unknown",
            execution_mode="deterministic",
            schedule=_polling(),
            lifecycle=_lifecycle(),
        )
    with pytest.raises(ValueError, match="one_shot schedule requires run_at"):
        _create_process(service, schedule={"type": "one_shot"})
    with pytest.raises(ValueError, match="Invalid timezone"):
        _create_process(
            service,
            schedule={
                "type": "recurring",
                "frequency": "daily",
                "time": "10:00",
                "timezone": "Not/AZone",
            },
        )
    with pytest.raises(ValueError, match="weekly recurring schedule requires non-empty days"):
        _create_process(
            service,
            schedule={
                "type": "recurring",
                "frequency": "weekly",
                "time": "10:00",
                "timezone": "UTC",
            },
        )
    with pytest.raises(ValueError, match="poll_every_seconds > 0"):
        _create_process(service, schedule={"type": "polling", "pollEverySeconds": 0})
    with pytest.raises(ValueError, match="complete_after_n_matches"):
        _create_process(
            service,
            lifecycle={"completionPolicy": "complete_after_n_matches"},
        )
    with pytest.raises(ValueError, match="Direct broker execution"):
        _create_process(service, safety={"brokerActionsAllowed": True})
    with pytest.raises(ValueError, match="Direct broker execution"):
        service.create_process(
            title="Unsafe action",
            kind="trade_setup_monitor",
            execution_mode="llm_assisted",
            schedule=_polling(),
            lifecycle=_lifecycle(),
            action={"type": "broker_place_order"},
        )


def test_scheduler_computes_initial_next_run_for_supported_schedule_types(
    tmp_path: Path,
) -> None:
    service, _, _ = _service(tmp_path)

    one_shot_at = BASE_NOW + timedelta(hours=2)
    one_shot = _create_process(
        service,
        schedule={"type": "one_shot", "runAt": one_shot_at},
        lifecycle=_lifecycle("complete_on_first_run"),
        title="one shot",
    )
    daily = _create_process(
        service,
        schedule={
            "type": "recurring",
            "frequency": "daily",
            "time": "10:00",
            "timezone": "UTC",
        },
        title="daily",
    )
    weekdays = _create_process(
        service,
        now=datetime(2026, 5, 8, 11, 0, tzinfo=UTC),
        schedule={
            "type": "recurring",
            "frequency": "weekdays",
            "time": "10:00",
            "timezone": "UTC",
        },
        title="weekdays",
    )
    weekly = _create_process(
        service,
        schedule={
            "type": "recurring",
            "frequency": "weekly",
            "days": ["Friday"],
            "time": "08:30",
            "timezone": "UTC",
        },
        title="weekly",
    )
    polling = _create_process(service, schedule=_polling(300), title="polling")
    manual = _create_process(service, schedule={"type": "manual"}, title="manual")

    assert one_shot.next_run_at == one_shot_at
    assert daily.next_run_at == datetime(2026, 5, 7, 10, 0, tzinfo=UTC)
    assert weekdays.next_run_at == datetime(2026, 5, 11, 10, 0, tzinfo=UTC)
    assert weekly.next_run_at == datetime(2026, 5, 8, 8, 30, tzinfo=UTC)
    assert weekly.schedule.days == ["fri"]
    assert polling.next_run_at == BASE_NOW
    assert manual.next_run_at is None


def test_scheduler_lists_due_processes_and_excludes_ineligible_statuses(
    tmp_path: Path,
) -> None:
    service, _, _ = _service(tmp_path)
    due = _create_process(service, title="due")
    future = _create_process(
        service,
        title="future",
        schedule={"type": "one_shot", "runAt": BASE_NOW + timedelta(hours=1)},
    )
    paused = service.pause_process(
        _create_process(service, title="paused").process_id,
        now=BASE_NOW + timedelta(seconds=1),
    )
    archived = service.archive_process(
        _create_process(service, title="archived").process_id,
        now=BASE_NOW + timedelta(seconds=1),
    )
    completed = service.mark_completed(
        _create_process(service, title="completed").process_id,
        now=BASE_NOW + timedelta(seconds=1),
    )
    failed = service.mark_failed(
        _create_process(service, title="failed").process_id,
        now=BASE_NOW + timedelta(seconds=1),
    )
    expired = _create_process(
        service,
        title="expired",
        lifecycle=_lifecycle(expiresAt=BASE_NOW - timedelta(minutes=1)),
    )

    matches = service.list_due_processes(now=BASE_NOW + timedelta(minutes=1))

    assert [process.process_id for process in matches] == [due.process_id]
    assert service.get_process(future.process_id).status == ScheduledProcessStatus.ACTIVE
    assert paused.status == ScheduledProcessStatus.PAUSED
    assert archived.status == ScheduledProcessStatus.ARCHIVED
    assert completed.status == ScheduledProcessStatus.COMPLETED
    assert failed.status == ScheduledProcessStatus.FAILED
    assert service.get_process(expired.process_id).status == ScheduledProcessStatus.EXPIRED


def test_scheduler_lifecycle_transitions_write_events(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path)
    paused_process = _create_process(service, title="pause resume")

    paused = service.pause_process(paused_process.process_id, now=BASE_NOW + timedelta(seconds=1))
    resumed = service.resume_process(paused_process.process_id, now=BASE_NOW + timedelta(minutes=1))
    archived = service.archive_process(resumed.process_id, now=BASE_NOW + timedelta(minutes=2))
    completed = service.mark_completed(
        _create_process(service, title="complete").process_id,
        now=BASE_NOW + timedelta(seconds=1),
    )
    expired = service.mark_expired(
        _create_process(service, title="expire").process_id,
        now=BASE_NOW + timedelta(seconds=1),
    )

    assert paused.status == ScheduledProcessStatus.PAUSED
    assert resumed.status == ScheduledProcessStatus.ACTIVE
    assert archived.status == ScheduledProcessStatus.ARCHIVED
    assert completed.status == ScheduledProcessStatus.COMPLETED
    assert expired.status == ScheduledProcessStatus.EXPIRED

    event_types = [event.event_type for event in service.list_events(paused_process.process_id)]
    assert event_types == [
        ScheduledEventType.CREATED,
        ScheduledEventType.PAUSED,
        ScheduledEventType.RESUMED,
        ScheduledEventType.ARCHIVED,
    ]


def test_scheduler_records_run_completion_failure_and_recomputes_next_run(
    tmp_path: Path,
) -> None:
    service, _, _ = _service(tmp_path)
    process = _create_process(service, schedule=_polling(60))

    run = service.record_run_started(
        process.process_id,
        due_at=process.next_run_at,
        metadata={"attempt": 1},
        now=BASE_NOW,
    )
    completed = service.record_run_completed(
        run.run_id,
        matched=False,
        output_summary="No match.",
        metadata={"checked": True},
        now=BASE_NOW + timedelta(seconds=5),
    )
    failed_run = service.record_run_started(
        process.process_id,
        now=BASE_NOW + timedelta(seconds=70),
    )
    failed = service.record_run_failed(
        failed_run.run_id,
        error_code="market_data_unavailable",
        error_message="Market data unavailable.",
        metadata={"provider": "fake"},
        now=BASE_NOW + timedelta(seconds=75),
    )
    updated = service.get_process(process.process_id)

    assert completed.status == ScheduledRunStatus.COMPLETED
    assert completed.output_summary == "No match."
    assert failed.status == ScheduledRunStatus.FAILED
    assert failed.error_code == "market_data_unavailable"
    assert updated is not None
    assert updated.last_status == ScheduledRunStatus.FAILED
    assert updated.failure_count == 1
    assert updated.next_run_at == BASE_NOW + timedelta(seconds=135)

    event_types = [event.event_type for event in service.list_events(process.process_id)]
    assert event_types == [
        ScheduledEventType.CREATED,
        ScheduledEventType.RUN_STARTED,
        ScheduledEventType.RUN_COMPLETED,
        ScheduledEventType.RUN_STARTED,
        ScheduledEventType.RUN_FAILED,
    ]


def test_scheduler_records_skipped_run_without_failure_count(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path)
    process = _create_process(service, schedule=_polling(60))

    run = service.record_run_started(process.process_id, now=BASE_NOW)
    skipped = service.record_run_skipped(
        run.run_id,
        reason_code="adapter_unavailable",
        reason_message="No adapter registered.",
        metadata={"kind": "instrument_monitor"},
        now=BASE_NOW + timedelta(seconds=5),
    )
    updated = service.get_process(process.process_id)

    assert skipped.status == ScheduledRunStatus.SKIPPED
    assert skipped.error_code == "adapter_unavailable"
    assert skipped.error_message == "No adapter registered."
    assert updated is not None
    assert updated.last_status == ScheduledRunStatus.SKIPPED
    assert updated.failure_count == 0
    assert updated.next_run_at == BASE_NOW + timedelta(seconds=65)

    event_types = [event.event_type for event in service.list_events(process.process_id)]
    assert event_types == [
        ScheduledEventType.CREATED,
        ScheduledEventType.RUN_STARTED,
        ScheduledEventType.RUN_SKIPPED,
    ]


def test_scheduler_leases_prevent_duplicate_claims_and_allow_reclaim(
    tmp_path: Path,
) -> None:
    service_a, _, session_factory = _service(tmp_path)
    service_b = ScheduledProcessService(session_factory)
    process = _create_process(service_a, schedule=_polling(60))

    first_claims = service_a.claim_due_processes(
        worker_id="worker-a",
        lease_seconds=60,
        now=BASE_NOW,
    )
    second_claims = service_b.claim_due_processes(
        worker_id="worker-b",
        lease_seconds=60,
        now=BASE_NOW + timedelta(seconds=1),
    )
    reclaimed = service_b.claim_due_processes(
        worker_id="worker-b",
        lease_seconds=60,
        now=BASE_NOW + timedelta(seconds=61),
    )

    assert [claim.process.process_id for claim in first_claims] == [process.process_id]
    assert second_claims == []
    assert [claim.process.process_id for claim in reclaimed] == [process.process_id]
    assert reclaimed[0].worker_id == "worker-b"
    assert service_a.release_process_lease(process.process_id, reclaimed[0].lease_token)
    assert not service_a.release_process_lease(process.process_id, reclaimed[0].lease_token)


def test_scheduler_recovers_stale_started_runs_but_preserves_active_leases(
    tmp_path: Path,
) -> None:
    service, _, _ = _service(tmp_path)
    stale_process = _create_process(service, title="stale", schedule=_polling(60))
    leased_process = _create_process(service, title="leased", schedule=_polling(60))
    stale_run = service.record_run_started(
        stale_process.process_id,
        now=BASE_NOW - timedelta(hours=2),
    )
    leased_run = service.record_run_started(
        leased_process.process_id,
        now=BASE_NOW - timedelta(hours=2),
    )
    claims = service.claim_due_processes(
        worker_id="active-worker",
        lease_seconds=3600,
        now=BASE_NOW,
        limit=10,
    )
    for claim in claims:
        if claim.process.process_id == stale_process.process_id:
            service.release_process_lease(claim.process.process_id, claim.lease_token)

    dry_run = service.recover_stale_runs(
        stale_after_seconds=3600,
        now=BASE_NOW,
        dry_run=True,
    )
    applied = service.recover_stale_runs(
        stale_after_seconds=3600,
        now=BASE_NOW,
        dry_run=False,
    )

    assert dry_run.dry_run is True
    assert stale_run.run_id in dry_run.run_ids
    assert leased_run.run_id not in dry_run.run_ids
    assert applied.changed_count == 1
    recovered_run = service.list_runs(stale_process.process_id)[0]
    untouched_run = service.list_runs(leased_process.process_id)[0]
    recovered_process = service.get_process(stale_process.process_id)
    assert recovered_run.status == ScheduledRunStatus.FAILED
    assert recovered_run.error_code == "stale_run_recovered"
    assert untouched_run.status == ScheduledRunStatus.STARTED
    assert recovered_process.failure_count == 1


def test_scheduler_cleanup_archived_before_and_export(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path)
    old_process = _create_process(service, title="old archived", schedule=_polling(60))
    keep_process = _create_process(service, title="recent archived", schedule=_polling(60))
    active_process = _create_process(service, title="active", schedule=_polling(60))
    run = service.record_run_started(old_process.process_id, now=BASE_NOW)
    service.record_run_completed(run.run_id, now=BASE_NOW + timedelta(seconds=1))
    service.archive_process(old_process.process_id, now=BASE_NOW + timedelta(days=1))
    service.archive_process(keep_process.process_id, now=BASE_NOW + timedelta(days=10))

    dry_run = service.delete_archived_before(
        BASE_NOW + timedelta(days=2),
        dry_run=True,
    )
    assert dry_run.matched_count == 1
    assert dry_run.changed_count == 0
    assert dry_run.run_count == 1
    assert dry_run.event_count >= 1
    assert service.get_process(old_process.process_id) is not None

    applied = service.delete_archived_before(
        BASE_NOW + timedelta(days=2),
        dry_run=False,
    )
    exported = service.export_processes(include_runs=True, include_events=True)

    assert applied.changed_count == 1
    assert service.get_process(old_process.process_id) is None
    assert service.get_process(keep_process.process_id) is not None
    assert service.get_process(active_process.process_id) is not None
    assert exported["schema"] == "brokerai.scheduler.export.v1"
    assert exported["processCount"] == 2
    assert all("runs" in item and "events" in item for item in exported["processes"])


def test_scheduler_completion_policies_and_cooldown_are_deterministic(
    tmp_path: Path,
) -> None:
    service, _, _ = _service(tmp_path)

    first_run_process = _create_process(
        service,
        title="first run",
        lifecycle=_lifecycle("complete_on_first_run"),
    )
    run = service.record_run_started(first_run_process.process_id, now=BASE_NOW)
    service.record_run_completed(run.run_id, matched=False, now=BASE_NOW + timedelta(seconds=1))
    assert service.get_process(first_run_process.process_id).status == ScheduledProcessStatus.COMPLETED

    first_match_process = _create_process(
        service,
        title="first match",
        lifecycle=_lifecycle("complete_on_first_match"),
    )
    run = service.record_run_started(first_match_process.process_id, now=BASE_NOW)
    service.record_run_completed(run.run_id, matched=False, now=BASE_NOW + timedelta(seconds=1))
    assert service.get_process(first_match_process.process_id).status == ScheduledProcessStatus.ACTIVE
    run = service.record_run_started(first_match_process.process_id, now=BASE_NOW + timedelta(seconds=61))
    service.record_run_completed(run.run_id, matched=True, now=BASE_NOW + timedelta(seconds=62))
    assert service.get_process(first_match_process.process_id).status == ScheduledProcessStatus.COMPLETED

    two_matches_process = _create_process(
        service,
        title="two matches",
        lifecycle=_lifecycle("complete_after_n_matches", maxMatches=2),
    )
    run = service.record_run_started(two_matches_process.process_id, now=BASE_NOW)
    service.record_run_completed(run.run_id, matched=True, now=BASE_NOW + timedelta(seconds=1))
    assert service.get_process(two_matches_process.process_id).status == ScheduledProcessStatus.ACTIVE
    run = service.record_run_started(two_matches_process.process_id, now=BASE_NOW + timedelta(seconds=61))
    service.record_run_completed(run.run_id, matched=True, now=BASE_NOW + timedelta(seconds=62))
    assert service.get_process(two_matches_process.process_id).status == ScheduledProcessStatus.COMPLETED

    cooldown_process = _create_process(
        service,
        title="cooldown",
        schedule=_polling(60),
        lifecycle=_lifecycle("keep_running", cooldownSeconds=300),
    )
    run = service.record_run_started(cooldown_process.process_id, now=BASE_NOW)
    service.record_run_completed(run.run_id, matched=True, now=BASE_NOW + timedelta(seconds=10))
    updated = service.get_process(cooldown_process.process_id)
    assert updated.next_run_at == BASE_NOW + timedelta(seconds=310)


def test_scheduler_schema_is_registered_when_package_is_imported(tmp_path: Path) -> None:
    _, engine, _ = _service(tmp_path)
    inspector = inspect(engine)

    assert inspector.has_table("scheduled_processes")
    assert inspector.has_table("scheduled_process_runs")
    assert inspector.has_table("scheduled_process_events")
    assert inspector.has_table("scheduled_process_locks")
