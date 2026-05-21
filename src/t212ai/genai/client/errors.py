"""Provider error extraction and content-filter diagnostics."""

from __future__ import annotations

import json
from typing import Any


def _provider_error_code(exc: Exception) -> str | None:
    return _provider_error_details(exc).get("error_code")


def _provider_error_details(exc: Exception) -> dict[str, Any]:
    payload = _provider_error_payload(exc)
    error_payload: dict[str, Any] = {}
    if isinstance(payload, dict):
        nested = payload.get("error")
        error_payload = nested if isinstance(nested, dict) else payload

    values = [
        getattr(exc, "code", None),
        getattr(exc, "status_code", None),
        getattr(exc, "body", None),
        getattr(exc, "message", None),
        payload,
        str(exc),
    ]
    text = " ".join(str(value).lower() for value in values if value is not None)
    raw_code = (
        error_payload.get("code")
        or getattr(exc, "code", None)
        or error_payload.get("status")
        or getattr(exc, "status_code", None)
    )
    error_code = _normalize_provider_error_code(raw_code, text)
    inner_error = error_payload.get("innererror") or error_payload.get("inner_error")
    inner_error = inner_error if isinstance(inner_error, dict) else {}
    filter_summary = _content_filter_summary(error_payload, inner_error)
    if filter_summary and error_code is None:
        error_code = "content_filter"

    return {
        "error_code": error_code,
        "provider_error_code": raw_code if raw_code is not None else None,
        "provider_error_type": error_payload.get("type") or getattr(exc, "type", None),
        "provider_error_param": error_payload.get("param")
        or getattr(exc, "param", None),
        "provider_status": error_payload.get("status")
        or getattr(exc, "status_code", None),
        "provider_policy_code": inner_error.get("code"),
        **filter_summary,
    }


def _provider_error_payload(exc: Exception) -> dict[str, Any] | None:
    body = getattr(exc, "body", None)
    parsed = _parse_provider_payload(body)
    if isinstance(parsed, dict):
        return parsed

    response = getattr(exc, "response", None)
    if response is None:
        return None
    response_json = getattr(response, "json", None)
    if callable(response_json):
        try:
            parsed = response_json()
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    return _parse_provider_payload(getattr(response, "text", None))


def _parse_provider_payload(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _normalize_provider_error_code(value: Any, text: str) -> str | None:
    raw = str(value).strip() if value is not None else ""
    lowered = raw.lower().replace("-", "_")
    if (
        "contentfilter" in text
        or "content_filter" in text
        or "responsibleaipolicyviolation" in text
    ):
        return "content_filter"
    if lowered in {"contentfilter", "content_filter"}:
        return "content_filter"
    return raw or None


def _content_filter_summary(
    error_payload: dict[str, Any],
    inner_error: dict[str, Any],
) -> dict[str, Any]:
    result = (
        inner_error.get("contentfilterresult")
        or inner_error.get("content_filter_result")
        or error_payload.get("contentfilterresult")
        or error_payload.get("content_filter_result")
    )
    if not isinstance(result, dict):
        return {}

    category_status: dict[str, dict[str, Any]] = {}
    categories: list[str] = []
    blocked_categories: list[str] = []
    detected_categories: list[str] = []
    for category, raw_status in sorted(result.items()):
        if not isinstance(raw_status, dict):
            continue
        filtered = bool(raw_status.get("filtered"))
        detected = bool(raw_status.get("detected"))
        severity = str(raw_status.get("severity") or "").strip().lower()
        category_status[str(category)] = {
            key: value
            for key, value in {
                "filtered": filtered,
                "detected": detected if "detected" in raw_status else None,
                "severity": severity or None,
            }.items()
            if value is not None
        }
        if filtered or detected or severity not in {"", "safe"}:
            categories.append(str(category))
        if filtered:
            blocked_categories.append(str(category))
        if detected:
            detected_categories.append(str(category))

    summary = _content_filter_status_summary(
        categories=categories,
        blocked_categories=blocked_categories,
        detected_categories=detected_categories,
    )
    return {
        "content_filter_triggered": bool(categories),
        "content_filter_summary": summary,
        "content_filter_categories": categories,
        "content_filter_blocked_categories": blocked_categories,
        "content_filter_detected_categories": detected_categories,
        "content_filter_category_status": category_status,
    }


def _content_filter_status_summary(
    *,
    categories: list[str],
    blocked_categories: list[str],
    detected_categories: list[str],
) -> str | None:
    if not categories:
        return None
    blocked = set(blocked_categories)
    detected = set(detected_categories)
    parts: list[str] = []
    for category in categories:
        flags = []
        if category in blocked:
            flags.append("filtered")
        if category in detected:
            flags.append("detected")
        parts.append(f"{category}({','.join(flags)})" if flags else category)
    return "; ".join(parts)
