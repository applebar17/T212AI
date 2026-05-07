"""LLM-facing market signal memory tools."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Any, Callable

from t212ai.genai.models import ToolError, ToolResult, ToolSpec
from t212ai.genai.tools.base import ToolBox, build_tool_index
from t212ai.genai.tracing import set_trace_metadata, traceable

from .service import MarketSignalService


@dataclass(slots=True)
class MarketSignalToolRuntime:
    service: MarketSignalService | None = None


MARKET_SIGNAL_SEARCH_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "market_signal_search",
        "description": (
            "Search persistent market signal memory for advisory context. Prefer broad "
            "searches when the request is ambiguous: use one or two filters such as "
            "symbols, sectors, or tags before adding direction, horizon, source, or "
            "signal_type filters. Results are stored notes, not fresh market data or "
            "broker-authoritative state."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "default": None,
                    "description": "Public symbols or tickers to match broadly.",
                },
                "sectors": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "default": None,
                    "description": "Sectors/themes such as semiconductors, banks, energy.",
                },
                "tags": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "default": None,
                    "description": "Flexible topics such as earnings, rates, ai_capex.",
                },
                "signal_types": {
                    "type": ["array", "null"],
                    "items": {
                        "type": "string",
                        "enum": [
                            "catalyst",
                            "macro",
                            "earnings",
                            "sentiment",
                            "technical",
                            "valuation",
                            "risk",
                            "positioning",
                            "news",
                            "regulatory",
                            "portfolio",
                            "other",
                        ],
                    },
                    "default": None,
                },
                "directions": {
                    "type": ["array", "null"],
                    "items": {
                        "type": "string",
                        "enum": ["bullish", "bearish", "neutral", "mixed", "unknown"],
                    },
                    "default": None,
                },
                "impact_horizons": {
                    "type": ["array", "null"],
                    "items": {
                        "type": "string",
                        "enum": [
                            "intraday",
                            "short_term",
                            "medium_term",
                            "long_term",
                            "unknown",
                        ],
                    },
                    "default": None,
                },
                "sources": {
                    "type": ["array", "null"],
                    "items": {
                        "type": "string",
                        "enum": [
                            "user",
                            "agent",
                            "scheduled_job",
                            "search",
                            "sec_edgar",
                            "reddit",
                            "market_data",
                            "broker_context",
                            "other",
                        ],
                    },
                    "default": None,
                },
                "active_only": {"type": "boolean", "default": True},
                "include_expired": {"type": "boolean", "default": False},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 8,
                },
            },
            "required": [
                "symbols",
                "sectors",
                "tags",
                "signal_types",
                "directions",
                "impact_horizons",
                "sources",
                "active_only",
                "include_expired",
                "limit",
            ],
            "additionalProperties": False,
        },
    },
}

MARKET_SIGNAL_CREATE_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "market_signal_create",
        "description": (
            "Create one concise persistent market signal. Use only when the user "
            "explicitly asks to save a signal or the current configured process is a "
            "capture workflow. Write future-useful market impact summaries, not raw "
            "search dumps. Provide at least one symbol, sector, or tag."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "summary": {
                    "type": "string",
                    "description": (
                        "Concise LLM-readable note with likely future impact and caveats."
                    ),
                },
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                },
                "sectors": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                },
                "signal_type": {
                    "type": "string",
                    "enum": [
                        "catalyst",
                        "macro",
                        "earnings",
                        "sentiment",
                        "technical",
                        "valuation",
                        "risk",
                        "positioning",
                        "news",
                        "regulatory",
                        "portfolio",
                        "other",
                    ],
                    "default": "other",
                },
                "direction": {
                    "type": "string",
                    "enum": ["bullish", "bearish", "neutral", "mixed", "unknown"],
                    "default": "unknown",
                },
                "impact_horizon": {
                    "type": "string",
                    "enum": [
                        "intraday",
                        "short_term",
                        "medium_term",
                        "long_term",
                        "unknown",
                    ],
                    "default": "unknown",
                },
                "source": {
                    "type": "string",
                    "enum": [
                        "user",
                        "agent",
                        "scheduled_job",
                        "search",
                        "sec_edgar",
                        "reddit",
                        "market_data",
                        "broker_context",
                        "other",
                    ],
                    "default": "agent",
                },
                "source_refs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                    "description": "Compact provenance refs such as URLs or tool/source ids.",
                },
                "expires_at": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Optional ISO-8601 expiry timestamp for time-sensitive signals.",
                },
            },
            "required": [
                "title",
                "summary",
                "symbols",
                "sectors",
                "tags",
                "signal_type",
                "direction",
                "impact_horizon",
                "source",
                "source_refs",
                "expires_at",
            ],
            "additionalProperties": False,
        },
    },
}

MARKET_SIGNAL_ARCHIVE_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "market_signal_archive",
        "description": (
            "Archive one explicit market signal by id. This never deletes rows and "
            "should only be used when a signal is obsolete, superseded, or the user "
            "explicitly asks to archive it."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "signal_id": {"type": "string"},
                "source": {
                    "type": "string",
                    "enum": [
                        "user",
                        "agent",
                        "scheduled_job",
                        "search",
                        "sec_edgar",
                        "reddit",
                        "market_data",
                        "broker_context",
                        "other",
                    ],
                    "default": "agent",
                },
            },
            "required": ["signal_id", "source"],
            "additionalProperties": False,
        },
    },
}

MARKET_SIGNAL_TOOLS: list[ToolSpec] = [
    MARKET_SIGNAL_SEARCH_TOOL,
    MARKET_SIGNAL_CREATE_TOOL,
    MARKET_SIGNAL_ARCHIVE_TOOL,
]

MARKET_SIGNAL_TOOLBOX = ToolBox(
    name="market_signals",
    tools=MARKET_SIGNAL_TOOLS,
    tools_by_name=build_tool_index(MARKET_SIGNAL_TOOLS),
)


def build_market_signal_tool_mapping(
    service: MarketSignalService | None,
) -> dict[str, Callable[..., ToolResult]]:
    runtime = MarketSignalToolRuntime(service=service)
    return {
        "market_signal_search": partial(market_signal_search, runtime=runtime),
        "market_signal_create": partial(market_signal_create, runtime=runtime),
        "market_signal_archive": partial(market_signal_archive, runtime=runtime),
    }


@traceable(
    name="market_signal_search",
    run_type="tool",
)
def market_signal_search(
    *,
    symbols: list[str] | None,
    sectors: list[str] | None,
    tags: list[str] | None,
    signal_types: list[str] | None,
    directions: list[str] | None,
    impact_horizons: list[str] | None,
    sources: list[str] | None,
    active_only: bool,
    include_expired: bool,
    limit: int,
    runtime: MarketSignalToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider="market_signals", tool_name="market_signal_search")
    if runtime.service is None:
        return _missing_service()
    try:
        matches = runtime.service.search_signals(
            symbols=symbols,
            sectors=sectors,
            tags=tags,
            signal_types=signal_types,
            directions=directions,
            impact_horizons=impact_horizons,
            sources=sources,
            active_only=active_only,
            include_expired=include_expired,
            limit=limit,
        )
    except Exception as exc:
        return _tool_exception(exc, operation="search")
    output = _search_output(matches)
    return ToolResult(
        status="ok",
        output=output,
        data={
            "count": len(matches),
            "matches": [
                match.model_dump(by_alias=True, exclude_none=True, mode="json")
                for match in matches
            ],
        },
    )


@traceable(
    name="market_signal_create",
    run_type="tool",
)
def market_signal_create(
    *,
    title: str,
    summary: str,
    symbols: list[str],
    sectors: list[str],
    tags: list[str],
    signal_type: str,
    direction: str,
    impact_horizon: str,
    source: str,
    source_refs: list[str],
    expires_at: str | None,
    runtime: MarketSignalToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider="market_signals", tool_name="market_signal_create")
    if runtime.service is None:
        return _missing_service()
    try:
        signal = runtime.service.create_signal(
            title=title,
            summary=summary,
            symbols=symbols,
            sectors=sectors,
            tags=tags,
            signal_type=signal_type or "other",
            direction=direction or "unknown",
            impact_horizon=impact_horizon or "unknown",
            source=source or "agent",
            source_refs=source_refs,
            expires_at=_parse_optional_datetime(expires_at),
        )
    except Exception as exc:
        return _tool_exception(exc, operation="create")
    return ToolResult(
        status="ok",
        output=f"Created active market signal {signal.signal_id}: {signal.title}.",
        data={"signal": signal.model_dump(by_alias=True, exclude_none=True, mode="json")},
    )


@traceable(
    name="market_signal_archive",
    run_type="tool",
)
def market_signal_archive(
    *,
    signal_id: str,
    source: str,
    runtime: MarketSignalToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider="market_signals", tool_name="market_signal_archive")
    if runtime.service is None:
        return _missing_service()
    try:
        signal = runtime.service.archive_signal(signal_id, source=source or "agent")
    except Exception as exc:
        return _tool_exception(exc, operation="archive")
    return ToolResult(
        status="ok",
        output=f"Archived market signal {signal.signal_id}: {signal.title}.",
        data={"signal": signal.model_dump(by_alias=True, exclude_none=True, mode="json")},
    )


def _search_output(matches) -> str:
    if not matches:
        return (
            "No active market signals matched. Try a broader search with fewer filters "
            "such as symbols, sectors, or tags only."
        )
    lines = [f"Found {len(matches)} market signal(s)."]
    for match in matches:
        signal = match.signal
        parts = [signal.signal_id, signal.title, signal.signal_type.value]
        if signal.symbols:
            parts.append("symbols=" + ",".join(signal.symbols))
        if signal.sectors:
            parts.append("sectors=" + ",".join(signal.sectors))
        if signal.tags:
            parts.append("tags=" + ",".join(signal.tags))
        parts.append(f"horizon={signal.impact_horizon.value}")
        parts.append(f"direction={signal.direction.value}")
        parts.append("matched=" + ",".join(match.matched_fields or ["all"]))
        lines.append("- " + " | ".join(parts) + f": {signal.summary}")
    return "\n".join(lines)


def _parse_optional_datetime(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("expires_at must be an ISO-8601 timestamp or null.") from exc


def _missing_service() -> ToolResult:
    return ToolResult(
        status="error",
        output="Market signal memory is not configured.",
        error=ToolError(
            message="Market signal memory is not configured.",
            code="market_signal_memory_unavailable",
            hint="Configure DATABASE_URL and ensure the application database is available.",
            retryable=False,
        ),
    )


def _tool_exception(exc: Exception, *, operation: str) -> ToolResult:
    return ToolResult(
        status="error",
        output=f"Market signal {operation} failed. Reason: {exc}.",
        error=ToolError(
            message=str(exc),
            code="market_signal_error",
            type=exc.__class__.__name__,
            hint=(
                "Use concise signal content and provide at least one broad "
                "filter/category such as symbols, sectors, or tags."
            ),
            retryable=False,
            details={"operation": operation},
        ),
    )
