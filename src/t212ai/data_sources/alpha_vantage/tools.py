"""Alpha Vantage Intelligence tool definitions."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import partial
from typing import Any, Callable

from t212ai.genai.models import ToolError, ToolResult, ToolSpec
from t212ai.genai.tracing import (
    _trace_tool_function_inputs,
    _trace_tool_function_outputs,
    set_trace_metadata,
    traceable,
)
from t212ai.genai.tools.tools import ToolBox, build_tool_index

from .client import AlphaVantageApiError, AlphaVantageClient
from .models import AlphaVantageResponse


@dataclass(slots=True)
class AlphaVantageToolRuntime:
    client: AlphaVantageClient


_COMMON_TICKER_ARRAY = {
    "type": ["array", "null"],
    "items": {"type": "string"},
}


ALPHA_VANTAGE_NEWS_SENTIMENT_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "alpha_vantage_news_sentiment",
        "description": (
            "Fetch Alpha Vantage market news and sentiment for tickers/topics. "
            "Use for contextual research packets, not broker state."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "tickers": {
                    **_COMMON_TICKER_ARRAY,
                    "description": "Ticker symbols, for example ['AAPL', 'MSFT'], or null.",
                },
                "topics": {
                    **_COMMON_TICKER_ARRAY,
                    "description": "Alpha Vantage news topics, or null.",
                },
                "time_from": {
                    "type": ["string", "null"],
                    "description": "Start time YYYYMMDDTHHMM or null.",
                },
                "time_to": {
                    "type": ["string", "null"],
                    "description": "End time YYYYMMDDTHHMM or null.",
                },
                "sort": {
                    "type": "string",
                    "enum": ["LATEST", "EARLIEST", "RELEVANCE"],
                    "description": "Sort order.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1000,
                    "description": "Maximum feed items to request.",
                },
            },
            "required": ["tickers", "topics", "time_from", "time_to", "sort", "limit"],
            "additionalProperties": False,
        },
    },
}

ALPHA_VANTAGE_EARNINGS_CALL_TRANSCRIPT_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "alpha_vantage_earnings_call_transcript",
        "description": "Fetch an Alpha Vantage earnings call transcript by symbol and quarter.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol."},
                "quarter": {
                    "type": "string",
                    "description": "Fiscal quarter, for example 2024Q1.",
                },
            },
            "required": ["symbol", "quarter"],
            "additionalProperties": False,
        },
    },
}

ALPHA_VANTAGE_TOP_GAINERS_LOSERS_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "alpha_vantage_top_gainers_losers",
        "description": "Fetch Alpha Vantage top gainers, losers, and most-active stocks.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "entitlement": {
                    "type": ["string", "null"],
                    "description": "Optional entitlement such as realtime or delayed.",
                },
            },
            "required": ["entitlement"],
            "additionalProperties": False,
        },
    },
}

ALPHA_VANTAGE_MOST_ACTIVELY_TRADED_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "alpha_vantage_most_actively_traded",
        "description": (
            "Fetch Alpha Vantage most actively traded stocks, with a focus on turnover "
            "and volume monitoring context."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "entitlement": {
                    "type": ["string", "null"],
                    "description": "Optional entitlement such as realtime or delayed.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum most-active entries to return.",
                },
            },
            "required": ["entitlement", "limit"],
            "additionalProperties": False,
        },
    },
}

ALPHA_VANTAGE_INSIDER_TRANSACTIONS_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "alpha_vantage_insider_transactions",
        "description": "Fetch latest Alpha Vantage insider transactions for one ticker.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
            "additionalProperties": False,
        },
    },
}

ALPHA_VANTAGE_INSTITUTIONAL_HOLDINGS_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "alpha_vantage_institutional_holdings",
        "description": "Fetch Alpha Vantage institutional holdings for one ticker.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
            "additionalProperties": False,
        },
    },
}

_ANALYTICS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "symbols": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Symbols to analyze.",
        },
        "range": {"type": "string", "description": "Alpha Vantage RANGE parameter."},
        "interval": {
            "type": "string",
            "description": "Interval such as DAILY, WEEKLY, or MONTHLY.",
        },
        "ohlc": {
            "type": "string",
            "description": "Price field, for example close.",
        },
        "calculations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Analytics calculations, e.g. MEAN or STDDEV(annualized=True).",
        },
    },
    "required": ["symbols", "range", "interval", "ohlc", "calculations"],
    "additionalProperties": False,
}

ALPHA_VANTAGE_ANALYTICS_FIXED_WINDOW_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "alpha_vantage_analytics_fixed_window",
        "description": "Fetch Alpha Vantage fixed-window analytics for multiple symbols.",
        "strict": True,
        "parameters": _ANALYTICS_SCHEMA,
    },
}

ALPHA_VANTAGE_ANALYTICS_SLIDING_WINDOW_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "alpha_vantage_analytics_sliding_window",
        "description": "Fetch Alpha Vantage sliding-window analytics for multiple symbols.",
        "strict": True,
        "parameters": {
            **_ANALYTICS_SCHEMA,
            "properties": {
                **_ANALYTICS_SCHEMA["properties"],
                "window_size": {
                    "type": "integer",
                    "minimum": 2,
                    "description": "Sliding window size.",
                },
            },
            "required": [*_ANALYTICS_SCHEMA["required"], "window_size"],
        },
    },
}


def build_alpha_vantage_intelligence_tool_mapping(
    runtime: AlphaVantageToolRuntime | None = None,
) -> dict[str, Callable[..., ToolResult]]:
    resolved_runtime = runtime or AlphaVantageToolRuntime(
        client=AlphaVantageClient.from_settings()
    )
    return {
        "alpha_vantage_news_sentiment": partial(
            alpha_vantage_news_sentiment,
            runtime=resolved_runtime,
        ),
        "alpha_vantage_earnings_call_transcript": partial(
            alpha_vantage_earnings_call_transcript,
            runtime=resolved_runtime,
        ),
        "alpha_vantage_top_gainers_losers": partial(
            alpha_vantage_top_gainers_losers,
            runtime=resolved_runtime,
        ),
        "alpha_vantage_most_actively_traded": partial(
            alpha_vantage_most_actively_traded,
            runtime=resolved_runtime,
        ),
        "alpha_vantage_insider_transactions": partial(
            alpha_vantage_insider_transactions,
            runtime=resolved_runtime,
        ),
        "alpha_vantage_institutional_holdings": partial(
            alpha_vantage_institutional_holdings,
            runtime=resolved_runtime,
        ),
        "alpha_vantage_analytics_fixed_window": partial(
            alpha_vantage_analytics_fixed_window,
            runtime=resolved_runtime,
        ),
        "alpha_vantage_analytics_sliding_window": partial(
            alpha_vantage_analytics_sliding_window,
            runtime=resolved_runtime,
        ),
    }


@traceable(
    name="alpha_vantage_news_sentiment",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def alpha_vantage_news_sentiment(
    *,
    tickers: list[str] | None,
    topics: list[str] | None,
    time_from: str | None,
    time_to: str | None,
    sort: str,
    limit: int,
    runtime: AlphaVantageToolRuntime,
) -> ToolResult:
    set_trace_metadata(
        provider="alpha_vantage",
        tool_name="alpha_vantage_news_sentiment",
        intelligence_category="news",
    )
    return _run_intelligence_call(
        "news_sentiment",
        runtime.client.news_sentiment,
        tickers=tickers,
        topics=topics,
        time_from=time_from,
        time_to=time_to,
        sort=sort,
        limit=limit,
    )


@traceable(
    name="alpha_vantage_earnings_call_transcript",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def alpha_vantage_earnings_call_transcript(
    *,
    symbol: str,
    quarter: str,
    runtime: AlphaVantageToolRuntime,
) -> ToolResult:
    set_trace_metadata(
        provider="alpha_vantage",
        tool_name="alpha_vantage_earnings_call_transcript",
        intelligence_category="transcript",
    )
    return _run_intelligence_call(
        "earnings_call_transcript",
        runtime.client.earnings_call_transcript,
        symbol=symbol,
        quarter=quarter,
    )


@traceable(
    name="alpha_vantage_top_gainers_losers",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def alpha_vantage_top_gainers_losers(
    *,
    entitlement: str | None,
    runtime: AlphaVantageToolRuntime,
) -> ToolResult:
    set_trace_metadata(
        provider="alpha_vantage",
        tool_name="alpha_vantage_top_gainers_losers",
        intelligence_category="movers",
    )
    return _run_intelligence_call(
        "top_gainers_losers",
        runtime.client.top_gainers_losers,
        entitlement=entitlement,
    )


@traceable(
    name="alpha_vantage_most_actively_traded",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def alpha_vantage_most_actively_traded(
    *,
    entitlement: str | None,
    limit: int,
    runtime: AlphaVantageToolRuntime,
) -> ToolResult:
    set_trace_metadata(
        provider="alpha_vantage",
        tool_name="alpha_vantage_most_actively_traded",
        intelligence_category="volume",
    )
    try:
        response = runtime.client.top_gainers_losers(entitlement=entitlement)
    except AlphaVantageApiError as exc:
        context = exc.context
        return ToolResult(
            status="error",
            output=(
                f"Alpha Vantage most_actively_traded failed. Reason: {context.message}. "
                "Use another data source or narrow the request if the error suggests "
                "rate limits, entitlement, or temporary provider issues."
            ),
            error=ToolError(
                message=context.message or "Alpha Vantage request failed.",
                code="alpha_vantage_api_error",
                type=exc.__class__.__name__,
                hint=_error_hint(context.retryable),
                retryable=context.retryable,
                details={
                    "function": context.function,
                    "status_code": context.status_code,
                    **context.details,
                },
            ),
        )
    except Exception as exc:
        return ToolResult(
            status="error",
            output=(
                "Alpha Vantage most_actively_traded failed before receiving usable data. "
                "Check the API configuration and retry."
            ),
            error=ToolError(
                message=str(exc),
                code="alpha_vantage_tool_error",
                type=exc.__class__.__name__,
                hint="Validate provider configuration and retry.",
                retryable=False,
            ),
        )

    data = response.data if isinstance(response.data, dict) else {}
    most_active = data.get("most_actively_traded")
    if not isinstance(most_active, list):
        most_active = []
    resolved_limit = max(1, min(int(limit or 20), 100))
    limited = most_active[:resolved_limit]
    return ToolResult(
        status="ok",
        output=_format_most_actively_traded_output(limited, response=response),
        data={
            "function": response.function,
            "most_actively_traded": limited,
            "total_count": len(most_active),
            "request_params": response.request_params,
            "endpoint": response.endpoint,
            "datatype": response.datatype,
        },
    )


@traceable(
    name="alpha_vantage_insider_transactions",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def alpha_vantage_insider_transactions(
    *,
    symbol: str,
    runtime: AlphaVantageToolRuntime,
) -> ToolResult:
    set_trace_metadata(
        provider="alpha_vantage",
        tool_name="alpha_vantage_insider_transactions",
        intelligence_category="ownership",
    )
    return _run_intelligence_call(
        "insider_transactions",
        runtime.client.insider_transactions,
        symbol=symbol,
    )


@traceable(
    name="alpha_vantage_institutional_holdings",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def alpha_vantage_institutional_holdings(
    *,
    symbol: str,
    runtime: AlphaVantageToolRuntime,
) -> ToolResult:
    set_trace_metadata(
        provider="alpha_vantage",
        tool_name="alpha_vantage_institutional_holdings",
        intelligence_category="ownership",
    )
    return _run_intelligence_call(
        "institutional_holdings",
        runtime.client.institutional_holdings,
        symbol=symbol,
    )


@traceable(
    name="alpha_vantage_analytics_fixed_window",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def alpha_vantage_analytics_fixed_window(
    *,
    symbols: list[str],
    range: str,  # noqa: A002 - API parameter name exposed to LLM schema
    interval: str,
    ohlc: str,
    calculations: list[str],
    runtime: AlphaVantageToolRuntime,
) -> ToolResult:
    set_trace_metadata(
        provider="alpha_vantage",
        tool_name="alpha_vantage_analytics_fixed_window",
        intelligence_category="analytics",
    )
    return _run_intelligence_call(
        "analytics_fixed_window",
        runtime.client.analytics_fixed_window,
        symbols=symbols,
        range_=range,
        interval=interval,
        ohlc=ohlc,
        calculations=calculations,
    )


@traceable(
    name="alpha_vantage_analytics_sliding_window",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def alpha_vantage_analytics_sliding_window(
    *,
    symbols: list[str],
    range: str,  # noqa: A002 - API parameter name exposed to LLM schema
    interval: str,
    ohlc: str,
    calculations: list[str],
    window_size: int,
    runtime: AlphaVantageToolRuntime,
) -> ToolResult:
    set_trace_metadata(
        provider="alpha_vantage",
        tool_name="alpha_vantage_analytics_sliding_window",
        intelligence_category="analytics",
    )
    return _run_intelligence_call(
        "analytics_sliding_window",
        runtime.client.analytics_sliding_window,
        symbols=symbols,
        range_=range,
        interval=interval,
        ohlc=ohlc,
        calculations=calculations,
        window_size=window_size,
    )


def _run_intelligence_call(
    label: str,
    fn: Callable[..., AlphaVantageResponse],
    **kwargs: Any,
) -> ToolResult:
    try:
        response = fn(**kwargs)
    except AlphaVantageApiError as exc:
        context = exc.context
        return ToolResult(
            status="error",
            output=(
                f"Alpha Vantage {label} failed. Reason: {context.message}. "
                "Use another data source or reduce the request if the error suggests "
                "rate limits, entitlement, or invalid parameters."
            ),
            error=ToolError(
                message=context.message or "Alpha Vantage request failed.",
                code="alpha_vantage_api_error",
                type=exc.__class__.__name__,
                hint=_error_hint(context.retryable),
                retryable=context.retryable,
                details={
                    "function": context.function,
                    "status_code": context.status_code,
                    **context.details,
                },
            ),
        )
    except Exception as exc:
        return ToolResult(
            status="error",
            output=(
                f"Alpha Vantage {label} failed before receiving usable data. "
                "Check the tool parameters and configured API key."
            ),
            error=ToolError(
                message=str(exc),
                code="alpha_vantage_tool_error",
                type=exc.__class__.__name__,
                hint="Validate required parameters and retry with a narrower request.",
                retryable=False,
            ),
        )

    summary = _summarize_response(label, response)
    return ToolResult(
        status="ok",
        output=summary,
        data=response.to_dict(),
    )


def _summarize_response(label: str, response: AlphaVantageResponse) -> str:
    data = response.data
    facts = [f"Alpha Vantage {label} returned {response.function} data."]
    if isinstance(data, dict):
        if "feed" in data and isinstance(data["feed"], list):
            facts.append(f"news_items={len(data['feed'])}")
        if "top_gainers" in data and isinstance(data["top_gainers"], list):
            facts.append(f"top_gainers={len(data['top_gainers'])}")
        if "top_losers" in data and isinstance(data["top_losers"], list):
            facts.append(f"top_losers={len(data['top_losers'])}")
        if "most_actively_traded" in data and isinstance(data["most_actively_traded"], list):
            facts.append(f"most_active={len(data['most_actively_traded'])}")
        if "data" in data and isinstance(data["data"], list):
            facts.append(f"rows={len(data['data'])}")
        if "transcript" in data and isinstance(data["transcript"], list):
            facts.append(f"transcript_segments={len(data['transcript'])}")
    elif isinstance(data, list):
        facts.append(f"rows={len(data)}")

    params = ", ".join(f"{key}={value}" for key, value in response.request_params.items())
    facts.append(f"request_params: {params or 'none'}.")
    facts.append(
        "Use this as third-party intelligence context; do not treat it as broker state."
    )
    return " ".join(facts)


def _format_most_actively_traded_output(
    most_active: list[dict[str, Any]],
    *,
    response: AlphaVantageResponse,
) -> str:
    if not most_active:
        return (
            "Alpha Vantage most_actively_traded returned no most-active entries. "
            "Retry later or use another market-data provider."
        )
    facts = [
        "Alpha Vantage most_actively_traded returned current most-active volume context."
    ]
    preview: list[str] = []
    for item in most_active[:5]:
        preview.append(
            f"{item.get('ticker') or item.get('symbol')}: "
            f"price={item.get('price')}, "
            f"change_pct={item.get('change_percentage')}, "
            f"volume={item.get('volume')}"
        )
    if preview:
        facts.append("Top entries: " + "; ".join(preview) + ".")
    params = ", ".join(f"{key}={value}" for key, value in response.request_params.items())
    facts.append(f"request_params: {params or 'none'}.")
    facts.append(
        "Use this as third-party activity context; do not treat it as broker state."
    )
    return " ".join(facts)


def _error_hint(retryable: bool) -> str:
    if retryable:
        return (
            "Alpha Vantage may be rate-limited, temporarily unavailable, or gated by "
            "entitlement. Retry later, lower the limit, or use a narrower symbol list."
        )
    return "Check endpoint parameters, symbol format, API key, and plan entitlement."


ALPHA_VANTAGE_INTELLIGENCE_TOOLBOX = ToolBox(
    name="alpha_vantage_intelligence",
    tools=[
        ALPHA_VANTAGE_NEWS_SENTIMENT_TOOL,
        ALPHA_VANTAGE_EARNINGS_CALL_TRANSCRIPT_TOOL,
        ALPHA_VANTAGE_TOP_GAINERS_LOSERS_TOOL,
        ALPHA_VANTAGE_MOST_ACTIVELY_TRADED_TOOL,
        ALPHA_VANTAGE_INSIDER_TRANSACTIONS_TOOL,
        ALPHA_VANTAGE_INSTITUTIONAL_HOLDINGS_TOOL,
        ALPHA_VANTAGE_ANALYTICS_FIXED_WINDOW_TOOL,
        ALPHA_VANTAGE_ANALYTICS_SLIDING_WINDOW_TOOL,
    ],
    tools_by_name=build_tool_index(
        [
            ALPHA_VANTAGE_NEWS_SENTIMENT_TOOL,
            ALPHA_VANTAGE_EARNINGS_CALL_TRANSCRIPT_TOOL,
            ALPHA_VANTAGE_TOP_GAINERS_LOSERS_TOOL,
            ALPHA_VANTAGE_MOST_ACTIVELY_TRADED_TOOL,
            ALPHA_VANTAGE_INSIDER_TRANSACTIONS_TOOL,
            ALPHA_VANTAGE_INSTITUTIONAL_HOLDINGS_TOOL,
            ALPHA_VANTAGE_ANALYTICS_FIXED_WINDOW_TOOL,
            ALPHA_VANTAGE_ANALYTICS_SLIDING_WINDOW_TOOL,
        ]
    ),
)
