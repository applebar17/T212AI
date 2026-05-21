"""Validation, schedule math, row conversion, and JSON helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from enum import Enum
import json
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
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
from ..orm import (
    ScheduledProcessEventRow,
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
