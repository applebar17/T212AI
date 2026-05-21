"""Small formatting primitives shared by broker tools."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


def _broker_provider_failure_hint(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized == "trading212":
        return (
            "Check BROKER_PROVIDER=trading212, T212_ENVIRONMENT, the active Trading 212 key pair "
            "(T212_DEMO_API_KEY/T212_DEMO_API_SECRET or T212_LIVE_API_KEY/T212_LIVE_API_SECRET), "
            "legacy fallback vars T212_API_KEY/T212_API_SECRET if you still use them, API scopes "
            "for account/portfolio/orders/history, IP restrictions, and rate limits."
        )
    if normalized == "alpaca":
        return (
            "Check BROKER_PROVIDER=alpaca, ALPACA_ENVIRONMENT, the active Alpaca key pair "
            "(ALPACA_PAPER_API_KEY/ALPACA_PAPER_API_SECRET or ALPACA_LIVE_API_KEY/ALPACA_LIVE_API_SECRET), "
            "legacy fallback vars ALPACA_API_KEY/ALPACA_API_SECRET if you still use them, "
            "paper/live account selection, account status, and rate limits."
        )
    return (
        "Check the selected broker provider credentials, account permissions, "
        "network access, and rate limits."
    )


def _display_broker_name(provider: str) -> str:
    if str(provider).strip().lower() == "trading212":
        return "Trading 212"
    return str(provider or "broker").replace("_", " ").strip().title() or "Broker"


def _format_money(value: Any, currency: str | None) -> str:
    formatted = _format_value(value)
    if formatted == "unknown" or not currency:
        return formatted
    return f"{formatted} {currency}"


def _format_value(value: Any) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        return value.isoformat()
    raw_value = getattr(value, "value", value)
    return str(raw_value)


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3] + "..."
