"""Shared parsing, formatting, and error helpers for scheduler tools."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from t212ai.genai.models import ToolError, ToolResult

from ..models import ScheduledProcess
from .constants import MARKET_REGIME_PROXY_LABELS


def _optional_float(value: int | float | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("threshold values must be numeric.") from exc


def _clean_symbols(values: list[str] | None) -> list[str]:
    return _dedupe_terms(str(value or "").strip().upper() for value in values or [])


def _clean_terms(values: list[str] | None) -> list[str]:
    return _dedupe_terms(
        str(value or "").strip().lower().replace(" ", "_") for value in values or []
    )


def _clean_order_terms(
    values: list[str] | None,
    *,
    allowed: frozenset[str],
    field_name: str,
) -> list[str]:
    terms = _dedupe_terms(str(value or "").strip().upper() for value in values or [])
    if not terms:
        raise ValueError(f"{field_name} is required for proposal creation.")
    unsupported = [term for term in terms if term not in allowed]
    if unsupported:
        raise ValueError(f"{field_name} contains unsupported values: {', '.join(unsupported)}.")
    return terms


def _dedupe_terms(values) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _optional_decimal(value: int | float | None, *, field_name: str) -> Decimal | None:
    if value is None or not str(value).strip():
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} must be decimal-compatible.") from exc


def _resolve_run_at(run_at: str | None, *, timezone_name: str) -> datetime:
    raw = str(run_at or "").strip()
    if not raw:
        raise ValueError("one_shot schedules require run_at.")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("run_at must be a valid ISO-8601 datetime.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_zone_info(timezone_name))
    return parsed.astimezone(timezone.utc)


def _resolve_optional_datetime(
    value: str | None,
    *,
    timezone_name: str,
    fallback: datetime,
    field_name: str,
) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        resolved = fallback
        if resolved.tzinfo is None:
            resolved = resolved.replace(tzinfo=timezone.utc)
        return resolved.astimezone(timezone.utc)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid ISO-8601 datetime.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_zone_info(timezone_name))
    return parsed.astimezone(timezone.utc)


def _resolve_stream_end_at(
    *,
    end_at: str | None,
    duration_minutes: int | None,
    timezone_name: str,
    start: datetime,
) -> datetime:
    raw_end = str(end_at or "").strip()
    if raw_end:
        return _resolve_optional_datetime(
            raw_end,
            timezone_name=timezone_name,
            fallback=start,
            field_name="end_at",
        )
    if duration_minutes is None:
        raise ValueError("Provide end_at or duration_minutes for a bounded news monitor.")
    minutes = _positive_int(
        duration_minutes,
        fallback=60,
        field_name="duration_minutes",
    )
    return start + timedelta(minutes=minutes)


def _resolve_timezone_name(
    value: str | None,
    default_timezone: str | None,
    *,
    now: datetime | None = None,
) -> str:
    fallback = str(default_timezone or "UTC").strip() or "UTC"
    fallback_zone = _zone_info(fallback)
    raw = str(value or "").strip()
    if not raw:
        return fallback
    if raw == fallback:
        return fallback
    if _matches_timezone_abbreviation(raw, fallback_zone, now=now):
        return fallback
    _zone_info(raw)
    return raw


def _resolve_timezone_name_best_effort(
    value: str | None,
    default_timezone: str | None,
    *,
    now: datetime | None = None,
) -> str:
    fallback = str(default_timezone or "UTC").strip() or "UTC"
    raw = str(value or "").strip()
    if not raw or raw == fallback:
        return fallback
    try:
        return _resolve_timezone_name(raw, fallback, now=now)
    except ValueError:
        return fallback


def _positive_int(value: int | None, *, fallback: int, field_name: str) -> int:
    resolved = fallback if value is None else value
    try:
        parsed = int(resolved)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a positive integer.") from exc
    if parsed <= 0:
        raise ValueError(f"{field_name} must be greater than zero.")
    return parsed


def _resolve_expires_at(
    expires_at: str | None,
    *,
    timezone_name: str,
    runtime: SchedulerManagementRuntime,
) -> datetime:
    tz = _zone_info(timezone_name)
    raw = str(expires_at or "").strip()
    if raw:
        normalized = raw.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError("expires_at must be a valid ISO-8601 datetime.") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        return parsed.astimezone(timezone.utc)

    now = runtime.clock()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local_now = now.astimezone(tz)
    end_of_day = datetime.combine(
        local_now.date(),
        time(hour=23, minute=59, second=59),
        tzinfo=tz,
    )
    return end_of_day.astimezone(timezone.utc)


def _zone_info(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"timezone must be a valid IANA timezone: {timezone_name}.") from exc


def _matches_timezone_abbreviation(
    value: str,
    zone: ZoneInfo,
    *,
    now: datetime | None,
) -> bool:
    tokens = _timezone_abbreviation_tokens(value)
    if not tokens:
        return False
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reference = reference.astimezone(timezone.utc)
    samples = [
        reference,
        datetime(reference.year, 1, 15, 12, tzinfo=timezone.utc),
        datetime(reference.year, 7, 15, 12, tzinfo=timezone.utc),
    ]
    abbreviations = {
        abbreviation.upper()
        for sample in samples
        if (abbreviation := sample.astimezone(zone).tzname())
    }
    return all(token in abbreviations for token in tokens)


def _timezone_abbreviation_tokens(value: str) -> list[str]:
    normalized = str(value or "").strip().upper()
    if not normalized:
        return []
    for separator in ("/", ",", ";", "|", "(", ")", "[", "]", "{", "}"):
        normalized = normalized.replace(separator, " ")
    return [
        token
        for token in normalized.split()
        if token and token not in {"AND", "OR"}
    ]


def _process_payload(process: ScheduledProcess) -> dict[str, Any]:
    return process.model_dump(by_alias=True, exclude_none=True, mode="json")


def _list_output(processes: list[ScheduledProcess]) -> str:
    if not processes:
        return "No scheduled processes matched the provided filters."
    lines = [f"Found {len(processes)} scheduled process(es)."]
    for process in processes:
        lines.append(
            "- "
            + " | ".join(
                [
                    process.process_id,
                    process.kind.value,
                    process.status.value,
                    f"title={process.title}",
                    f"nextRunAt={process.next_run_at}",
                ]
            )
        )
    return "\n".join(lines)


def _missing_service() -> ToolResult:
    return ToolResult(
        status="error",
        output="Scheduled processes are not configured.",
        error=ToolError(
            message="Scheduled processes are not configured.",
            code="scheduled_processes_unavailable",
            hint="Configure DATABASE_URL and ensure the scheduler database schema is available.",
            retryable=False,
        ),
    )


def _tool_exception(exc: Exception, *, operation: str) -> ToolResult:
    return ToolResult(
        status="error",
        output=f"Scheduler {operation} failed. Reason: {exc}.",
        error=ToolError(
            message=str(exc),
            code="scheduler_management_error",
            type=exc.__class__.__name__,
            hint=(
                "Use an exact process id for lifecycle operations, and for creation "
                "provide a supported kind, schedule, lifecycle, and safe action policy."
            ),
            retryable=False,
            details={"operation": operation},
        ),
    )


def _instrument_monitor_exception(exc: Exception) -> ToolResult:
    return ToolResult(
        status="error",
        output=f"Instrument monitor creation failed. Reason: {exc}.",
        error=ToolError(
            message=str(exc),
            code="invalid_instrument_monitor_spec",
            type=exc.__class__.__name__,
            hint=(
                "Provide symbol, a supported trigger_type, value for price or "
                "percent-change triggers, positive poll_every_seconds if supplied, "
                "and keep broker_actions_allowed=false."
            ),
            retryable=False,
        ),
    )


def _company_event_exception(exc: Exception) -> ToolResult:
    return ToolResult(
        status="error",
        output=f"Company-event analyst creation failed. Reason: {exc}.",
        error=ToolError(
            message=str(exc),
            code="invalid_company_event_analyst_spec",
            type=exc.__class__.__name__,
            hint=(
                "Provide symbol and a supported one_shot or recurring schedule. "
                "one_shot requires run_at; recurring requires frequency, time, and "
                "timezone. Keep broker_actions_allowed=false."
            ),
            retryable=False,
        ),
    )


def _market_regime_exception(exc: Exception) -> ToolResult:
    return ToolResult(
        status="error",
        output=f"Market-regime monitor creation failed. Reason: {exc}.",
        error=ToolError(
            message=str(exc),
            code="invalid_market_regime_monitor_spec",
            type=exc.__class__.__name__,
            hint=(
                "Provide a known market_label or explicit proxy_symbol, keep "
                "broker_actions_allowed=false, use a negative percent_change_below "
                "or positive drawdown_from_high_pct, and provide a valid timezone "
                "if overriding the default."
            ),
            retryable=False,
        ),
    )


def _market_signal_capture_exception(exc: Exception) -> ToolResult:
    return ToolResult(
        status="error",
        output=f"Market-signal capture creation failed. Reason: {exc}.",
        error=ToolError(
            message=str(exc),
            code="invalid_market_signal_capture_spec",
            type=exc.__class__.__name__,
            hint=(
                "Provide at least one scan scope field such as query, symbols, "
                "sectors, or tags; use a polling or recurring schedule; keep "
                "polling intervals at least 900 seconds; keep max_signals between "
                "1 and 3; and keep broker_actions_allowed=false."
            ),
            retryable=False,
        ),
    )


def _alpaca_news_monitor_exception(exc: Exception) -> ToolResult:
    return ToolResult(
        status="error",
        output=f"Alpaca news monitor creation failed. Reason: {exc}.",
        error=ToolError(
            message=str(exc),
            code="invalid_alpaca_news_monitor_spec",
            type=exc.__class__.__name__,
            hint=(
                "Provide a bounded stream window using end_at or duration_minutes. "
                "If no ticker symbols are specified, the monitor defaults to ['*']. "
                "Keep broker_actions_allowed=false."
            ),
            retryable=False,
        ),
    )


def _trade_setup_exception(exc: Exception) -> ToolResult:
    return ToolResult(
        status="error",
        output=f"Trade setup monitor creation failed. Reason: {exc}.",
        error=ToolError(
            message=str(exc),
            code="invalid_trade_setup_monitor_spec",
            type=exc.__class__.__name__,
            hint=(
                "Provide symbol, supported trigger_type, required trigger threshold, "
                "positive polling interval if supplied, keep broker_actions_allowed=false, "
                "and when proposal creation is enabled provide allowed sides/order types, "
                "max notional or quantity caps, and an approval chat target."
            ),
            retryable=False,
        ),
    )
