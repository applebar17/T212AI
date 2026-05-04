"""Broker provider error classification helpers."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


@dataclass(frozen=True, slots=True)
class BrokerProviderErrorClassification:
    message: str
    code: str
    hint: str | None
    retryable: bool
    details: dict[str, Any]


def classify_broker_provider_error(
    exc: Exception,
    *,
    provider: str,
    operation: str,
) -> BrokerProviderErrorClassification | None:
    details = _provider_error_details(exc, provider=provider, operation=operation)
    provider_type = str(details.get("provider_error_type") or "").lower()
    provider_detail = str(details.get("provider_error_detail") or "").lower()
    provider_title = str(details.get("provider_error_title") or "").lower()
    raw_error = str(details.get("error") or "").lower()

    if (
        "instrument-close-only-mode" in provider_type
        or "close only mode" in provider_detail
        or "close-only" in provider_detail
        or "close only mode" in raw_error
        or "close only" in provider_title
    ):
        display_provider = _display_provider(provider)
        return BrokerProviderErrorClassification(
            message=(
                f"{display_provider} rejected the order because the instrument is in "
                "close-only mode. New buy/opening orders are temporarily not allowed "
                "for this stock; only closing an existing position may be possible."
            ),
            code="instrument_temporarily_not_tradable",
            hint=(
                "Do not retry this buy/opening order unchanged. Explain that the asset "
                "is temporarily not tradable for opening orders, and suggest choosing "
                "another tradable instrument or checking again later."
            ),
            retryable=False,
            details=details,
        )

    return None


def provider_execution_error_message(exc: Exception, *, provider: str, operation: str) -> str:
    classification = classify_broker_provider_error(
        exc,
        provider=provider,
        operation=operation,
    )
    if classification is not None:
        return classification.message
    return _generic_execution_error_message(exc)


def _provider_error_details(
    exc: Exception,
    *,
    provider: str,
    operation: str,
) -> dict[str, Any]:
    details: dict[str, Any] = {
        "operation": operation,
        "provider": provider,
        "error_type": exc.__class__.__name__,
        "error": str(exc),
    }
    status_code = getattr(exc, "status_code", None)
    if status_code is not None and str(status_code).strip():
        details["status_code"] = str(status_code)
    body = getattr(exc, "body", None)
    if body is not None and str(body).strip():
        raw_body = str(body)
        details["body"] = _truncate(raw_body, 600)
        parsed = _parse_json_object(raw_body)
        if parsed is not None:
            for source_key, target_key in (
                ("type", "provider_error_type"),
                ("title", "provider_error_title"),
                ("status", "provider_error_status"),
                ("detail", "provider_error_detail"),
                ("traceId", "provider_trace_id"),
            ):
                if parsed.get(source_key) is not None:
                    details[target_key] = parsed[source_key]
    code = getattr(exc, "code", None)
    if code is not None and str(code).strip():
        details["code"] = str(code)
    return details


def _generic_execution_error_message(exc: Exception) -> str:
    parts = [f"{exc.__class__.__name__}: {exc}"]
    status_code = getattr(exc, "status_code", None)
    if status_code is not None and str(status_code).strip():
        parts.append(f"status_code={status_code}")
    body = getattr(exc, "body", None)
    if body is not None and str(body).strip():
        parts.append(f"body={_truncate(str(body), 300)}")
    code = getattr(exc, "code", None)
    if code is not None and str(code).strip():
        parts.append(f"code={code}")
    return " | ".join(parts)


def _parse_json_object(value: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(value)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _display_provider(provider: str) -> str:
    if str(provider).strip().lower() == "trading212":
        return "Trading 212"
    return str(provider or "broker").replace("_", " ").strip().title() or "Broker"


def _truncate(value: str, limit: int) -> str:
    raw = str(value)
    if len(raw) <= limit:
        return raw
    return raw[: limit - 3] + "..."
