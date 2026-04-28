"""Provider-neutral market-data tool facade."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from t212ai.genai.models import ToolError, ToolResult, ToolSpec
from t212ai.genai.tracing import (
    _trace_tool_function_inputs,
    _trace_tool_function_outputs,
    set_trace_metadata,
    traceable,
)

if TYPE_CHECKING:
    from t212ai.capabilities.protocols import MarketDataService

_MARKET_PRICE_COMMON_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "symbols": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of market symbols, for example ['AAPL', 'MSFT'].",
        },
        "period": {
            "type": "string",
            "default": "1mo",
            "description": (
                "Historical lookback period, for example 1d, 5d, 1mo, 3mo, 6mo, "
                "1y, 2y, 5y, 10y, ytd, max. Ignored if start/end are provided."
            ),
        },
        "interval": {
            "type": "string",
            "default": "1d",
            "description": "Data interval, for example 1m, 5m, 1h, 1d, 1wk, 1mo.",
        },
        "start": {
            "type": ["string", "null"],
            "default": None,
            "description": "Start date YYYY-MM-DD or null.",
        },
        "end": {
            "type": ["string", "null"],
            "default": None,
            "description": "End date YYYY-MM-DD or null.",
        },
        "auto_adjust": {
            "type": "boolean",
            "default": False,
            "description": "Whether to prefer adjusted close values where available.",
        },
    },
    "required": [
        "symbols",
        "period",
        "interval",
        "start",
        "end",
        "auto_adjust",
    ],
    "additionalProperties": False,
}


MARKET_SEARCH_SYMBOL_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "market_search_symbol",
        "description": (
            "Search market symbols for a company, ETF, fund, index, or ambiguous "
            "user phrase. Use this before analysis when the symbol is unclear."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search text."},
                "quotes_count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 8,
                    "description": "Maximum symbol candidates.",
                },
                "news_count": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 10,
                    "default": 0,
                    "description": "Maximum provider-native news candidates.",
                },
            },
            "required": ["query", "quotes_count", "news_count"],
            "additionalProperties": False,
        },
    },
}

MARKET_GET_QUOTE_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "market_get_quote",
        "description": (
            "Fetch a best-effort market quote snapshot for one or more symbols. "
            "Useful for convenience context, not broker-authoritative state."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Market symbols.",
                }
            },
            "required": ["symbols"],
            "additionalProperties": False,
        },
    },
}

MARKET_GET_BARS_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "market_get_bars",
        "description": (
            "Retrieve historical OHLCV bars for one or more symbols."
        ),
        "strict": True,
        "parameters": _MARKET_PRICE_COMMON_PARAMETERS,
    },
}

MARKET_GET_VOLUME_MONITOR_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "market_get_volume_monitor",
        "description": (
            "Compare current quote volume against recent average historical volume "
            "for one or more symbols."
        ),
        "strict": True,
        "parameters": _MARKET_PRICE_COMMON_PARAMETERS,
    },
}

MARKET_GET_MARKET_SNAPSHOT_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "market_get_market_snapshot",
        "description": (
            "Fetch a compact market context packet: quote snapshot plus recent "
            "price analytics for one or more symbols."
        ),
        "strict": True,
        "parameters": _MARKET_PRICE_COMMON_PARAMETERS,
    },
}

MARKET_GET_CHART_CONTEXT_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "market_get_chart_context",
        "description": (
            "Retrieve chart-ready market context: recent price analytics plus "
            "series and chart placement references."
        ),
        "strict": True,
        "parameters": _MARKET_PRICE_COMMON_PARAMETERS,
    },
}

GENERIC_MARKET_DATA_TOOLS: list[ToolSpec] = [
    MARKET_SEARCH_SYMBOL_TOOL,
    MARKET_GET_QUOTE_TOOL,
    MARKET_GET_BARS_TOOL,
    MARKET_GET_VOLUME_MONITOR_TOOL,
    MARKET_GET_MARKET_SNAPSHOT_TOOL,
    MARKET_GET_CHART_CONTEXT_TOOL,
]


def build_market_data_tool_mapping(
    service: "MarketDataService | None",
) -> dict[str, Any]:
    return {
        "market_search_symbol": partial(market_search_symbol, service=service),
        "market_get_quote": partial(market_get_quote, service=service),
        "market_get_bars": partial(market_get_bars, service=service),
        "market_get_volume_monitor": partial(
            market_get_volume_monitor,
            service=service,
        ),
        "market_get_market_snapshot": partial(
            market_get_market_snapshot,
            service=service,
        ),
        "market_get_chart_context": partial(
            market_get_chart_context,
            service=service,
        ),
    }


@traceable(
    name="market_search_symbol",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def market_search_symbol(
    *,
    query: str,
    quotes_count: int = 8,
    news_count: int = 0,
    service: "MarketDataService | None" = None,
) -> ToolResult:
    provider = _provider_name(service=service)
    set_trace_metadata(provider=provider, tool_name="market_search_symbol")
    if service is None:
        return _missing_service_result("market_search_symbol")
    try:
        result = service.search_symbols(
            query,
            quotes_count=quotes_count,
            news_count=news_count,
        )
    except Exception as exc:
        return _exception_result(exc, operation="market_search_symbol")
    resolved_provider = _result_provider(result.meta, service=service)
    candidates = list(result.candidates)
    output = _format_symbol_search_output(
        provider=resolved_provider,
        query=query,
        candidates=candidates,
    )
    return ToolResult(
        status="ok",
        output=output,
        data={
            "query": result.query,
            "provider": resolved_provider,
            "candidates": candidates,
        },
    )


@traceable(
    name="market_get_quote",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def market_get_quote(
    *,
    symbols: list[str] | tuple[str, ...],
    service: "MarketDataService | None" = None,
) -> ToolResult:
    provider = _provider_name(service=service)
    set_trace_metadata(provider=provider, tool_name="market_get_quote")
    normalized = _normalize_symbols(symbols)
    if not normalized:
        return _input_error("At least one symbol is required.", "missing_symbols")
    if service is None:
        return _missing_service_result("market_get_quote")
    try:
        result = service.get_quote_snapshot(normalized)
    except Exception as exc:
        return _exception_result(exc, operation="market_get_quote")
    resolved_provider = _result_provider(result.meta, service=service)
    output = _format_quote_output(
        provider=resolved_provider,
        quotes=result.quotes,
        errors=result.errors,
    )
    return ToolResult(
        status="ok",
        output=output,
        data={
            "provider": resolved_provider,
            "quotes": dict(result.quotes),
            "errors": dict(result.errors),
        },
    )


@traceable(
    name="market_get_bars",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def market_get_bars(
    *,
    symbols: list[str] | tuple[str, ...],
    period: str = "1mo",
    interval: str = "1d",
    start: str | None = None,
    end: str | None = None,
    auto_adjust: bool = False,
    service: "MarketDataService | None" = None,
) -> ToolResult:
    provider = _provider_name(service=service)
    set_trace_metadata(provider=provider, tool_name="market_get_bars")
    normalized = _normalize_symbols(symbols)
    if not normalized:
        return _input_error("At least one symbol is required.", "missing_symbols")
    if service is None:
        return _missing_service_result("market_get_bars")
    try:
        result = service.get_price_history(
            normalized,
            period=period,
            interval=interval,
            start=start,
            end=end,
            auto_adjust=auto_adjust,
        )
    except Exception as exc:
        return _exception_result(exc, operation="market_get_bars")
    total_points = sum(len(points) for points in result.series.values())
    resolved_provider = _result_provider(result.meta, service=service)
    output = (
        f"Market bars via {resolved_provider} returned {total_points} point(s) for "
        f"{len(result.series)} symbol(s)."
    )
    if result.errors:
        output += f" Errors were returned for: {', '.join(result.errors.keys())}."
    return ToolResult(
        status="ok",
        output=output,
        data={
            "provider": resolved_provider,
            "series": dict(result.series),
            "errors": dict(result.errors),
            "meta": {
                "provider_meta": dict(result.meta),
                "total_points": total_points,
            },
        },
    )


@traceable(
    name="market_get_volume_monitor",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def market_get_volume_monitor(
    *,
    symbols: list[str] | tuple[str, ...],
    period: str = "1mo",
    interval: str = "1d",
    start: str | None = None,
    end: str | None = None,
    auto_adjust: bool = False,
    service: "MarketDataService | None" = None,
) -> ToolResult:
    provider = _provider_name(service=service)
    set_trace_metadata(provider=provider, tool_name="market_get_volume_monitor")
    normalized = _normalize_symbols(symbols)
    if not normalized:
        return _input_error("At least one symbol is required.", "missing_symbols")
    if service is None:
        return _missing_service_result("market_get_volume_monitor")
    try:
        result = service.get_volume_monitor(
            normalized,
            period=period,
            interval=interval,
            start=start,
            end=end,
            auto_adjust=auto_adjust,
        )
    except Exception as exc:
        return _exception_result(exc, operation="market_get_volume_monitor")
    if result.status != "ok":
        return result
    payload = _coerce_mapping(result.data)
    monitor = _coerce_mapping(payload.get("monitor"))
    quotes = _coerce_mapping(payload.get("quotes"))
    errors = _combine_errors(
        quote_errors=_coerce_mapping(payload.get("quote_errors")),
        price_errors=_coerce_mapping(payload.get("price_errors")),
    )
    resolved_provider = _tool_payload_provider(payload, result=result, service=service)
    return ToolResult(
        status="ok",
        output=_format_volume_monitor_output(provider=resolved_provider, monitor=monitor),
        data={
            "provider": resolved_provider,
            "monitor": monitor,
            "quotes": quotes,
            "errors": errors,
            "meta": _coerce_mapping(payload.get("meta")),
        },
    )


@traceable(
    name="market_get_market_snapshot",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def market_get_market_snapshot(
    *,
    symbols: list[str] | tuple[str, ...],
    period: str = "1mo",
    interval: str = "1d",
    start: str | None = None,
    end: str | None = None,
    auto_adjust: bool = False,
    service: "MarketDataService | None" = None,
) -> ToolResult:
    provider = _provider_name(service=service)
    set_trace_metadata(provider=provider, tool_name="market_get_market_snapshot")
    normalized = _normalize_symbols(symbols)
    if not normalized:
        return _input_error("At least one symbol is required.", "missing_symbols")
    if service is None:
        return _missing_service_result("market_get_market_snapshot")
    try:
        result = service.get_market_snapshot(
            normalized,
            period=period,
            interval=interval,
            start=start,
            end=end,
            auto_adjust=auto_adjust,
        )
    except Exception as exc:
        return _exception_result(exc, operation="market_get_market_snapshot")
    if result.status != "ok":
        return result
    payload = _coerce_mapping(result.data)
    quotes = _coerce_mapping(payload.get("quotes"))
    price_summary = _coerce_mapping(payload.get("price_summary"))
    errors = _combine_errors(
        quote_errors=_coerce_mapping(payload.get("quote_errors")),
        price_errors=_coerce_mapping(payload.get("price_errors")),
    )
    resolved_provider = _tool_payload_provider(payload, result=result, service=service)
    return ToolResult(
        status="ok",
        output=_format_market_snapshot_output(
            provider=resolved_provider,
            quotes=quotes,
            price_summary=price_summary,
        ),
        data={
            "provider": resolved_provider,
            "quotes": quotes,
            "price_summary": price_summary,
            "errors": errors,
            "meta": _coerce_mapping(payload.get("meta")),
        },
    )


@traceable(
    name="market_get_chart_context",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def market_get_chart_context(
    *,
    symbols: list[str] | tuple[str, ...],
    period: str = "1mo",
    interval: str = "1d",
    start: str | None = None,
    end: str | None = None,
    auto_adjust: bool = False,
    service: "MarketDataService | None" = None,
) -> ToolResult:
    provider = _provider_name(service=service)
    set_trace_metadata(provider=provider, tool_name="market_get_chart_context")
    normalized = _normalize_symbols(symbols)
    if not normalized:
        return _input_error("At least one symbol is required.", "missing_symbols")
    if service is None:
        return _missing_service_result("market_get_chart_context")
    try:
        result = service.get_chart_context(
            normalized,
            period=period,
            interval=interval,
            start=start,
            end=end,
            auto_adjust=auto_adjust,
        )
    except Exception as exc:
        return _exception_result(exc, operation="market_get_chart_context")
    if result.status != "ok":
        return result
    payload = _coerce_mapping(result.data)
    summary = _coerce_mapping(payload.get("summary"))
    series = _coerce_mapping(payload.get("series"))
    chart_refs = payload.get("chart_refs")
    placement_guidance = str(payload.get("placement_guidance") or "").strip()
    errors = _coerce_mapping(payload.get("errors"))
    meta = _coerce_mapping(payload.get("meta"))
    total_points = payload.get("total_points")
    meta_payload = dict(meta)
    if total_points is not None:
        meta_payload["total_points"] = total_points
    resolved_provider = _tool_payload_provider(payload, result=result, service=service)
    output = (
        f"Chart-ready market context via {resolved_provider} for "
        f"{len(summary)} symbol(s). Use chart_refs and placement_guidance for rendering."
    )
    if errors:
        output += f" Errors were returned for: {', '.join(errors.keys())}."
    return ToolResult(
        status="ok",
        output=output,
        data={
            "provider": resolved_provider,
            "summary": summary,
            "series": series,
            "chart_refs": chart_refs,
            "placement_guidance": placement_guidance,
            "errors": errors,
            "meta": meta_payload,
        },
    )


def _missing_service_result(tool_name: str) -> ToolResult:
    return ToolResult(
        status="error",
        output=f"{tool_name} is unavailable because no market-data provider is ready.",
        error=ToolError(
            message="No market-data provider is currently configured and ready.",
            code="market_data_not_configured",
            hint="Enable a market-data provider and retry.",
            retryable=False,
        ),
    )


def _exception_result(exc: Exception, *, operation: str) -> ToolResult:
    return ToolResult(
        status="error",
        output=f"Market-data request failed during {operation}.",
        error=ToolError(
            message=str(exc),
            code="market_data_error",
            type=exc.__class__.__name__,
            hint="Retry with valid symbols or verify provider availability.",
            retryable=False,
        ),
    )


def _input_error(message: str, code: str) -> ToolResult:
    return ToolResult(
        status="error",
        output=message,
        error=ToolError(message=message, code=code, retryable=False),
    )


def _normalize_symbols(symbols: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for raw in symbols:
        symbol = str(raw).strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(symbol)
    return normalized


def _coerce_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _provider_name(*, service: "MarketDataService | None") -> str:
    return str(getattr(service, "provider_name", "market_data")).strip() or "market_data"


def _result_provider(
    meta: dict[str, Any] | None,
    *,
    service: "MarketDataService | None",
) -> str:
    if isinstance(meta, dict) and str(meta.get("provider") or "").strip():
        return str(meta["provider"]).strip()
    return _provider_name(service=service)


def _tool_payload_provider(
    payload: dict[str, Any],
    *,
    result: ToolResult,
    service: "MarketDataService | None",
) -> str:
    meta = payload.get("meta")
    if isinstance(meta, dict):
        quote_meta = meta.get("quote")
        if isinstance(quote_meta, dict) and str(quote_meta.get("provider") or "").strip():
            return str(quote_meta["provider"]).strip()
        price_meta = meta.get("price")
        if isinstance(price_meta, dict) and str(price_meta.get("provider") or "").strip():
            return str(price_meta["provider"]).strip()
    if isinstance(result.meta, dict) and str(result.meta.get("provider") or "").strip():
        return str(result.meta["provider"]).strip()
    return _provider_name(service=service)


def _combine_errors(**sources: dict[str, Any]) -> dict[str, dict[str, Any]]:
    combined: dict[str, dict[str, Any]] = {}
    for source_name, errors in sources.items():
        for symbol, payload in errors.items():
            combined.setdefault(str(symbol), {})[source_name] = payload
    return combined


def _format_symbol_search_output(
    *,
    provider: str,
    query: str,
    candidates: list[dict[str, Any]],
) -> str:
    if not candidates:
        return (
            f"Market symbol search via {provider} found no candidates for '{query}'. "
            "Ask for a clearer company name, exchange, or symbol."
        )
    formatted: list[str] = []
    for item in candidates[:8]:
        symbol = item.get("symbol")
        name = item.get("name")
        exchange = item.get("exchange")
        if name and exchange:
            formatted.append(f"{symbol} ({name}, {exchange})")
        elif name:
            formatted.append(f"{symbol} ({name})")
        else:
            formatted.append(str(symbol))
    return (
        f"Market symbol search via {provider} found {len(candidates)} candidate(s): "
        f"{'; '.join(formatted)}."
    )


def _format_quote_output(
    *,
    provider: str,
    quotes: dict[str, Any],
    errors: dict[str, Any],
) -> str:
    if not quotes:
        return f"Market quote snapshot via {provider} returned no quote data."
    lines = [f"Market quote snapshot via {provider}."]
    for symbol, quote in list(quotes.items())[:8]:
        lines.append(
            "- "
            f"{symbol}: price={_fmt(quote.get('price'))} "
            f"{quote.get('currency') or ''}, "
            f"change_pct={_fmt(quote.get('change_pct'))}%, "
            f"volume={_fmt(quote.get('volume'))}."
        )
    if errors:
        lines.append(f"Errors for: {', '.join(errors.keys())}.")
    return "\n".join(lines)


def _format_market_snapshot_output(
    *,
    provider: str,
    quotes: dict[str, Any],
    price_summary: dict[str, Any],
) -> str:
    symbols = list({*quotes.keys(), *price_summary.keys()})
    if not symbols:
        return f"Market snapshot via {provider} returned no market context."
    return (
        f"Market snapshot via {provider} returned quote and price-summary "
        f"context for {len(symbols)} symbol(s)."
    )


def _format_volume_monitor_output(*, provider: str, monitor: dict[str, Any]) -> str:
    if not monitor:
        return f"Volume monitor via {provider} returned no relative-volume signals."
    fragments: list[str] = []
    for symbol, item in list(monitor.items())[:6]:
        fragments.append(
            f"{symbol}: signal={item.get('signal')}, "
            f"relative_volume={_fmt(item.get('relative_volume'))}x"
        )
    return f"Volume monitor via {provider}: " + "; ".join(fragments) + "."


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)
