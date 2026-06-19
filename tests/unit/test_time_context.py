from __future__ import annotations

from datetime import datetime, timezone

from t212ai.agent.time_context import render_timezone_context


def test_render_timezone_context_includes_current_local_and_utc_datetime() -> None:
    context = render_timezone_context(
        "Europe/Rome",
        now_utc=datetime(2026, 5, 11, 12, 34, 56, tzinfo=timezone.utc),
    )

    assert "Configured user timezone: Europe/Rome" in context
    assert "Current local datetime: 2026-05-11T14:34:56+02:00 (CEST)" in context
    assert "Current UTC datetime: 2026-05-11T12:34:56Z" in context
    assert "Current UTC offset for that timezone: UTC+02:00" in context
    assert "Do not use timezone abbreviations such as CET" in context
    assert "For relative windows such as next hour" in context


def test_render_timezone_context_includes_utc_datetime_for_invalid_timezone() -> None:
    context = render_timezone_context(
        "Not/AZone",
        now_utc=datetime(2026, 5, 11, 12, 34, 56, tzinfo=timezone.utc),
    )

    assert "Configured user timezone: Not/AZone could not be resolved" in context
    assert "Current UTC datetime: 2026-05-11T12:34:56Z" in context
