"""Error conversion helpers for Trading 212 tools."""

from __future__ import annotations

from typing import Any

from t212ai.brokers.exceptions import BrokerInstrumentResolutionError
from t212ai.genai.models import ToolError, ToolResult

from .formatting import _truncate


def _instrument_resolution_tool_error(exc: BrokerInstrumentResolutionError) -> ToolResult:
    return _tool_error(
        str(exc),
        code="instrument_resolution_failed",
        hint=(
            "Use one of error.details.resolution.candidates[].ticker values "
            "and prepare the order again."
        ),
        details=exc.details(),
    )


def _tool_error(
    message: str,
    *,
    code: str,
    hint: str | None = None,
    details: dict[str, Any] | None = None,
) -> ToolResult:
    return ToolResult(
        status="error",
        output=_format_tool_error_output(
            message,
            code=code,
            hint=hint,
            details=details,
        ),
        error=ToolError(
            message=message,
            code=code,
            hint=hint,
            retryable=False,
            details=details,
        ),
    )


def _format_tool_error_output(
    message: str,
    *,
    code: str,
    hint: str | None = None,
    details: dict[str, Any] | None = None,
) -> str:
    lines = [str(message or "Tool execution failed.").strip()]
    if code:
        lines.append(f"Code: {code}.")
    resolution = details.get("resolution") if isinstance(details, dict) else None
    if isinstance(resolution, dict):
        candidates = resolution.get("candidates")
        if isinstance(candidates, list) and candidates:
            rendered = [
                str(candidate.get("ticker"))
                for candidate in candidates[:5]
                if isinstance(candidate, dict) and candidate.get("ticker")
            ]
            if rendered:
                lines.append("Candidate Trading 212 tickers: " + ", ".join(rendered) + ".")
    if hint:
        lines.append(f"Hint: {hint}")
    return "\n".join(line for line in lines if line)


def _tool_exception(
    exc: Exception,
    *,
    operation: str,
    message: str,
    hint: str,
) -> ToolResult:
    details: dict[str, Any] = {
        "operation": operation,
        "error_type": exc.__class__.__name__,
        "error": str(exc),
    }
    for attr in ("status_code", "body"):
        value = getattr(exc, attr, None)
        if value:
            details[attr] = _truncate(str(value), 600)
    rate_limit = getattr(exc, "rate_limit", None)
    if rate_limit is not None and hasattr(rate_limit, "__dict__"):
        details["rate_limit"] = {
            key: value
            for key, value in rate_limit.__dict__.items()
            if value is not None
        }

    return ToolResult(
        status="error",
        error=ToolError(
            message=f"{message} Reason: {exc}",
            code="broker_snapshot_failed",
            type=exc.__class__.__name__,
            hint=hint,
            retryable=True,
            details=details,
        ),
    )
