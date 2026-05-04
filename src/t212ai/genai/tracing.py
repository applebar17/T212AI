"""Thin LangSmith tracing utilities."""

from __future__ import annotations

import re
from typing import Any

from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree, tracing_context

TRACE_COLLECTION_LIMIT = 20

_TRACE_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_TRACE_PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d(). \-]{6,}\d)")
_TRACE_HANDLE_RE = re.compile(r"(?<!\S)@[A-Za-z0-9_]{2,32}")


def set_trace_metadata(**metadata: Any) -> None:
    """Attach small metadata values to the current LangSmith run."""

    clean = {
        key: _sanitize_trace_value(value)
        for key, value in metadata.items()
        if value is not None
    }
    if not clean:
        return
    try:
        run_tree = get_current_run_tree()
    except Exception:
        return
    if not run_tree:
        return
    try:
        existing = getattr(run_tree, "metadata", None)
        if isinstance(existing, dict):
            existing.update(clean)
        else:
            run_tree.metadata = clean
    except Exception:
        try:
            run_tree.add_metadata(clean)
        except Exception:
            return


def set_trace_name(name: str | None) -> None:
    """Rename the current LangSmith run when a dynamic name is clearer."""

    if not name:
        return
    try:
        run_tree = get_current_run_tree()
    except Exception:
        return
    if not run_tree:
        return
    try:
        run_tree.name = name
    except Exception:
        return


def get_trace_parent_headers() -> dict[str, str] | None:
    """Return LangSmith parent headers for downstream requests, when available."""

    try:
        run_tree = get_current_run_tree()
    except Exception:
        return None
    if not run_tree:
        return None
    try:
        headers = run_tree.to_headers()
    except Exception:
        return None
    return dict(headers) if headers else None


def _sanitize_trace_value(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_trace_text(value)
    if isinstance(value, list):
        return [_sanitize_trace_value(item) for item in value[:TRACE_COLLECTION_LIMIT]]
    if isinstance(value, tuple):
        return tuple(_sanitize_trace_value(item) for item in value[:TRACE_COLLECTION_LIMIT])
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= TRACE_COLLECTION_LIMIT:
                sanitized["truncated_items"] = len(value) - TRACE_COLLECTION_LIMIT
                break
            sanitized[str(key)] = _sanitize_trace_value(item)
        return sanitized
    return value


def _sanitize_trace_text(value: str) -> str:
    redacted = _TRACE_EMAIL_RE.sub("[redacted-email]", value)
    redacted = _TRACE_PHONE_RE.sub("[redacted-phone]", redacted)
    return _TRACE_HANDLE_RE.sub("@[redacted-user]", redacted)
