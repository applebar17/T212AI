"""Order tool error rendering helpers."""

from __future__ import annotations

from typing import Any

from t212ai.genai.models import ToolError, ToolResult


def _local_order_error(
    message: str,
    *,
    code: str,
    hint: str | None = None,
) -> ToolResult:
    return ToolResult(
        status="error",
        error=ToolError(
            message=message,
            code=code,
            hint=hint,
            retryable=False,
        ),
    )


def _render_tool_error_message(error: ToolError) -> str:
    message = str(error.message or "Tool execution failed.").strip()
    if error.code:
        message = f"{message}\nCode: {error.code}"
    if error.hint:
        message = f"{message}\nHint: {error.hint}"
    details = _compact_tool_error_details(error.details)
    if details:
        message = f"{message}\nDetails: {details}"
    return message


def _compact_tool_error_details(details: dict[str, Any] | None) -> str | None:
    if not details:
        return None
    parts: list[str] = []
    for key in ("operation", "provider", "status_code", "error_type", "error", "expected_fingerprint"):
        value = details.get(key)
        if value is None:
            continue
        raw = str(value).strip()
        if raw:
            parts.append(f"{key}={raw}")
    return "; ".join(parts) if parts else None
