"""Timezone context helpers for agent prompts."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def render_timezone_context(
    timezone_name: str,
    *,
    now_utc: datetime | None = None,
) -> str:
    """Return compact timezone context for scheduling-aware prompts."""
    configured_timezone = (timezone_name or "UTC").strip() or "UTC"
    reference_utc = now_utc or datetime.now(timezone.utc)
    if reference_utc.tzinfo is None:
        reference_utc = reference_utc.replace(tzinfo=timezone.utc)
    reference_utc = reference_utc.astimezone(timezone.utc)
    utc_label = _format_utc(reference_utc)
    try:
        zone = ZoneInfo(configured_timezone)
    except ZoneInfoNotFoundError:
        return (
            f"Configured user timezone: {configured_timezone} could not be resolved. "
            f"Current UTC datetime: {utc_label}. "
            "For local-time scheduling, ask the user to confirm their city or timezone "
            "in natural language before creating the job."
        )

    local_now = reference_utc.astimezone(zone)
    local_label = local_now.isoformat(timespec="seconds")
    offset = local_now.utcoffset()
    offset_label = "UTC"
    if offset is not None:
        total_minutes = int(offset.total_seconds() // 60)
        sign = "+" if total_minutes >= 0 else "-"
        total_minutes = abs(total_minutes)
        hours, minutes = divmod(total_minutes, 60)
        offset_label = f"UTC{sign}{hours:02d}:{minutes:02d}"

    return (
        f"Configured user timezone: {configured_timezone}. Current local datetime: "
        f"{local_label} ({local_now.tzname()}). Current UTC datetime: {utc_label}. "
        f"Current UTC offset for that timezone: {offset_label}. Scheduler storage and "
        "workers operate in UTC. When the user gives a schedule time without another "
        "timezone, treat it as local time in the configured user timezone. When the "
        "schedule time comes from an external source or event that has its own "
        "timezone, preserve that source timezone and convert the final run time to UTC."
    )


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00",
        "Z",
    )
