"""SQL-backed scheduled process service."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from enum import Enum
import json
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError
from sqlalchemy import asc, desc, select
from sqlalchemy.orm import Session, sessionmaker

from .models import (
    LifecycleCompletionPolicy,
    LifecycleSpec,
    ScheduledEventType,
    ScheduledExecutionMode,
    ScheduledProcess,
    ScheduledProcessEvent,
    ScheduledProcessKind,
    ScheduledProcessRun,
    ScheduledProcessSpec,
    ScheduledProcessStatus,
    ScheduledRunStatus,
    ScheduleSpec,
    ScheduleType,
    SafetySpec,
)
from .orm import (
    ScheduledProcessEventRow,
    ScheduledProcessLockRow,
    ScheduledProcessRow,
    ScheduledProcessRunRow,
)


TERMINAL_PROCESS_STATUSES = {
    ScheduledProcessStatus.COMPLETED.value,
    ScheduledProcessStatus.EXPIRED.value,
    ScheduledProcessStatus.ARCHIVED.value,
    ScheduledProcessStatus.FAILED.value,
}

SUPPORTED_RECURRING_FREQUENCIES = {"daily", "weekdays", "weekly"}
VALID_WEEKDAYS = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}
NORMALIZED_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
UNSAFE_ACTION_TYPES = {
    "broker_execute",
    "broker_execution",
    "broker_place_order",
    "broker_cancel_order",
    "cancel_order",
    "execute_order",
    "place_order",
    "submit_order",
}


@dataclass(frozen=True, slots=True)
class ScheduledProcessClaim:
    process: ScheduledProcess
    lease_token: str
    worker_id: str
    leased_until: datetime


@dataclass(frozen=True, slots=True)
class SchedulerMaintenanceResult:
    matched_count: int = 0
    changed_count: int = 0
    process_ids: tuple[str, ...] = ()
    run_ids: tuple[str, ...] = ()
    event_count: int = 0
    run_count: int = 0
    dry_run: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class ScheduledProcessService:
    """Stores scheduled process definitions and deterministic audit state."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def validate_process_spec(
        self,
        *,
        title: str,
        kind: ScheduledProcessKind | str,
        execution_mode: ScheduledExecutionMode | str,
        schedule: ScheduleSpec | dict[str, Any],
        lifecycle: LifecycleSpec | dict[str, Any],
        description: str = "",
        trigger: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        llm_scope: dict[str, Any] | None = None,
        action: dict[str, Any] | None = None,
        notification: dict[str, Any] | None = None,
        safety: SafetySpec | dict[str, Any] | None = None,
    ) -> ScheduledProcessSpec:
        resolved_spec = _build_process_spec(
            title=title,
            description=description,
            kind=kind,
            execution_mode=execution_mode,
            schedule=schedule,
            trigger=trigger,
            inputs=inputs,
            llm_scope=llm_scope,
            action=action,
            notification=notification,
            lifecycle=lifecycle,
            safety=safety,
        )
        _validate_process_spec(resolved_spec)
        return resolved_spec

    def create_process(
        self,
        *,
        title: str,
        kind: ScheduledProcessKind | str,
        execution_mode: ScheduledExecutionMode | str,
        schedule: ScheduleSpec | dict[str, Any],
        lifecycle: LifecycleSpec | dict[str, Any],
        description: str = "",
        trigger: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        llm_scope: dict[str, Any] | None = None,
        action: dict[str, Any] | None = None,
        notification: dict[str, Any] | None = None,
        safety: SafetySpec | dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> ScheduledProcess:
        spec = self.validate_process_spec(
            title=title,
            description=description,
            kind=kind,
            execution_mode=execution_mode,
            schedule=schedule,
            trigger=trigger,
            inputs=inputs,
            llm_scope=llm_scope,
            action=action,
            notification=notification,
            lifecycle=lifecycle,
            safety=safety,
        )
        created_at = _ensure_aware(now) if now is not None else _utc_now()
        row = ScheduledProcessRow(
            process_id=_new_process_id(),
            title=spec.title,
            description=spec.description,
            kind=spec.kind.value,
            execution_mode=spec.execution_mode.value,
            status=ScheduledProcessStatus.ACTIVE.value,
            schedule_json=_json_model(spec.schedule),
            trigger_json=_json_dict(spec.trigger),
            inputs_json=_json_dict(spec.inputs),
            llm_scope_json=_json_dict(spec.llm_scope),
            action_json=_json_dict(spec.action),
            notification_json=_json_dict(spec.notification),
            lifecycle_json=_json_model(spec.lifecycle),
            safety_json=_json_model(spec.safety),
            created_at=created_at,
            updated_at=created_at,
            next_run_at=_initial_next_run_at(spec.schedule, created_at),
            last_run_at=None,
            last_status=None,
            failure_count=0,
        )
        with self._session_scope() as session:
            session.add(row)
            _add_event(
                session,
                process_id=row.process_id,
                event_type=ScheduledEventType.CREATED,
                message="Scheduled process created.",
                created_at=created_at,
                details={"kind": row.kind, "executionMode": row.execution_mode},
            )
            session.flush()
            return _process_model(row)

    def get_process(self, process_id: str) -> ScheduledProcess | None:
        with self._session_scope() as session:
            row = session.get(ScheduledProcessRow, str(process_id))
            return _process_model(row) if row is not None else None

    def list_processes(
        self,
        *,
        statuses: list[ScheduledProcessStatus | str] | None = None,
        kinds: list[ScheduledProcessKind | str] | None = None,
        limit: int = 50,
    ) -> list[ScheduledProcess]:
        resolved_limit = _safe_limit(limit, default=50, maximum=250)
        with self._session_scope() as session:
            query = select(ScheduledProcessRow)
            if statuses:
                query = query.where(
                    ScheduledProcessRow.status.in_(
                        [_coerce_enum(ScheduledProcessStatus, status).value for status in statuses]
                    )
                )
            if kinds:
                query = query.where(
                    ScheduledProcessRow.kind.in_(
                        [_coerce_enum(ScheduledProcessKind, kind).value for kind in kinds]
                    )
                )
            query = query.order_by(desc(ScheduledProcessRow.updated_at)).limit(resolved_limit)
            return [_process_model(row) for row in session.scalars(query).all()]

    def claim_due_processes(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime | None = None,
        limit: int = 100,
    ) -> list[ScheduledProcessClaim]:
        resolved_worker = _required_text(worker_id, "worker_id")
        resolved_lease_seconds = _positive_int(lease_seconds, "lease_seconds")
        cutoff = _ensure_aware(now) if now is not None else _utc_now()
        leased_until = cutoff + timedelta(seconds=resolved_lease_seconds)
        resolved_limit = _safe_limit(limit, default=100, maximum=500)
        claims: list[ScheduledProcessClaim] = []
        with self._session_scope() as session:
            self._expire_active_processes(session, cutoff)
            query = (
                select(ScheduledProcessRow)
                .where(
                    ScheduledProcessRow.status == ScheduledProcessStatus.ACTIVE.value,
                    ScheduledProcessRow.next_run_at.is_not(None),
                    ScheduledProcessRow.next_run_at <= cutoff,
                )
                .order_by(asc(ScheduledProcessRow.next_run_at))
                .limit(resolved_limit)
            )
            for process in session.scalars(query).all():
                lock = session.get(ScheduledProcessLockRow, process.process_id)
                if lock is not None and _ensure_aware(lock.leased_until) > cutoff:
                    continue
                lease_token = _new_lease_token()
                if lock is None:
                    lock = ScheduledProcessLockRow(
                        process_id=process.process_id,
                        lease_token=lease_token,
                        worker_id=resolved_worker,
                        leased_until=leased_until,
                        created_at=cutoff,
                        updated_at=cutoff,
                    )
                    session.add(lock)
                else:
                    lock.lease_token = lease_token
                    lock.worker_id = resolved_worker
                    lock.leased_until = leased_until
                    lock.updated_at = cutoff
                claims.append(
                    ScheduledProcessClaim(
                        process=_process_model(process),
                        lease_token=lease_token,
                        worker_id=resolved_worker,
                        leased_until=leased_until,
                    )
                )
            session.flush()
            return claims

    def release_process_lease(self, process_id: str, lease_token: str) -> bool:
        with self._session_scope() as session:
            lock = session.get(ScheduledProcessLockRow, str(process_id))
            if lock is None or lock.lease_token != str(lease_token):
                return False
            session.delete(lock)
            session.flush()
            return True

    def claim_process(
        self,
        process_id: str,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> ScheduledProcessClaim | None:
        resolved_worker = _required_text(worker_id, "worker_id")
        resolved_lease_seconds = _positive_int(lease_seconds, "lease_seconds")
        resolved_now = _ensure_aware(now) if now is not None else _utc_now()
        leased_until = resolved_now + timedelta(seconds=resolved_lease_seconds)
        with self._session_scope() as session:
            row = session.get(ScheduledProcessRow, str(process_id))
            if row is None or row.status != ScheduledProcessStatus.ACTIVE.value:
                return None
            lock = session.get(ScheduledProcessLockRow, row.process_id)
            if lock is not None and _ensure_aware(lock.leased_until) > resolved_now:
                return None
            lease_token = _new_lease_token()
            if lock is None:
                lock = ScheduledProcessLockRow(
                    process_id=row.process_id,
                    lease_token=lease_token,
                    worker_id=resolved_worker,
                    leased_until=leased_until,
                    created_at=resolved_now,
                    updated_at=resolved_now,
                )
                session.add(lock)
            else:
                lock.lease_token = lease_token
                lock.worker_id = resolved_worker
                lock.leased_until = leased_until
                lock.updated_at = resolved_now
            session.flush()
            return ScheduledProcessClaim(
                process=_process_model(row),
                lease_token=lease_token,
                worker_id=resolved_worker,
                leased_until=leased_until,
            )

    def refresh_process_lease(
        self,
        process_id: str,
        lease_token: str,
        *,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> bool:
        resolved_lease_seconds = _positive_int(lease_seconds, "lease_seconds")
        resolved_now = _ensure_aware(now) if now is not None else _utc_now()
        with self._session_scope() as session:
            lock = session.get(ScheduledProcessLockRow, str(process_id))
            if lock is None or lock.lease_token != str(lease_token):
                return False
            lock.leased_until = resolved_now + timedelta(seconds=resolved_lease_seconds)
            lock.updated_at = resolved_now
            session.flush()
            return True

    def recover_stale_runs(
        self,
        *,
        stale_after_seconds: int,
        now: datetime | None = None,
        limit: int = 100,
        dry_run: bool = False,
    ) -> SchedulerMaintenanceResult:
        resolved_stale_after = _positive_int(stale_after_seconds, "stale_after_seconds")
        resolved_now = _ensure_aware(now) if now is not None else _utc_now()
        cutoff = resolved_now - timedelta(seconds=resolved_stale_after)
        resolved_limit = _safe_limit(limit, default=100, maximum=500)
        matched_run_ids: list[str] = []
        changed_run_ids: list[str] = []
        changed_process_ids: list[str] = []
        with self._session_scope() as session:
            query = (
                select(ScheduledProcessRunRow)
                .where(
                    ScheduledProcessRunRow.status == ScheduledRunStatus.STARTED.value,
                    ScheduledProcessRunRow.started_at <= cutoff,
                )
                .order_by(asc(ScheduledProcessRunRow.started_at))
                .limit(resolved_limit)
            )
            rows = list(session.scalars(query).all())
            for row in rows:
                lock = session.get(ScheduledProcessLockRow, row.process_id)
                if lock is not None and _ensure_aware(lock.leased_until) > resolved_now:
                    continue
                matched_run_ids.append(row.run_id)
                if dry_run:
                    continue
                process = _required_process_row(session, row.process_id)
                row.status = ScheduledRunStatus.FAILED.value
                row.finished_at = resolved_now
                row.matched = 0
                row.error_code = "stale_run_recovered"
                row.error_message = (
                    "Scheduler recovered a stale started run after worker interruption."
                )
                metadata = _load_json_dict(row.metadata_json)
                metadata["staleRecoveredAt"] = resolved_now.isoformat()
                metadata["staleCutoff"] = cutoff.isoformat()
                row.metadata_json = _json_dict(metadata)
                process.last_run_at = resolved_now
                process.last_status = ScheduledRunStatus.FAILED.value
                process.failure_count = int(process.failure_count or 0) + 1
                process.updated_at = resolved_now
                if process.status == ScheduledProcessStatus.ACTIVE.value:
                    process.next_run_at = _next_run_after_completion(
                        _schedule_model(process),
                        _lifecycle_model(process),
                        resolved_now,
                        matched=False,
                    )
                _add_event(
                    session,
                    process_id=process.process_id,
                    run_id=row.run_id,
                    event_type=ScheduledEventType.RUN_FAILED,
                    message=row.error_message,
                    created_at=resolved_now,
                    details={"errorCode": row.error_code, "recovered": True},
                )
                changed_run_ids.append(row.run_id)
                changed_process_ids.append(process.process_id)
            session.flush()
            return SchedulerMaintenanceResult(
                matched_count=len(matched_run_ids),
                changed_count=len(changed_run_ids),
                process_ids=tuple(dict.fromkeys(changed_process_ids)),
                run_ids=tuple(matched_run_ids),
                dry_run=bool(dry_run),
                metadata={
                    "staleAfterSeconds": resolved_stale_after,
                    "cutoff": cutoff.isoformat(),
                },
            )

    def delete_archived_before(
        self,
        cutoff: datetime,
        *,
        dry_run: bool = True,
    ) -> SchedulerMaintenanceResult:
        resolved_cutoff = _ensure_aware(cutoff)
        with self._session_scope() as session:
            processes = list(
                session.scalars(
                    select(ScheduledProcessRow)
                    .where(
                        ScheduledProcessRow.status == ScheduledProcessStatus.ARCHIVED.value,
                        ScheduledProcessRow.updated_at <= resolved_cutoff,
                    )
                    .order_by(asc(ScheduledProcessRow.updated_at))
                ).all()
            )
            process_ids = [row.process_id for row in processes]
            if not process_ids:
                return SchedulerMaintenanceResult(dry_run=bool(dry_run))
            runs = list(
                session.scalars(
                    select(ScheduledProcessRunRow).where(
                        ScheduledProcessRunRow.process_id.in_(process_ids)
                    )
                ).all()
            )
            events = list(
                session.scalars(
                    select(ScheduledProcessEventRow).where(
                        ScheduledProcessEventRow.process_id.in_(process_ids)
                    )
                ).all()
            )
            locks = list(
                session.scalars(
                    select(ScheduledProcessLockRow).where(
                        ScheduledProcessLockRow.process_id.in_(process_ids)
                    )
                ).all()
            )
            if not dry_run:
                for row in [*events, *runs, *locks, *processes]:
                    session.delete(row)
                session.flush()
            return SchedulerMaintenanceResult(
                matched_count=len(process_ids),
                changed_count=0 if dry_run else len(process_ids),
                process_ids=tuple(process_ids),
                run_count=len(runs),
                event_count=len(events),
                dry_run=bool(dry_run),
                metadata={"cutoff": resolved_cutoff.isoformat()},
            )

    def scheduler_status(self, *, now: datetime | None = None) -> dict[str, Any]:
        resolved_now = _ensure_aware(now) if now is not None else _utc_now()
        with self._session_scope() as session:
            self._expire_active_processes(session, resolved_now)
            processes = list(session.scalars(select(ScheduledProcessRow)).all())
            started_runs = list(
                session.scalars(
                    select(ScheduledProcessRunRow).where(
                        ScheduledProcessRunRow.status == ScheduledRunStatus.STARTED.value
                    )
                ).all()
            )
            active_locks = list(
                session.scalars(
                    select(ScheduledProcessLockRow).where(
                        ScheduledProcessLockRow.leased_until > resolved_now
                    )
                ).all()
            )
            due_count = sum(
                1
                for process in processes
                if process.status == ScheduledProcessStatus.ACTIVE.value
                and process.next_run_at is not None
                and _ensure_aware(process.next_run_at) <= resolved_now
            )
            by_status: dict[str, int] = {}
            by_kind: dict[str, int] = {}
            for process in processes:
                by_status[process.status] = by_status.get(process.status, 0) + 1
                by_kind[process.kind] = by_kind.get(process.kind, 0) + 1
            return {
                "asOf": resolved_now.isoformat(),
                "processCount": len(processes),
                "processesByStatus": dict(sorted(by_status.items())),
                "processesByKind": dict(sorted(by_kind.items())),
                "dueCount": due_count,
                "startedRunCount": len(started_runs),
                "activeLeaseCount": len(active_locks),
                "oldestStartedRunAt": (
                    min(_ensure_aware(row.started_at) for row in started_runs).isoformat()
                    if started_runs
                    else None
                ),
                "nextRunAt": (
                    min(
                        _ensure_aware(row.next_run_at)
                        for row in processes
                        if row.next_run_at is not None
                        and row.status == ScheduledProcessStatus.ACTIVE.value
                    ).isoformat()
                    if any(
                        row.next_run_at is not None
                        and row.status == ScheduledProcessStatus.ACTIVE.value
                        for row in processes
                    )
                    else None
                ),
            }

    def export_processes(
        self,
        *,
        statuses: list[ScheduledProcessStatus | str] | None = None,
        kinds: list[ScheduledProcessKind | str] | None = None,
        include_runs: bool = False,
        include_events: bool = False,
        limit: int = 500,
    ) -> dict[str, Any]:
        processes = self.list_processes(statuses=statuses, kinds=kinds, limit=limit)
        payload: list[dict[str, Any]] = []
        for process in processes:
            item = process.model_dump(by_alias=True, exclude_none=True, mode="json")
            if include_runs:
                item["runs"] = [
                    run.model_dump(by_alias=True, exclude_none=True, mode="json")
                    for run in self.list_runs(process.process_id, limit=500)
                ]
            if include_events:
                item["events"] = [
                    event.model_dump(by_alias=True, exclude_none=True, mode="json")
                    for event in self.list_events(process.process_id, limit=500)
                ]
            payload.append(item)
        return {
            "schema": "brokerai.scheduler.export.v1",
            "exportedAt": _utc_now().isoformat(),
            "processCount": len(payload),
            "processes": payload,
        }

    def pause_process(
        self,
        process_id: str,
        *,
        now: datetime | None = None,
    ) -> ScheduledProcess:
        resolved_now = _ensure_aware(now) if now is not None else _utc_now()
        with self._session_scope() as session:
            row = _required_process_row(session, process_id)
            if row.status in TERMINAL_PROCESS_STATUSES:
                raise ValueError(f"Scheduled process '{process_id}' cannot be paused from {row.status}.")
            if row.status != ScheduledProcessStatus.PAUSED.value:
                row.status = ScheduledProcessStatus.PAUSED.value
                row.updated_at = resolved_now
                _add_event(
                    session,
                    process_id=row.process_id,
                    event_type=ScheduledEventType.PAUSED,
                    message="Scheduled process paused.",
                    created_at=row.updated_at,
                )
            session.flush()
            return _process_model(row)

    def resume_process(
        self,
        process_id: str,
        *,
        now: datetime | None = None,
    ) -> ScheduledProcess:
        resolved_now = _ensure_aware(now) if now is not None else _utc_now()
        with self._session_scope() as session:
            row = _required_process_row(session, process_id)
            if row.status in TERMINAL_PROCESS_STATUSES:
                raise ValueError(f"Scheduled process '{process_id}' cannot be resumed from {row.status}.")
            if row.status != ScheduledProcessStatus.ACTIVE.value:
                row.status = ScheduledProcessStatus.ACTIVE.value
                row.next_run_at = _initial_next_run_at(_schedule_model(row), resolved_now)
                row.updated_at = resolved_now
                _add_event(
                    session,
                    process_id=row.process_id,
                    event_type=ScheduledEventType.RESUMED,
                    message="Scheduled process resumed.",
                    created_at=resolved_now,
                )
            session.flush()
            return _process_model(row)

    def archive_process(
        self,
        process_id: str,
        *,
        now: datetime | None = None,
    ) -> ScheduledProcess:
        resolved_now = _ensure_aware(now) if now is not None else _utc_now()
        with self._session_scope() as session:
            row = _required_process_row(session, process_id)
            row.status = ScheduledProcessStatus.ARCHIVED.value
            row.next_run_at = None
            row.updated_at = resolved_now
            _add_event(
                session,
                process_id=row.process_id,
                event_type=ScheduledEventType.ARCHIVED,
                message="Scheduled process archived.",
                created_at=row.updated_at,
            )
            session.flush()
            return _process_model(row)

    def mark_completed(
        self,
        process_id: str,
        *,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> ScheduledProcess:
        return self._mark_terminal(
            process_id,
            status=ScheduledProcessStatus.COMPLETED,
            event_type=ScheduledEventType.COMPLETED,
            message=reason or "Scheduled process completed.",
            now=now,
        )

    def mark_expired(
        self,
        process_id: str,
        *,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> ScheduledProcess:
        return self._mark_terminal(
            process_id,
            status=ScheduledProcessStatus.EXPIRED,
            event_type=ScheduledEventType.EXPIRED,
            message=reason or "Scheduled process expired.",
            now=now,
        )

    def mark_failed(
        self,
        process_id: str,
        *,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> ScheduledProcess:
        return self._mark_terminal(
            process_id,
            status=ScheduledProcessStatus.FAILED,
            event_type=ScheduledEventType.FAILED,
            message=reason or "Scheduled process failed.",
            now=now,
        )

    def record_run_started(
        self,
        process_id: str,
        *,
        due_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> ScheduledProcessRun:
        started_at = _ensure_aware(now) if now is not None else _utc_now()
        resolved_due_at = _ensure_aware(due_at) if due_at is not None else None
        row = ScheduledProcessRunRow(
            run_id=_new_run_id(),
            process_id=str(process_id),
            status=ScheduledRunStatus.STARTED.value,
            started_at=started_at,
            finished_at=None,
            due_at=resolved_due_at,
            matched=0,
            output_summary=None,
            error_code=None,
            error_message=None,
            metadata_json=_json_dict(metadata or {}),
        )
        with self._session_scope() as session:
            process = _required_process_row(session, process_id)
            session.add(row)
            process.last_run_at = started_at
            process.last_status = ScheduledRunStatus.STARTED.value
            process.updated_at = started_at
            _add_event(
                session,
                process_id=process.process_id,
                run_id=row.run_id,
                event_type=ScheduledEventType.RUN_STARTED,
                message="Scheduled process run started.",
                created_at=started_at,
                details={"dueAt": resolved_due_at.isoformat() if resolved_due_at else None},
            )
            session.flush()
            return _run_model(row)

    def record_run_completed(
        self,
        run_id: str,
        *,
        matched: bool = False,
        output_summary: str | None = None,
        metadata: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> ScheduledProcessRun:
        finished_at = _ensure_aware(now) if now is not None else _utc_now()
        with self._session_scope() as session:
            row = _required_run_row(session, run_id)
            process = _required_process_row(session, row.process_id)
            row.status = ScheduledRunStatus.COMPLETED.value
            row.finished_at = finished_at
            row.matched = 1 if matched else 0
            row.output_summary = output_summary
            row.error_code = None
            row.error_message = None
            row.metadata_json = _json_dict(metadata or {})
            process.last_run_at = finished_at
            process.last_status = ScheduledRunStatus.COMPLETED.value
            process.updated_at = finished_at
            _add_event(
                session,
                process_id=process.process_id,
                run_id=row.run_id,
                event_type=ScheduledEventType.RUN_COMPLETED,
                message="Scheduled process run completed.",
                created_at=finished_at,
                details={"matched": bool(matched)},
            )
            if matched:
                _add_event(
                    session,
                    process_id=process.process_id,
                    run_id=row.run_id,
                    event_type=ScheduledEventType.TRIGGER_MATCHED,
                    message="Scheduled process trigger matched.",
                    created_at=finished_at,
                )
            session.flush()
            self._apply_success_lifecycle(
                session,
                process,
                run_id=row.run_id,
                matched=matched,
                finished_at=finished_at,
            )
            session.flush()
            return _run_model(row)

    def record_run_failed(
        self,
        run_id: str,
        *,
        error_code: str,
        error_message: str,
        metadata: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> ScheduledProcessRun:
        finished_at = _ensure_aware(now) if now is not None else _utc_now()
        with self._session_scope() as session:
            row = _required_run_row(session, run_id)
            process = _required_process_row(session, row.process_id)
            row.status = ScheduledRunStatus.FAILED.value
            row.finished_at = finished_at
            row.matched = 0
            row.error_code = _required_text(error_code, "error_code")
            row.error_message = _required_text(error_message, "error_message")
            row.metadata_json = _json_dict(metadata or {})
            process.last_run_at = finished_at
            process.last_status = ScheduledRunStatus.FAILED.value
            process.failure_count = int(process.failure_count or 0) + 1
            process.updated_at = finished_at
            if process.status == ScheduledProcessStatus.ACTIVE.value:
                process.next_run_at = _next_run_after_completion(
                    _schedule_model(process),
                    _lifecycle_model(process),
                    finished_at,
                    matched=False,
                )
            _add_event(
                session,
                process_id=process.process_id,
                run_id=row.run_id,
                event_type=ScheduledEventType.RUN_FAILED,
                message=row.error_message,
                created_at=finished_at,
                details={"errorCode": row.error_code},
            )
            session.flush()
            return _run_model(row)

    def record_run_skipped(
        self,
        run_id: str,
        *,
        reason_code: str,
        reason_message: str,
        metadata: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> ScheduledProcessRun:
        finished_at = _ensure_aware(now) if now is not None else _utc_now()
        with self._session_scope() as session:
            row = _required_run_row(session, run_id)
            process = _required_process_row(session, row.process_id)
            row.status = ScheduledRunStatus.SKIPPED.value
            row.finished_at = finished_at
            row.matched = 0
            row.output_summary = _required_text(reason_message, "reason_message")
            row.error_code = _required_text(reason_code, "reason_code")
            row.error_message = row.output_summary
            row.metadata_json = _json_dict(metadata or {})
            process.last_run_at = finished_at
            process.last_status = ScheduledRunStatus.SKIPPED.value
            process.updated_at = finished_at
            if process.status == ScheduledProcessStatus.ACTIVE.value:
                process.next_run_at = _next_run_after_completion(
                    _schedule_model(process),
                    _lifecycle_model(process),
                    finished_at,
                    matched=False,
                )
            _add_event(
                session,
                process_id=process.process_id,
                run_id=row.run_id,
                event_type=ScheduledEventType.RUN_SKIPPED,
                message=row.output_summary,
                created_at=finished_at,
                details={"reasonCode": row.error_code},
            )
            session.flush()
            return _run_model(row)

    def list_due_processes(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> list[ScheduledProcess]:
        cutoff = _ensure_aware(now) if now is not None else _utc_now()
        resolved_limit = _safe_limit(limit, default=100, maximum=500)
        with self._session_scope() as session:
            self._expire_active_processes(session, cutoff)
            query = (
                select(ScheduledProcessRow)
                .where(
                    ScheduledProcessRow.status == ScheduledProcessStatus.ACTIVE.value,
                    ScheduledProcessRow.next_run_at.is_not(None),
                    ScheduledProcessRow.next_run_at <= cutoff,
                )
                .order_by(asc(ScheduledProcessRow.next_run_at))
                .limit(resolved_limit)
            )
            rows = list(session.scalars(query).all())
            return [_process_model(row) for row in rows]

    def list_runs(self, process_id: str, *, limit: int = 100) -> list[ScheduledProcessRun]:
        resolved_limit = _safe_limit(limit, default=100, maximum=500)
        with self._session_scope() as session:
            query = (
                select(ScheduledProcessRunRow)
                .where(ScheduledProcessRunRow.process_id == str(process_id))
                .order_by(asc(ScheduledProcessRunRow.started_at))
                .limit(resolved_limit)
            )
            return [_run_model(row) for row in session.scalars(query).all()]

    def list_events(self, process_id: str, *, limit: int = 100) -> list[ScheduledProcessEvent]:
        resolved_limit = _safe_limit(limit, default=100, maximum=500)
        with self._session_scope() as session:
            query = (
                select(ScheduledProcessEventRow)
                .where(ScheduledProcessEventRow.process_id == str(process_id))
                .order_by(asc(ScheduledProcessEventRow.created_at))
                .limit(resolved_limit)
            )
            return [_event_model(row) for row in session.scalars(query).all()]

    def record_event(
        self,
        process_id: str,
        *,
        event_type: ScheduledEventType | str,
        message: str,
        run_id: str | None = None,
        details: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> ScheduledProcessEvent:
        resolved_now = _ensure_aware(now) if now is not None else _utc_now()
        resolved_event_type = _coerce_enum(ScheduledEventType, event_type)
        with self._session_scope() as session:
            _required_process_row(session, process_id)
            if run_id is not None:
                run_row = _required_run_row(session, run_id)
                if run_row.process_id != str(process_id):
                    raise ValueError(
                        f"Scheduled process run '{run_id}' does not belong to '{process_id}'."
                    )
            row = _add_event(
                session,
                process_id=str(process_id),
                run_id=str(run_id) if run_id is not None else None,
                event_type=resolved_event_type,
                message=_required_text(message, "message"),
                created_at=resolved_now,
                details=details or {},
            )
            session.flush()
            return _event_model(row)

    def _mark_terminal(
        self,
        process_id: str,
        *,
        status: ScheduledProcessStatus,
        event_type: ScheduledEventType,
        message: str,
        now: datetime | None,
    ) -> ScheduledProcess:
        resolved_now = _ensure_aware(now) if now is not None else _utc_now()
        with self._session_scope() as session:
            row = _required_process_row(session, process_id)
            row.status = status.value
            row.next_run_at = None
            row.updated_at = resolved_now
            _add_event(
                session,
                process_id=row.process_id,
                event_type=event_type,
                message=message,
                created_at=row.updated_at,
            )
            session.flush()
            return _process_model(row)

    def _apply_success_lifecycle(
        self,
        session: Session,
        process: ScheduledProcessRow,
        *,
        run_id: str,
        matched: bool,
        finished_at: datetime,
    ) -> None:
        if process.status != ScheduledProcessStatus.ACTIVE.value:
            return
        lifecycle = _lifecycle_model(process)
        should_complete = False
        if lifecycle.completion_policy == LifecycleCompletionPolicy.COMPLETE_ON_FIRST_RUN:
            should_complete = True
        elif (
            lifecycle.completion_policy == LifecycleCompletionPolicy.COMPLETE_ON_FIRST_MATCH
            and matched
        ):
            should_complete = True
        elif lifecycle.completion_policy == LifecycleCompletionPolicy.COMPLETE_AFTER_N_MATCHES:
            match_count = _completed_match_count(session, process.process_id)
            should_complete = (
                lifecycle.max_matches is not None
                and match_count >= lifecycle.max_matches
            )
        if should_complete:
            process.status = ScheduledProcessStatus.COMPLETED.value
            process.next_run_at = None
            process.updated_at = finished_at
            _add_event(
                session,
                process_id=process.process_id,
                run_id=run_id,
                event_type=ScheduledEventType.COMPLETED,
                message="Scheduled process completed by lifecycle policy.",
                created_at=finished_at,
                details={"completionPolicy": lifecycle.completion_policy.value},
            )
            return
        process.next_run_at = _next_run_after_completion(
            _schedule_model(process),
            lifecycle,
            finished_at,
            matched=matched,
        )

    def _expire_active_processes(self, session: Session, now: datetime) -> None:
        rows = session.scalars(
            select(ScheduledProcessRow).where(
                ScheduledProcessRow.status == ScheduledProcessStatus.ACTIVE.value
            )
        ).all()
        for row in rows:
            lifecycle = _lifecycle_model(row)
            if lifecycle.expires_at is None:
                continue
            expires_at = _ensure_aware(lifecycle.expires_at)
            if expires_at > now:
                continue
            row.status = ScheduledProcessStatus.EXPIRED.value
            row.next_run_at = None
            row.updated_at = now
            _add_event(
                session,
                process_id=row.process_id,
                event_type=ScheduledEventType.EXPIRED,
                message="Scheduled process expired.",
                created_at=now,
                details={"expiresAt": expires_at.isoformat()},
            )

    @contextmanager
    def _session_scope(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def _build_process_spec(
    *,
    title: str,
    description: str,
    kind: ScheduledProcessKind | str,
    execution_mode: ScheduledExecutionMode | str,
    schedule: ScheduleSpec | dict[str, Any],
    trigger: dict[str, Any] | None,
    inputs: dict[str, Any] | None,
    llm_scope: dict[str, Any] | None,
    action: dict[str, Any] | None,
    notification: dict[str, Any] | None,
    lifecycle: LifecycleSpec | dict[str, Any],
    safety: SafetySpec | dict[str, Any] | None,
) -> ScheduledProcessSpec:
    try:
        return ScheduledProcessSpec(
            title=_required_text(title, "title"),
            description=str(description or "").strip(),
            kind=_coerce_enum(ScheduledProcessKind, kind),
            execution_mode=_coerce_enum(ScheduledExecutionMode, execution_mode),
            schedule=_coerce_schedule(schedule),
            trigger=_clean_dict(trigger, "trigger"),
            inputs=_clean_dict(inputs, "inputs"),
            llm_scope=_clean_dict(llm_scope, "llm_scope"),
            action=_clean_dict(action, "action"),
            notification=_clean_dict(notification, "notification"),
            lifecycle=_coerce_lifecycle(lifecycle),
            safety=_coerce_safety(safety),
        )
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


def _validate_process_spec(spec: ScheduledProcessSpec) -> None:
    _validate_schedule(spec.schedule)
    _validate_lifecycle(spec.lifecycle)
    _validate_safety(spec.safety)
    _validate_action(spec.action)


def _validate_schedule(schedule: ScheduleSpec) -> None:
    if schedule.type == ScheduleType.ONE_SHOT:
        if schedule.run_at is None:
            raise ValueError("one_shot schedule requires run_at.")
        _ensure_aware(schedule.run_at)
        return
    if schedule.type == ScheduleType.RECURRING:
        frequency = str(schedule.frequency or "").strip().lower()
        if frequency not in SUPPORTED_RECURRING_FREQUENCIES:
            raise ValueError("recurring schedule requires frequency daily, weekdays, or weekly.")
        if not str(schedule.time or "").strip():
            raise ValueError("recurring schedule requires time.")
        if not str(schedule.timezone or "").strip():
            raise ValueError("recurring schedule requires timezone.")
        _parse_local_time(str(schedule.time))
        _zone_info(str(schedule.timezone))
        if frequency == "weekly" and not schedule.days:
            raise ValueError("weekly recurring schedule requires non-empty days.")
        if schedule.days:
            _normalize_days(schedule.days)
        return
    if schedule.type == ScheduleType.POLLING:
        if schedule.poll_every_seconds is None or schedule.poll_every_seconds <= 0:
            raise ValueError("polling schedule requires poll_every_seconds > 0.")
        return
    if schedule.type == ScheduleType.MANUAL:
        return
    raise ValueError(f"Unsupported schedule type '{schedule.type}'.")


def _validate_lifecycle(lifecycle: LifecycleSpec) -> None:
    if lifecycle.completion_policy == LifecycleCompletionPolicy.COMPLETE_AFTER_N_MATCHES:
        if lifecycle.max_matches is None or lifecycle.max_matches <= 0:
            raise ValueError("complete_after_n_matches lifecycle requires max_matches > 0.")
    if lifecycle.max_runs is not None and lifecycle.max_runs <= 0:
        raise ValueError("max_runs must be greater than zero when provided.")
    if lifecycle.max_matches is not None and lifecycle.max_matches <= 0:
        raise ValueError("max_matches must be greater than zero when provided.")
    if lifecycle.cooldown_seconds < 0:
        raise ValueError("cooldown_seconds must be zero or greater.")
    if lifecycle.expires_at is not None:
        _ensure_aware(lifecycle.expires_at)


def _validate_safety(safety: SafetySpec) -> None:
    if safety.broker_actions_allowed:
        raise ValueError("Direct broker execution is not representable in Wave 0 scheduler specs.")


def _validate_action(action: dict[str, Any]) -> None:
    action_type = str(action.get("type") or action.get("actionType") or "").strip().lower()
    if action_type in UNSAFE_ACTION_TYPES:
        raise ValueError("Direct broker execution is not representable in Wave 0 scheduler specs.")
    if any(key in action for key in ("brokerExecution", "broker_execution", "submitOrder")):
        raise ValueError("Direct broker execution is not representable in Wave 0 scheduler specs.")
    _json_dict(action)


def _coerce_schedule(value: ScheduleSpec | dict[str, Any]) -> ScheduleSpec:
    if isinstance(value, ScheduleSpec):
        schedule = value
    else:
        try:
            schedule = ScheduleSpec.model_validate(value)
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc
    if schedule.frequency is not None:
        schedule = schedule.model_copy(update={"frequency": schedule.frequency.strip().lower()})
    if schedule.timezone is not None:
        schedule = schedule.model_copy(update={"timezone": schedule.timezone.strip()})
    if schedule.days:
        schedule = schedule.model_copy(update={"days": _normalize_days(schedule.days)})
    return schedule


def _coerce_lifecycle(value: LifecycleSpec | dict[str, Any]) -> LifecycleSpec:
    if isinstance(value, LifecycleSpec):
        return value
    try:
        return LifecycleSpec.model_validate(value)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


def _coerce_safety(value: SafetySpec | dict[str, Any] | None) -> SafetySpec:
    if value is None:
        return SafetySpec()
    if isinstance(value, SafetySpec):
        return value
    try:
        return SafetySpec.model_validate(value)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


def _initial_next_run_at(schedule: ScheduleSpec, now: datetime) -> datetime | None:
    resolved_now = _ensure_aware(now)
    if schedule.type == ScheduleType.ONE_SHOT:
        assert schedule.run_at is not None
        return _ensure_aware(schedule.run_at)
    if schedule.type == ScheduleType.RECURRING:
        return _next_recurring_after(schedule, resolved_now)
    if schedule.type == ScheduleType.POLLING:
        return resolved_now
    if schedule.type == ScheduleType.MANUAL:
        return None
    raise ValueError(f"Unsupported schedule type '{schedule.type}'.")


def _next_run_after_completion(
    schedule: ScheduleSpec,
    lifecycle: LifecycleSpec,
    finished_at: datetime,
    *,
    matched: bool,
) -> datetime | None:
    resolved_finished_at = _ensure_aware(finished_at)
    if schedule.type == ScheduleType.POLLING:
        assert schedule.poll_every_seconds is not None
        next_run = resolved_finished_at + timedelta(seconds=schedule.poll_every_seconds)
    elif schedule.type == ScheduleType.RECURRING:
        next_run = _next_recurring_after(schedule, resolved_finished_at)
    else:
        next_run = None
    if matched and next_run is not None and lifecycle.cooldown_seconds > 0:
        cooldown_until = resolved_finished_at + timedelta(seconds=lifecycle.cooldown_seconds)
        if next_run < cooldown_until:
            next_run = cooldown_until
    return next_run


def _next_recurring_after(schedule: ScheduleSpec, now: datetime) -> datetime:
    local_tz = _zone_info(str(schedule.timezone))
    local_now = _ensure_aware(now).astimezone(local_tz)
    target_time = _parse_local_time(str(schedule.time))
    allowed_weekdays = _allowed_weekdays(schedule)
    for offset in range(15):
        candidate_date = local_now.date() + timedelta(days=offset)
        if candidate_date.weekday() not in allowed_weekdays:
            continue
        candidate = datetime.combine(candidate_date, target_time, tzinfo=local_tz)
        if candidate > local_now:
            return candidate.astimezone(UTC)
    raise ValueError("Unable to compute next recurring run.")


def _allowed_weekdays(schedule: ScheduleSpec) -> set[int]:
    frequency = str(schedule.frequency or "").strip().lower()
    if frequency == "daily":
        return set(range(7))
    if frequency == "weekdays":
        return set(range(5))
    if frequency == "weekly":
        return {VALID_WEEKDAYS[day] for day in _normalize_days(schedule.days)}
    raise ValueError("recurring schedule requires frequency daily, weekdays, or weekly.")


def _parse_local_time(raw: str) -> time:
    parts = str(raw or "").strip().split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError("time must use HH:MM format.")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("time must use HH:MM format.")
    return time(hour=hour, minute=minute)


def _normalize_days(days: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw_day in days:
        key = str(raw_day or "").strip().lower()
        if key not in VALID_WEEKDAYS:
            raise ValueError(f"Unsupported weekday '{raw_day}'.")
        day = NORMALIZED_WEEKDAYS[VALID_WEEKDAYS[key]]
        if day not in normalized:
            normalized.append(day)
    return normalized


def _zone_info(raw: str) -> ZoneInfo:
    try:
        return ZoneInfo(str(raw or "").strip())
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Invalid timezone '{raw}'.") from exc


def _process_model(row: ScheduledProcessRow) -> ScheduledProcess:
    last_status = ScheduledRunStatus(row.last_status) if row.last_status else None
    return ScheduledProcess(
        process_id=row.process_id,
        title=row.title,
        description=row.description,
        kind=ScheduledProcessKind(row.kind),
        execution_mode=ScheduledExecutionMode(row.execution_mode),
        status=ScheduledProcessStatus(row.status),
        schedule=_schedule_model(row),
        trigger=_load_json_dict(row.trigger_json),
        inputs=_load_json_dict(row.inputs_json),
        llm_scope=_load_json_dict(row.llm_scope_json),
        action=_load_json_dict(row.action_json),
        notification=_load_json_dict(row.notification_json),
        lifecycle=_lifecycle_model(row),
        safety=_safety_model(row),
        created_at=_ensure_aware(row.created_at),
        updated_at=_ensure_aware(row.updated_at),
        next_run_at=_ensure_aware(row.next_run_at) if row.next_run_at is not None else None,
        last_run_at=_ensure_aware(row.last_run_at) if row.last_run_at is not None else None,
        last_status=last_status,
        failure_count=int(row.failure_count or 0),
    )


def _run_model(row: ScheduledProcessRunRow) -> ScheduledProcessRun:
    return ScheduledProcessRun(
        run_id=row.run_id,
        process_id=row.process_id,
        status=ScheduledRunStatus(row.status),
        started_at=_ensure_aware(row.started_at),
        finished_at=_ensure_aware(row.finished_at) if row.finished_at is not None else None,
        due_at=_ensure_aware(row.due_at) if row.due_at is not None else None,
        matched=bool(row.matched),
        output_summary=row.output_summary,
        error_code=row.error_code,
        error_message=row.error_message,
        metadata=_load_json_dict(row.metadata_json),
    )


def _event_model(row: ScheduledProcessEventRow) -> ScheduledProcessEvent:
    return ScheduledProcessEvent(
        event_id=row.event_id,
        process_id=row.process_id,
        run_id=row.run_id,
        event_type=ScheduledEventType(row.event_type),
        message=row.message,
        details=_load_json_dict(row.details_json),
        created_at=_ensure_aware(row.created_at),
    )


def _schedule_model(row: ScheduledProcessRow) -> ScheduleSpec:
    return ScheduleSpec.model_validate(_load_json_dict(row.schedule_json))


def _lifecycle_model(row: ScheduledProcessRow) -> LifecycleSpec:
    return LifecycleSpec.model_validate(_load_json_dict(row.lifecycle_json))


def _safety_model(row: ScheduledProcessRow) -> SafetySpec:
    return SafetySpec.model_validate(_load_json_dict(row.safety_json))


def _required_process_row(session: Session, process_id: str) -> ScheduledProcessRow:
    row = session.get(ScheduledProcessRow, str(process_id))
    if row is None:
        raise ValueError(f"Scheduled process '{process_id}' was not found.")
    return row


def _required_run_row(session: Session, run_id: str) -> ScheduledProcessRunRow:
    row = session.get(ScheduledProcessRunRow, str(run_id))
    if row is None:
        raise ValueError(f"Scheduled process run '{run_id}' was not found.")
    return row


def _add_event(
    session: Session,
    *,
    process_id: str,
    event_type: ScheduledEventType,
    message: str,
    created_at: datetime,
    run_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> ScheduledProcessEventRow:
    row = ScheduledProcessEventRow(
        event_id=_new_event_id(),
        process_id=process_id,
        run_id=run_id,
        event_type=event_type.value,
        message=message,
        details_json=_json_dict(details or {}),
        created_at=_ensure_aware(created_at),
    )
    session.add(row)
    return row


def _completed_match_count(session: Session, process_id: str) -> int:
    rows = session.scalars(
        select(ScheduledProcessRunRow).where(
            ScheduledProcessRunRow.process_id == str(process_id),
            ScheduledProcessRunRow.status == ScheduledRunStatus.COMPLETED.value,
            ScheduledProcessRunRow.matched == 1,
        )
    ).all()
    return len(rows)


def _json_model(model: Any) -> str:
    return _json_dict(
        model.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
            exclude_defaults=True,
        )
    )


def _json_dict(value: dict[str, Any]) -> str:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _load_json_dict(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise ValueError("Stored scheduler JSON value is not an object.")
    return loaded


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return _ensure_aware(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


def _clean_dict(value: dict[str, Any] | None, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object.")
    _json_dict(value)
    return dict(value)


def _required_text(value: str, field_name: str) -> str:
    resolved = str(value or "").strip()
    if not resolved:
        raise ValueError(f"{field_name} is required.")
    return resolved


def _positive_int(value: int, field_name: str) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a positive integer.") from exc
    if resolved <= 0:
        raise ValueError(f"{field_name} must be greater than zero.")
    return resolved


def _coerce_enum(enum_type: type[Enum], value: Any) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(str(value))
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ValueError(f"Unsupported {enum_type.__name__} value '{value}'. Allowed: {allowed}.") from exc


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _safe_limit(value: int, *, default: int, maximum: int) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        resolved = default
    return max(1, min(maximum, resolved))


def _new_process_id() -> str:
    return f"sched_{uuid4().hex[:24]}"


def _new_run_id() -> str:
    return f"run_{uuid4().hex[:24]}"


def _new_event_id() -> str:
    return f"evt_{uuid4().hex[:24]}"


def _new_lease_token() -> str:
    return f"lease_{uuid4().hex[:24]}"
