"""EODHD symbol-reference tool definitions."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Any, Callable

from t212ai.genai.models import ToolError, ToolResult, ToolSpec
from t212ai.genai.tools.base import ToolBox, build_tool_index
from t212ai.genai.tracing import set_trace_metadata, traceable

from .client import EodhdApiError, EodhdClient


@dataclass(slots=True)
class EodhdToolRuntime:
    client: EodhdClient


SYMBOL_REFERENCE_SEARCH_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "symbol_reference_search",
        "description": (
            "Search EODHD reference data for instruments by ticker, company name, "
            "or ISIN. Use for symbol and ISIN discovery only, not broker-authoritative "
            "tradability or execution."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Ticker, company name, or ISIN.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "default": 10,
                    "description": "Maximum candidates to return.",
                },
                "asset_type": {
                    "type": "string",
                    "enum": ["all", "stock", "etf", "fund", "bond", "index", "crypto"],
                    "default": "all",
                    "description": "EODHD asset type filter.",
                },
                "exchange": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Optional exchange filter, for example US, NASDAQ, or LSE.",
                },
                "bonds_only": {
                    "type": "boolean",
                    "default": False,
                    "description": "Whether to request only bonds.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}


SYMBOL_REFERENCE_MAP_IDENTIFIERS_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "symbol_reference_map_identifiers",
        "description": (
            "Map between EODHD provider symbols and identifiers such as ISIN, CUSIP, "
            "FIGI, LEI, and CIK. Provide at least one filter. Use as reference data "
            "only; broker tools must verify tradability before order workflows."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": ["string", "null"],
                    "description": "EODHD provider symbol, for example AAPL.US, or null.",
                },
                "exchange": {
                    "type": ["string", "null"],
                    "description": "Exchange code filter, for example US, or null.",
                },
                "isin": {
                    "type": ["string", "null"],
                    "description": "ISIN filter or null.",
                },
                "figi": {
                    "type": ["string", "null"],
                    "description": "OpenFIGI filter or null.",
                },
                "lei": {
                    "type": ["string", "null"],
                    "description": "LEI filter or null.",
                },
                "cusip": {
                    "type": ["string", "null"],
                    "description": "CUSIP filter or null.",
                },
                "cik": {
                    "type": ["string", "null"],
                    "description": "CIK filter or null.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1000,
                    "default": 100,
                    "description": "Maximum records to return.",
                },
                "offset": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 0,
                    "description": "Pagination offset.",
                },
            },
            "required": [
                "symbol",
                "exchange",
                "isin",
                "figi",
                "lei",
                "cusip",
                "cik",
                "limit",
                "offset",
            ],
            "additionalProperties": False,
        },
    },
}


SYMBOL_REFERENCE_TOOLS: list[ToolSpec] = [
    SYMBOL_REFERENCE_SEARCH_TOOL,
    SYMBOL_REFERENCE_MAP_IDENTIFIERS_TOOL,
]


def build_eodhd_tool_mapping(
    runtime: EodhdToolRuntime | None = None,
) -> dict[str, Callable[..., ToolResult]]:
    resolved_runtime = runtime or EodhdToolRuntime(client=EodhdClient.from_settings())
    return {
        "symbol_reference_search": partial(
            symbol_reference_search,
            runtime=resolved_runtime,
        ),
        "symbol_reference_map_identifiers": partial(
            symbol_reference_map_identifiers,
            runtime=resolved_runtime,
        ),
    }


@traceable(name="symbol_reference_search", run_type="tool")
def symbol_reference_search(
    *,
    query: str,
    limit: int = 10,
    asset_type: str = "all",
    exchange: str | None = None,
    bonds_only: bool = False,
    runtime: EodhdToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider="eodhd", tool_name="symbol_reference_search")
    try:
        result = runtime.client.search(
            query,
            limit=limit,
            asset_type=asset_type,
            exchange=exchange,
            bonds_only=bonds_only,
        )
    except EodhdApiError as exc:
        return _api_error_result(exc, operation="symbol_reference_search")
    except Exception as exc:
        return _tool_error_result(exc, operation="symbol_reference_search")
    candidates = [candidate.to_dict() for candidate in result.candidates]
    return ToolResult(
        status="ok",
        output=_format_search_output(query=result.query, candidates=candidates),
        data={
            "provider": "eodhd",
            "query": result.query,
            "candidates": candidates,
            "request_params": result.request_params,
            "endpoint": result.endpoint,
            "authority": "reference_data_only",
        },
    )


@traceable(name="symbol_reference_map_identifiers", run_type="tool")
def symbol_reference_map_identifiers(
    *,
    symbol: str | None,
    exchange: str | None,
    isin: str | None,
    figi: str | None,
    lei: str | None,
    cusip: str | None,
    cik: str | None,
    limit: int = 100,
    offset: int = 0,
    runtime: EodhdToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider="eodhd", tool_name="symbol_reference_map_identifiers")
    try:
        result = runtime.client.id_mapping(
            symbol=symbol,
            exchange=exchange,
            isin=isin,
            figi=figi,
            lei=lei,
            cusip=cusip,
            cik=cik,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        return ToolResult(
            status="error",
            output=(
                "EODHD identifier mapping needs at least one filter: symbol, exchange, "
                "isin, figi, lei, cusip, or cik."
            ),
            error=ToolError(
                message=str(exc),
                code="eodhd_missing_identifier_filter",
                type=exc.__class__.__name__,
                hint="Retry with one identifier filter.",
                retryable=False,
            ),
        )
    except EodhdApiError as exc:
        return _api_error_result(exc, operation="symbol_reference_map_identifiers")
    except Exception as exc:
        return _tool_error_result(exc, operation="symbol_reference_map_identifiers")
    records = [record.to_dict() for record in result.records]
    return ToolResult(
        status="ok",
        output=_format_mapping_output(records=records, total=result.total),
        data={
            "provider": "eodhd",
            "records": records,
            "total": result.total,
            "limit": result.limit,
            "offset": result.offset,
            "next_url": result.next_url,
            "request_params": result.request_params,
            "endpoint": result.endpoint,
            "authority": "reference_data_only",
        },
    )


def _format_search_output(*, query: str, candidates: list[dict[str, Any]]) -> str:
    lines = [
        f"EODHD symbol reference search returned {len(candidates)} candidate(s) for {query}.",
        "Use this as reference data only; broker tools must verify tradability.",
    ]
    for candidate in candidates[:8]:
        label = candidate.get("provider_symbol") or candidate.get("code") or "unknown"
        name = candidate.get("name") or "unknown name"
        isin = candidate.get("isin") or "no ISIN"
        lines.append(f"- {label}: {name}; ISIN={isin}")
    return "\n".join(lines)


def _format_mapping_output(*, records: list[dict[str, Any]], total: int | None) -> str:
    lines = [
        "EODHD identifier mapping returned "
        f"{len(records)} record(s){f' of {total}' if total is not None else ''}.",
        "Use this as reference data only; broker tools must verify tradability.",
    ]
    for record in records[:8]:
        symbol = record.get("provider_symbol") or "unknown symbol"
        identifiers = ", ".join(
            f"{key.upper()}={record[key]}"
            for key in ("isin", "cusip", "figi", "lei", "cik")
            if record.get(key)
        )
        lines.append(f"- {symbol}: {identifiers or 'no identifiers'}")
    return "\n".join(lines)


def _api_error_result(exc: EodhdApiError, *, operation: str) -> ToolResult:
    context = exc.context
    return ToolResult(
        status="error",
        output=(
            f"EODHD {operation} failed. Reason: {context.message}. "
            "Retry later or narrow the identifier/reference lookup."
        ),
        error=ToolError(
            message=context.message or "EODHD request failed.",
            code="eodhd_api_error",
            type=exc.__class__.__name__,
            hint="Retry later if the issue is rate-limit or provider availability related.",
            retryable=context.retryable,
            details={
                "operation": context.operation,
                "endpoint": context.endpoint,
                "status_code": context.status_code,
                **context.details,
            },
        ),
    )


def _tool_error_result(exc: Exception, *, operation: str) -> ToolResult:
    return ToolResult(
        status="error",
        output=(
            f"EODHD {operation} failed before usable reference data was produced. "
            "Validate the query and provider configuration."
        ),
        error=ToolError(
            message=str(exc),
            code="eodhd_tool_error",
            type=exc.__class__.__name__,
            hint="Use a valid query or identifier filter and retry.",
            retryable=False,
        ),
    )


SYMBOL_REFERENCE_TOOLBOX = ToolBox(
    name="symbol_reference",
    tools=SYMBOL_REFERENCE_TOOLS,
    tools_by_name=build_tool_index(SYMBOL_REFERENCE_TOOLS),
)
