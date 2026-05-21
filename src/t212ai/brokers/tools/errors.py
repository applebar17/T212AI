"""Error conversion helpers for broker tools."""

from __future__ import annotations

from typing import Any

from t212ai.genai.models import ToolError, ToolResult

from ..exceptions import BrokerInstrumentResolutionError
from ..provider_errors import classify_broker_provider_error
from .formatting import _enum_value, _format_value, _truncate
from .runtime import BrokerToolRuntime


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


def _tool_exception(
    exc: Exception,
    *,
    runtime: BrokerToolRuntime,
    operation: str,
    message: str,
) -> ToolResult:
    details: dict[str, Any] = {
        "operation": operation,
        "provider": runtime.broker_provider,
        "error_type": exc.__class__.__name__,
        "error": str(exc),
    }
    for attr in ("status_code", "body", "code"):
        value = getattr(exc, attr, None)
        if value is not None and str(value).strip():
            details[attr] = _truncate(str(value), 600)
    rate_limit = getattr(exc, "rate_limit", None)
    if rate_limit is not None and hasattr(rate_limit, "__dict__"):
        details["rate_limit"] = {
            key: value
            for key, value in rate_limit.__dict__.items()
            if value is not None
        }
    classification = classify_broker_provider_error(
        exc,
        provider=runtime.broker_provider,
        operation=operation,
    )
    if classification is not None:
        details.update(classification.details)
        return ToolResult(
            status="error",
            output=_format_tool_error_output(
                classification.message,
                code=classification.code,
                hint=classification.hint,
                details=details,
            ),
            error=ToolError(
                message=classification.message,
                code=classification.code,
                type=exc.__class__.__name__,
                hint=classification.hint,
                retryable=classification.retryable,
                details=details,
            ),
        )

    return ToolResult(
        status="error",
        output=_format_tool_error_output(
            f"{message} Reason: {exc}",
            code="broker_provider_request_failed",
            hint=_broker_provider_failure_hint(runtime.broker_provider),
            details=details,
        ),
        error=ToolError(
            message=f"{message} Reason: {exc}",
            code="broker_provider_request_failed",
            type=exc.__class__.__name__,
            hint=_broker_provider_failure_hint(runtime.broker_provider),
            retryable=True,
            details=details,
        ),
    )


def _instrument_resolution_tool_error(exc: BrokerInstrumentResolutionError) -> ToolResult:
    code = _instrument_resolution_error_code(exc)
    hint = _instrument_resolution_error_hint(exc)
    return ToolResult(
        status="error",
        output=_format_instrument_resolution_failure_output(
            exc,
            code=code,
            hint=hint,
        ),
        error=ToolError(
            message=str(exc),
            code=code,
            hint=hint,
            retryable=False,
            details=exc.details(),
        ),
    )


def _instrument_resolution_error_code(exc: BrokerInstrumentResolutionError) -> str:
    status = _enum_value(getattr(exc.resolution, "status", ""))
    if status == "ambiguous":
        return "ambiguous_broker_instrument"
    if status == "not_found":
        return "broker_instrument_not_found"
    if status == "resolved":
        return "broker_instrument_mismatch"
    return "instrument_resolution_failed"


def _instrument_resolution_error_hint(exc: BrokerInstrumentResolutionError) -> str:
    status = _enum_value(getattr(exc.resolution, "status", ""))
    if status == "ambiguous":
        return (
            "Do not guess. Ask the user to confirm one candidate, or retry "
            "broker_resolve_instrument with an ISIN, company name, exchange, or currency. "
            "Then prepare the order again with the exact broker-native ticker."
        )
    if status == "not_found":
        return (
            "Retry broker_resolve_instrument with a broader company name, ISIN, or "
            "more precise exchange/currency context. If no candidate is returned, "
            "explain that no order was prepared and ask the user for a tradable broker ticker."
        )
    if status == "resolved":
        return (
            "Use the resolvedTicker returned by the broker resolver and prepare the "
            "order again so the approved order matches the broker-native instrument."
        )
    return (
        "Resolve the instrument with broker_resolve_instrument, inspect "
        "resolution.status and candidates, then prepare the order again only with "
        "a confirmed broker-native ticker."
    )


def _format_instrument_resolution_failure_output(
    exc: BrokerInstrumentResolutionError,
    *,
    code: str,
    hint: str,
) -> str:
    resolution = exc.resolution
    query = str(getattr(resolution, "query", "") or "").strip() or "unknown"
    lines = [
        "No broker order was prepared or submitted.",
        (
            "The configured broker could not confirm a unique tradable "
            f"instrument for {query!r}."
        ),
        f"Resolution status: {_enum_value(getattr(resolution, 'status', 'unknown'))}.",
        f"Code: {code}.",
    ]
    resolved_ticker = getattr(resolution, "resolved_ticker", None)
    if resolved_ticker:
        lines.append(f"Broker resolver suggested: {resolved_ticker}.")
    candidates = list(getattr(resolution, "candidates", []) or [])
    if candidates:
        lines.append("Candidate broker-native tickers:")
        for candidate in candidates[:5]:
            parts = [_format_value(getattr(candidate, "ticker", None))]
            name = getattr(candidate, "name", None) or getattr(candidate, "short_name", None)
            currency = getattr(candidate, "currency", None)
            score = getattr(candidate, "score", None)
            reason = getattr(candidate, "match_reason", None)
            if name:
                parts.append(str(name))
            if currency:
                parts.append(str(currency))
            if score is not None:
                parts.append(f"score={score}")
            if reason:
                parts.append(f"match={reason}")
            lines.append(f"- {' | '.join(parts)}")
    else:
        lines.append("No candidate broker-native tickers were returned.")
    if getattr(resolution, "hint", None):
        lines.append(f"Broker hint: {resolution.hint}")
    lines.append(f"Next step: {hint}")
    return "\n".join(lines)


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
        query = resolution.get("query")
        status = resolution.get("status")
        if query or status:
            lines.append(
                "Instrument resolution: "
                f"query={_format_value(query)}, status={_format_value(status)}."
            )
        candidates = resolution.get("candidates")
        if isinstance(candidates, list) and candidates:
            rendered: list[str] = []
            for candidate in candidates[:5]:
                if not isinstance(candidate, dict):
                    continue
                parts = [_format_value(candidate.get("ticker"))]
                for key in ("name", "shortName", "currency", "score", "matchReason"):
                    value = candidate.get(key)
                    if value is not None:
                        parts.append(f"{key}={value}")
                rendered.append(" | ".join(parts))
            if rendered:
                lines.append("Candidate broker-native tickers: " + "; ".join(rendered) + ".")
    if hint:
        lines.append(f"Hint: {hint}")
    return "\n".join(line for line in lines if line)


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
