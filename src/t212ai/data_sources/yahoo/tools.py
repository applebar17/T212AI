"""Yahoo Finance convenience tools."""

from __future__ import annotations

from typing import Any

from t212ai.genai.models import ToolError, ToolResult, ToolSpec
from t212ai.genai.tracing import (
    set_trace_metadata,
    traceable,
)

from .analytics import PriceSeriesAnalytics
from .client import YahooFinanceClient
from .models import (
    YahooFinanceError,
    YahooOptionsResult,
    YahooPriceHistoryResult,
    YahooQuoteSnapshotResult,
    YahooQuoteSummaryResult,
    YahooSearchResult,
)


_YAHOO_PRICE_COMMON_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tickers": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of Yahoo ticker symbols, for example ['AAPL', 'MSFT'].",
        },
        "period": {
            "type": "string",
            "default": "1mo",
            "description": (
                "Yahoo Finance period, for example 1d, 5d, 1mo, 3mo, 6mo, "
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
        "tickers",
        "period",
        "interval",
        "start",
        "end",
        "auto_adjust",
    ],
    "additionalProperties": False,
}


YAHOO_PRICE_HISTORY_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "yahoo_price_history",
        "description": (
            "Retrieve Yahoo historical prices for one or more tickers. "
            "Returns OHLC, adjusted close, volume, and timestamps."
        ),
        "strict": True,
        "parameters": _YAHOO_PRICE_COMMON_PARAMETERS,
    },
}

YAHOO_PRICE_SUMMARY_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "yahoo_price_summary",
        "description": (
            "Retrieve Yahoo price analytics for one or more tickers. Includes "
            "open, close, high, low, absolute and percent move, annualized "
            "volatility, max drawdown, and average volume."
        ),
        "strict": True,
        "parameters": _YAHOO_PRICE_COMMON_PARAMETERS,
    },
}

YAHOO_PRICE_SUMMARY_WITH_CHART_REFS_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "yahoo_price_summary_with_chart_refs",
        "description": (
            "Retrieve Yahoo price analytics plus chart placement references. "
            "Also returns raw series for UI chart rendering."
        ),
        "strict": True,
        "parameters": _YAHOO_PRICE_COMMON_PARAMETERS,
    },
}

YAHOO_SYMBOL_SEARCH_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "yahoo_symbol_search",
        "description": (
            "Search Yahoo Finance symbols for a company, ETF, fund, index, or "
            "ambiguous user phrase. Use before analysis when the ticker is unclear."
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
                    "description": "Maximum quote candidates.",
                },
                "news_count": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 10,
                    "default": 0,
                    "description": "Maximum Yahoo news candidates.",
                },
            },
            "required": ["query", "quotes_count", "news_count"],
            "additionalProperties": False,
        },
    },
}

YAHOO_QUOTE_SNAPSHOT_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "yahoo_quote_snapshot",
        "description": (
            "Fetch a best-effort Yahoo quote snapshot for one or more tickers. "
            "Useful for convenience context, not broker-authoritative state."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "tickers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Yahoo ticker symbols.",
                }
            },
            "required": ["tickers"],
            "additionalProperties": False,
        },
    },
}

YAHOO_MARKET_SNAPSHOT_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "yahoo_market_snapshot",
        "description": (
            "Fetch a compact Yahoo market context packet: quote snapshot plus "
            "recent price analytics for one or more tickers."
        ),
        "strict": True,
        "parameters": _YAHOO_PRICE_COMMON_PARAMETERS,
    },
}

YAHOO_VOLUME_MONITOR_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "yahoo_volume_monitor",
        "description": (
            "Compare Yahoo current quote volume against average historical volume "
            "for one or more tickers. Useful for relative-volume and activity-spike context."
        ),
        "strict": True,
        "parameters": _YAHOO_PRICE_COMMON_PARAMETERS,
    },
}

YAHOO_OPTIONS_SNAPSHOT_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "yahoo_options_snapshot",
        "description": (
            "Fetch a best-effort Yahoo options-chain summary for a ticker. "
            "Useful for liquidity/skew context, not execution."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Yahoo ticker symbol."},
                "expiration": {
                    "type": ["integer", "null"],
                    "default": None,
                    "description": "Unix expiration timestamp or null for nearest/default.",
                },
                "max_contracts": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20,
                    "description": "Maximum calls and puts to return after ranking.",
                },
            },
            "required": ["symbol", "expiration", "max_contracts"],
            "additionalProperties": False,
        },
    },
}

YAHOO_ANALYST_SNAPSHOT_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "yahoo_analyst_snapshot",
        "description": (
            "Fetch best-effort Yahoo analyst context for one ticker, including "
            "financialData, recommendation trend, earnings trend, and upgrades."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {"symbol": {"type": "string", "description": "Yahoo ticker."}},
            "required": ["symbol"],
            "additionalProperties": False,
        },
    },
}

YAHOO_MARKET_CONTEXT_TOOLS: list[ToolSpec] = [
    YAHOO_SYMBOL_SEARCH_TOOL,
    YAHOO_QUOTE_SNAPSHOT_TOOL,
    YAHOO_PRICE_SUMMARY_TOOL,
    YAHOO_MARKET_SNAPSHOT_TOOL,
    YAHOO_VOLUME_MONITOR_TOOL,
    YAHOO_OPTIONS_SNAPSHOT_TOOL,
    YAHOO_ANALYST_SNAPSHOT_TOOL,
]


def build_yahoo_tool_mapping(
    client: YahooFinanceClient | None = None,
) -> dict[str, Any]:
    yahoo_client = client or YahooFinanceClient()
    return {
        "yahoo_price_history": lambda **kwargs: yahoo_price_history(
            client=yahoo_client,
            **kwargs,
        ),
        "yahoo_price_summary": lambda **kwargs: yahoo_price_summary(
            client=yahoo_client,
            **kwargs,
        ),
        "yahoo_price_summary_with_chart_refs": lambda **kwargs: (
            yahoo_price_summary_with_chart_refs(client=yahoo_client, **kwargs)
        ),
        "yahoo_symbol_search": lambda **kwargs: yahoo_symbol_search(
            client=yahoo_client,
            **kwargs,
        ),
        "yahoo_quote_snapshot": lambda **kwargs: yahoo_quote_snapshot(
            client=yahoo_client,
            **kwargs,
        ),
        "yahoo_market_snapshot": lambda **kwargs: yahoo_market_snapshot(
            client=yahoo_client,
            **kwargs,
        ),
        "yahoo_volume_monitor": lambda **kwargs: yahoo_volume_monitor(
            client=yahoo_client,
            **kwargs,
        ),
        "yahoo_options_snapshot": lambda **kwargs: yahoo_options_snapshot(
            client=yahoo_client,
            **kwargs,
        ),
        "yahoo_analyst_snapshot": lambda **kwargs: yahoo_analyst_snapshot(
            client=yahoo_client,
            **kwargs,
        ),
    }


@traceable(
    name="yahoo_price_history",
    run_type="tool"
)
def yahoo_price_history(
    *,
    tickers: list[str] | tuple[str, ...],
    period: str = "1mo",
    interval: str = "1d",
    start: str | None = None,
    end: str | None = None,
    auto_adjust: bool = False,
    client: YahooFinanceClient | None = None,
) -> ToolResult:
    set_trace_metadata(provider="yahoo_finance", tool_name="yahoo_price_history")
    symbols = _normalize_symbols(tickers)
    if not symbols:
        return _input_error("At least one ticker is required.", "missing_tickers")
    result = _fetch_price_history(
        symbols=symbols,
        period=period,
        interval=interval,
        start=start,
        end=end,
        auto_adjust=auto_adjust,
        client=client,
    )
    total_points = result["total_points"]
    output = (
        f"Yahoo returned {total_points} historical price points for "
        f"{len(result['series_payload'])} ticker(s). "
        "Use this as convenience market context, not broker-authoritative state."
    )
    if result["errors"]:
        output += f" Errors were returned for: {', '.join(result['errors'].keys())}."
    return ToolResult(
        status="ok",
        output=output,
        data={
            "series": result["series_payload"],
            "errors": result["errors"],
            "meta": result["meta"],
            "total_points": total_points,
        },
    )


@traceable(
    name="yahoo_price_summary",
    run_type="tool"
)
def yahoo_price_summary(
    *,
    tickers: list[str] | tuple[str, ...],
    period: str = "1mo",
    interval: str = "1d",
    start: str | None = None,
    end: str | None = None,
    auto_adjust: bool = False,
    client: YahooFinanceClient | None = None,
) -> ToolResult:
    set_trace_metadata(provider="yahoo_finance", tool_name="yahoo_price_summary")
    symbols = _normalize_symbols(tickers)
    if not symbols:
        return _input_error("At least one ticker is required.", "missing_tickers")
    result = _fetch_price_history(
        symbols=symbols,
        period=period,
        interval=interval,
        start=start,
        end=end,
        auto_adjust=auto_adjust,
        client=client,
    )
    summary_payload = PriceSeriesAnalytics.summarize_series(result["series_payload"])
    return ToolResult(
        status="ok",
        output=_format_price_summary_output(summary_payload, result["errors"]),
        data={
            "summary": summary_payload,
            "errors": result["errors"],
            "meta": result["meta"],
            "total_points": result["total_points"],
        },
    )


@traceable(
    name="yahoo_price_summary_with_chart_refs",
    run_type="tool"
)
def yahoo_price_summary_with_chart_refs(
    *,
    tickers: list[str] | tuple[str, ...],
    period: str = "1mo",
    interval: str = "1d",
    start: str | None = None,
    end: str | None = None,
    auto_adjust: bool = False,
    client: YahooFinanceClient | None = None,
) -> ToolResult:
    set_trace_metadata(
        provider="yahoo_finance",
        tool_name="yahoo_price_summary_with_chart_refs",
    )
    symbols = _normalize_symbols(tickers)
    if not symbols:
        return _input_error("At least one ticker is required.", "missing_tickers")
    result = _fetch_price_history(
        symbols=symbols,
        period=period,
        interval=interval,
        start=start,
        end=end,
        auto_adjust=auto_adjust,
        client=client,
    )
    series_payload = result["series_payload"]
    summary_payload = PriceSeriesAnalytics.summarize_series(series_payload)
    chart_refs = _build_chart_refs(series_payload, result.get("meta") or {})
    placement_guidance = (
        "A price chart can be rendered in the UI by rendering the exact "
        "standalone placeholder token returned in chart_refs."
    )
    return ToolResult(
        status="ok",
        output=f"{_format_price_summary_output(summary_payload, result['errors'])} "
        f"{placement_guidance}",
        data={
            "summary": summary_payload,
            "series": series_payload,
            "chart_refs": chart_refs,
            "placement_guidance": placement_guidance,
            "errors": result["errors"],
            "meta": result["meta"],
            "total_points": result["total_points"],
        },
    )


@traceable(
    name="yahoo_symbol_search",
    run_type="tool"
)
def yahoo_symbol_search(
    *,
    query: str,
    quotes_count: int = 8,
    news_count: int = 0,
    client: YahooFinanceClient | None = None,
) -> ToolResult:
    set_trace_metadata(provider="yahoo_finance", tool_name="yahoo_symbol_search")
    yf_client = client or YahooFinanceClient()
    try:
        result = yf_client.search_symbols(
            query,
            quotes_count=quotes_count,
            news_count=news_count,
        )
    except Exception as exc:
        return _exception_result(exc, operation="symbol_search")
    return ToolResult(
        status="ok",
        output=_format_symbol_search_output(result),
        data={
            "query": result.query,
            "quotes": result.quotes,
            "news": result.news,
            "meta": result.meta,
        },
    )


@traceable(
    name="yahoo_quote_snapshot",
    run_type="tool"
)
def yahoo_quote_snapshot(
    *,
    tickers: list[str] | tuple[str, ...],
    client: YahooFinanceClient | None = None,
) -> ToolResult:
    set_trace_metadata(provider="yahoo_finance", tool_name="yahoo_quote_snapshot")
    symbols = _normalize_symbols(tickers)
    if not symbols:
        return _input_error("At least one ticker is required.", "missing_tickers")
    yf_client = client or YahooFinanceClient()
    try:
        result = yf_client.get_quote_snapshot(symbols)
    except Exception as exc:
        return _exception_result(exc, operation="quote_snapshot")
    return ToolResult(
        status="ok",
        output=_format_quote_snapshot_output(result),
        data={"quotes": result.quotes, "errors": result.errors, "meta": result.meta},
    )


@traceable(
    name="yahoo_market_snapshot",
    run_type="tool"
)
def yahoo_market_snapshot(
    *,
    tickers: list[str] | tuple[str, ...],
    period: str = "1mo",
    interval: str = "1d",
    start: str | None = None,
    end: str | None = None,
    auto_adjust: bool = False,
    client: YahooFinanceClient | None = None,
) -> ToolResult:
    set_trace_metadata(provider="yahoo_finance", tool_name="yahoo_market_snapshot")
    symbols = _normalize_symbols(tickers)
    if not symbols:
        return _input_error("At least one ticker is required.", "missing_tickers")
    yf_client = client or YahooFinanceClient()
    try:
        quotes = yf_client.get_quote_snapshot(symbols)
    except Exception as exc:
        return _exception_result(exc, operation="market_snapshot_quotes")
    price_result = _fetch_price_history(
        symbols=symbols,
        period=period,
        interval=interval,
        start=start,
        end=end,
        auto_adjust=auto_adjust,
        client=yf_client,
    )
    summary = PriceSeriesAnalytics.summarize_series(price_result["series_payload"])
    output = (
        f"{_format_quote_snapshot_output(quotes)}\n"
        f"{_format_price_summary_output(summary, price_result['errors'])}"
    )
    return ToolResult(
        status="ok",
        output=output,
        data={
            "quotes": quotes.quotes,
            "quote_errors": quotes.errors,
            "price_summary": summary,
            "price_errors": price_result["errors"],
            "meta": {"quote": quotes.meta, "price": price_result["meta"]},
        },
    )


@traceable(
    name="yahoo_volume_monitor",
    run_type="tool"
)
def yahoo_volume_monitor(
    *,
    tickers: list[str] | tuple[str, ...],
    period: str = "1mo",
    interval: str = "1d",
    start: str | None = None,
    end: str | None = None,
    auto_adjust: bool = False,
    client: YahooFinanceClient | None = None,
) -> ToolResult:
    set_trace_metadata(provider="yahoo_finance", tool_name="yahoo_volume_monitor")
    symbols = _normalize_symbols(tickers)
    if not symbols:
        return _input_error("At least one ticker is required.", "missing_tickers")
    yf_client = client or YahooFinanceClient()
    try:
        quotes = yf_client.get_quote_snapshot(symbols)
    except Exception as exc:
        return _exception_result(exc, operation="volume_monitor_quotes")
    price_result = _fetch_price_history(
        symbols=symbols,
        period=period,
        interval=interval,
        start=start,
        end=end,
        auto_adjust=auto_adjust,
        client=yf_client,
    )
    summary = PriceSeriesAnalytics.summarize_series(price_result["series_payload"])
    monitor = _build_volume_monitor_payload(quotes.quotes, summary)
    return ToolResult(
        status="ok",
        output=_format_volume_monitor_output(
            monitor,
            quote_errors=quotes.errors,
            price_errors=price_result["errors"],
            interval=interval,
        ),
        data={
            "monitor": monitor,
            "quotes": quotes.quotes,
            "quote_errors": quotes.errors,
            "price_summary": summary,
            "price_errors": price_result["errors"],
            "meta": {"quote": quotes.meta, "price": price_result["meta"]},
        },
    )


@traceable(
    name="yahoo_options_snapshot",
    run_type="tool"
)
def yahoo_options_snapshot(
    *,
    symbol: str,
    expiration: int | None,
    max_contracts: int,
    client: YahooFinanceClient | None = None,
) -> ToolResult:
    set_trace_metadata(provider="yahoo_finance", tool_name="yahoo_options_snapshot")
    yf_client = client or YahooFinanceClient()
    try:
        result = yf_client.get_options_chain(symbol, expiration=expiration)
    except Exception as exc:
        return _exception_result(exc, operation="options_snapshot")
    limited_payload = _limit_options_payload(result, max_contracts=max_contracts)
    return ToolResult(
        status="ok",
        output=_format_options_snapshot_output(result),
        data=limited_payload,
    )


@traceable(
    name="yahoo_analyst_snapshot",
    run_type="tool"
)
def yahoo_analyst_snapshot(
    *,
    symbol: str,
    client: YahooFinanceClient | None = None,
) -> ToolResult:
    set_trace_metadata(provider="yahoo_finance", tool_name="yahoo_analyst_snapshot")
    yf_client = client or YahooFinanceClient()
    try:
        result = yf_client.get_analyst_snapshot(symbol)
    except Exception as exc:
        return _exception_result(exc, operation="analyst_snapshot")
    return ToolResult(
        status="ok",
        output=_format_analyst_snapshot_output(result),
        data={
            "symbol": result.symbol,
            "modules": result.modules,
            "data": result.data,
            "meta": result.meta,
        },
    )


def _fetch_price_history(
    *,
    symbols: list[str],
    period: str,
    interval: str,
    start: str | None,
    end: str | None,
    auto_adjust: bool,
    client: YahooFinanceClient | None,
) -> dict[str, Any]:
    yf_client = client or YahooFinanceClient()
    result = yf_client.get_price_history(
        symbols,
        period=period or "1mo",
        interval=interval or "1d",
        start=start,
        end=end,
        auto_adjust=bool(auto_adjust),
    )
    total_points = sum(len(points) for points in result.series.values())
    return {
        "series_payload": dict(result.series),
        "errors": dict(result.errors),
        "meta": dict(result.meta),
        "total_points": total_points,
    }


def _format_symbol_search_output(result: YahooSearchResult) -> str:
    if not result.quotes:
        return (
            f"Yahoo symbol search found no quote candidates for '{result.query}'. "
            "Ask the user for a more specific ticker, exchange, or instrument name."
        )
    candidates = []
    for item in result.quotes[:8]:
        symbol = item.get("symbol")
        name = item.get("shortname") or item.get("longname")
        exchange = item.get("exchDisp") or item.get("exchange")
        quote_type = item.get("quoteType")
        candidates.append(f"{symbol} ({name}, {exchange}, {quote_type})")
    return (
        f"Yahoo symbol search for '{result.query}' found {len(result.quotes)} "
        f"candidate(s): {'; '.join(candidates)}. Use this to resolve ticker ambiguity; "
        "confirm with the user if multiple candidates fit."
    )


def _format_quote_snapshot_output(result: YahooQuoteSnapshotResult) -> str:
    if not result.quotes:
        return (
            "Yahoo quote snapshot returned no quote data. "
            "Use another market-data provider or ask for a clearer ticker."
        )
    lines = [
        "Yahoo quote snapshot. Source tier: informational/convenience, not broker state."
    ]
    for symbol, quote in result.quotes.items():
        lines.append(
            "- "
            f"{symbol}: price={_fmt(quote.get('regularMarketPrice'))} "
            f"{quote.get('currency') or ''}, "
            f"change_pct={_fmt(quote.get('regularMarketChangePercent'))}%, "
            f"volume={_fmt(quote.get('regularMarketVolume'))}, "
            f"market_cap={_fmt(quote.get('marketCap'))}, "
            f"exchange={quote.get('fullExchangeName') or quote.get('exchange')}, "
            f"market_state={quote.get('marketState')}."
        )
    if result.errors:
        lines.append(f"Missing/error tickers: {', '.join(result.errors.keys())}.")
    return "\n".join(lines)


def _format_price_summary_output(
    summary_payload: dict[str, dict[str, Any]],
    errors: dict[str, dict[str, Any]],
) -> str:
    if not summary_payload:
        return (
            "Yahoo price analytics returned no usable series. "
            "Try a broader period, a different interval, or another provider."
        )
    lines = [
        "Yahoo price analytics. Source tier: informational/convenience, not execution-grade."
    ]
    for symbol, summary in summary_payload.items():
        lines.append(
            "- "
            f"{symbol}: points={summary.get('points')}, "
            f"close={_fmt(summary.get('close'))}, "
            f"pct_change={_fmt(summary.get('pct_change'))}%, "
            f"volatility={_fmt(summary.get('annualized_volatility_pct'))}%, "
            f"max_drawdown={_fmt(summary.get('max_drawdown_pct'))}%, "
            f"avg_volume={_fmt(summary.get('average_volume'))}."
        )
    if errors:
        lines.append(f"Yahoo returned errors for: {', '.join(errors.keys())}.")
    return "\n".join(lines)


def _format_options_snapshot_output(result: YahooOptionsResult) -> str:
    option_block = (result.options or [{}])[0] or {}
    calls = option_block.get("calls") or []
    puts = option_block.get("puts") or []
    return (
        f"Yahoo options snapshot for {result.symbol}. "
        f"expiration_dates_available={len(result.expiration_dates)}, "
        f"calls_returned={len(calls)}, puts_returned={len(puts)}. "
        "Use this for liquidity/skew context only; do not treat it as execution data."
    )


def _format_volume_monitor_output(
    monitor_payload: dict[str, dict[str, Any]],
    *,
    quote_errors: dict[str, dict[str, Any]],
    price_errors: dict[str, dict[str, Any]],
    interval: str,
) -> str:
    if not monitor_payload:
        return (
            "Yahoo volume monitor returned no usable data. "
            "Try a different ticker, broader period, or another data source."
        )
    lines = [
        "Yahoo volume monitor. Source tier: informational/convenience, not execution-grade."
    ]
    for symbol, item in monitor_payload.items():
        lines.append(
            "- "
            f"{symbol}: current_volume={_fmt(item.get('current_volume'))}, "
            f"avg_volume={_fmt(item.get('average_volume'))}, "
            f"relative_volume={_fmt(item.get('relative_volume'))}x, "
            f"volume_vs_average={_fmt(item.get('volume_change_pct'))}%, "
            f"signal={item.get('signal')}, "
            f"price_change_pct={_fmt(item.get('price_change_pct'))}%, "
            f"market_state={item.get('market_state')}."
        )
    if interval.strip().lower() != "1d":
        lines.append(
            "Note: relative volume compares Yahoo quote volume against the average "
            "requested series volume, so daily intervals are the most comparable baseline."
        )
    if quote_errors:
        lines.append(f"Quote errors for: {', '.join(quote_errors.keys())}.")
    if price_errors:
        lines.append(f"Price-series errors for: {', '.join(price_errors.keys())}.")
    return "\n".join(lines)


def _format_analyst_snapshot_output(result: YahooQuoteSummaryResult) -> str:
    data = result.data
    financial = data.get("financialData") or {}
    trend = ((data.get("recommendationTrend") or {}).get("trend") or [])
    upgrades = ((data.get("upgradeDowngradeHistory") or {}).get("history") or [])
    earnings = ((data.get("earningsTrend") or {}).get("trend") or [])
    return (
        f"Yahoo analyst snapshot for {result.symbol}. "
        f"current_price={_raw(financial.get('currentPrice'))}, "
        f"target_mean={_raw(financial.get('targetMeanPrice'))}, "
        f"target_low={_raw(financial.get('targetLowPrice'))}, "
        f"target_high={_raw(financial.get('targetHighPrice'))}, "
        f"recommendation={financial.get('recommendationKey')}, "
        f"recommendation_mean={_raw(financial.get('recommendationMean'))}, "
        f"recommendation_periods={len(trend)}, "
        f"upgrade_downgrade_events={len(upgrades)}, earnings_periods={len(earnings)}. "
        "Use this as analyst-context enrichment, not a standalone trade signal."
    )


def _limit_options_payload(result: YahooOptionsResult, *, max_contracts: int) -> dict[str, Any]:
    limit = max(1, min(int(max_contracts or 20), 100))
    options = []
    for block in result.options:
        limited_block = dict(block)
        limited_block["calls"] = _rank_contracts(block.get("calls") or [])[:limit]
        limited_block["puts"] = _rank_contracts(block.get("puts") or [])[:limit]
        options.append(limited_block)
    return {
        "symbol": result.symbol,
        "expiration_dates": result.expiration_dates,
        "quote": result.quote,
        "options": options,
        "meta": result.meta,
    }


def _rank_contracts(contracts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        contracts,
        key=lambda item: (
            _to_float(item.get("volume")) or 0.0,
            _to_float(item.get("openInterest")) or 0.0,
        ),
        reverse=True,
    )


def _normalize_symbols(values: list[str] | tuple[str, ...]) -> list[str]:
    return [str(value).strip().upper() for value in values or [] if str(value).strip()]


def _build_volume_monitor_payload(
    quotes: dict[str, dict[str, Any]],
    summary_payload: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    payload: dict[str, dict[str, Any]] = {}
    symbols = sorted(set(quotes.keys()) | set(summary_payload.keys()))
    for symbol in symbols:
        quote = quotes.get(symbol) or {}
        summary = summary_payload.get(symbol) or {}
        current_volume = _to_float(quote.get("regularMarketVolume"))
        average_volume = _to_float(summary.get("average_volume"))
        relative_volume = None
        volume_change_pct = None
        if current_volume is not None and average_volume not in {None, 0}:
            relative_volume = current_volume / average_volume
            volume_change_pct = ((current_volume - average_volume) / average_volume) * 100.0
        payload[symbol] = {
            "current_volume": _round_number(current_volume),
            "average_volume": _round_number(average_volume),
            "relative_volume": _round_number(relative_volume),
            "volume_change_pct": _round_number(volume_change_pct),
            "signal": _classify_relative_volume(relative_volume),
            "price_change_pct": _to_float(quote.get("regularMarketChangePercent")),
            "market_state": quote.get("marketState"),
        }
    return payload


def _classify_relative_volume(relative_volume: float | None) -> str:
    if relative_volume is None:
        return "insufficient_data"
    if relative_volume >= 3.0:
        return "anomalous"
    if relative_volume >= 1.5:
        return "elevated"
    if relative_volume <= 0.7:
        return "subdued"
    return "normal"


def _input_error(message: str, code: str) -> ToolResult:
    return ToolResult(
        status="error",
        output=f"Yahoo tool input error: {message}",
        error=ToolError(
            message=message,
            code=code,
            hint="Provide valid Yahoo Finance ticker symbols and retry.",
            retryable=False,
        ),
    )


def _exception_result(exc: Exception, *, operation: str) -> ToolResult:
    if isinstance(exc, YahooFinanceError):
        retryable = bool(exc.retryable)
        details = exc.details
        code = exc.code
    else:
        retryable = False
        details = {}
        code = "unexpected_error"
    return ToolResult(
        status="error",
        output=(
            f"Yahoo {operation} failed. Reason: {exc}. "
            "Because Yahoo is an unofficial convenience source, pivot to Alpha Vantage, "
            "web search, or another market-data provider if this context is important."
        ),
        error=ToolError(
            message=str(exc),
            code=f"yahoo_{code}",
            type=exc.__class__.__name__,
            hint=(
                "Retry later or reduce the request." if retryable else
                "Validate ticker/parameters or use another provider."
            ),
            retryable=retryable,
            details=details,
        ),
    )


def _build_chart_refs(
    series_payload: dict[str, list[dict[str, Any]]],
    fetch_meta: dict[str, Any],
) -> dict[str, dict[str, str]]:
    refs: dict[str, dict[str, str]] = {}
    used_ids: set[str] = set()
    period = _normalize_render_slug(str(fetch_meta.get("period") or ""))
    interval = _normalize_render_slug(str(fetch_meta.get("interval") or ""))
    start = _normalize_render_slug(str(fetch_meta.get("start") or ""))
    end = _normalize_render_slug(str(fetch_meta.get("end") or ""))
    range_key = "-".join(part for part in [start, end] if part) or period or "range"
    for symbol, points in series_payload.items():
        if not points:
            continue
        ticker_key = _normalize_render_slug(symbol)
        stable_key = "-".join(
            part for part in [ticker_key, range_key, interval or "interval"] if part
        )
        attachment_id = _build_chart_attachment_id(stable_key)
        suffix = 2
        while attachment_id in used_ids:
            attachment_id = _build_chart_attachment_id(f"{stable_key}-{suffix}")
            suffix += 1
        used_ids.add(attachment_id)
        attachment_slug = attachment_id.removeprefix("chart-")
        refs[symbol] = {
            "chart_id": attachment_id,
            "stable_key": attachment_slug,
            "chart_title": f"{symbol} price history",
            "placeholder": _build_chart_placeholder(attachment_slug),
        }
    return refs


def _normalize_render_slug(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


def _build_chart_attachment_id(stable_key: str) -> str:
    slug = _normalize_render_slug(stable_key) or "chart"
    return f"chart-{slug}"


def _build_chart_placeholder(stable_key: str) -> str:
    return f"{{{{chart:{stable_key}}}}}"


def _raw(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("raw", value.get("fmt"))
    return value


def _fmt(value: Any) -> str:
    raw = _raw(value)
    if raw is None:
        return "unknown"
    if isinstance(raw, float):
        return f"{raw:.4g}"
    return str(raw)


def _to_float(value: Any) -> float | None:
    raw = _raw(value)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _round_number(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)
