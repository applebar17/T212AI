"""Provider-neutral symbol-reference tool facade."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from t212ai.data_sources.eodhd import (
    SYMBOL_REFERENCE_MAP_IDENTIFIERS_TOOL,
    SYMBOL_REFERENCE_SEARCH_TOOL,
    SYMBOL_REFERENCE_TOOLS,
)
from t212ai.genai.models import ToolError, ToolResult
from t212ai.genai.tracing import set_trace_metadata, traceable

if TYPE_CHECKING:
    from t212ai.capabilities.protocols import SymbolReferenceService


def build_symbol_reference_tool_mapping(
    service: "SymbolReferenceService | None",
) -> dict[str, Any]:
    return {
        "symbol_reference_search": partial(symbol_reference_search, service=service),
        "symbol_reference_map_identifiers": partial(
            symbol_reference_map_identifiers,
            service=service,
        ),
    }


@traceable(name="symbol_reference_search", run_type="tool")
def symbol_reference_search(
    *,
    query: str,
    limit: int = 15,
    asset_type: str = "all",
    exchange: str | None = None,
    bonds_only: bool = False,
    service: "SymbolReferenceService | None" = None,
) -> ToolResult:
    provider = _provider_name(service)
    set_trace_metadata(provider=provider, tool_name="symbol_reference_search")
    if service is None:
        return _missing_service_result("symbol_reference_search")
    try:
        result = service.search(
            query,
            limit=limit,
            asset_type=asset_type,
            exchange=exchange,
            bonds_only=bonds_only,
        )
    except Exception as exc:
        return _exception_result(exc, operation="symbol_reference_search")
    provider = _result_provider(result.meta, service)
    candidates = list(result.candidates)
    return ToolResult(
        status="ok",
        output=_format_search_output(
            provider=provider,
            query=result.query,
            candidates=candidates,
        ),
        data={
            "provider": provider,
            "query": result.query,
            "candidates": candidates,
            "meta": dict(result.meta),
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
    service: "SymbolReferenceService | None" = None,
) -> ToolResult:
    provider = _provider_name(service)
    set_trace_metadata(provider=provider, tool_name="symbol_reference_map_identifiers")
    if service is None:
        return _missing_service_result("symbol_reference_map_identifiers")
    filters = (symbol, exchange, isin, figi, lei, cusip, cik)
    if not any(str(value or "").strip() for value in filters):
        return ToolResult(
            status="error",
            output=(
                "Identifier mapping requires at least one filter: symbol, exchange, "
                "isin, figi, lei, cusip, or cik."
            ),
            error=ToolError(
                message="At least one identifier filter is required.",
                code="symbol_reference_missing_identifier_filter",
                hint="Retry with a symbol, ISIN, CUSIP, FIGI, LEI, or CIK.",
                retryable=False,
            ),
        )
    try:
        result = service.map_identifiers(
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
    except Exception as exc:
        return _exception_result(exc, operation="symbol_reference_map_identifiers")
    provider = _result_provider(result.meta, service)
    records = list(result.records)
    return ToolResult(
        status="ok",
        output=_format_mapping_output(provider=provider, records=records, total=result.total),
        data={
            "provider": provider,
            "records": records,
            "total": result.total,
            "limit": result.limit,
            "offset": result.offset,
            "next_url": result.next_url,
            "meta": dict(result.meta),
            "authority": "reference_data_only",
        },
    )


def _format_search_output(
    *,
    provider: str,
    query: str,
    candidates: list[dict[str, Any]],
) -> str:
    lines = [
        f"Symbol reference via {provider} returned {len(candidates)} candidate(s) for {query}.",
        "Use as identity/reference data only; verify broker tradability with broker tools.",
    ]
    for candidate in candidates[:8]:
        symbol = candidate.get("provider_symbol") or candidate.get("code") or "unknown"
        name = candidate.get("name") or "unknown name"
        isin = candidate.get("isin") or "no ISIN"
        lines.append(f"- {symbol}: {name}; ISIN={isin}")
    return "\n".join(lines)


def _format_mapping_output(
    *,
    provider: str,
    records: list[dict[str, Any]],
    total: int | None,
) -> str:
    lines = [
        "Symbol identifier mapping via "
        f"{provider} returned {len(records)} record(s)"
        f"{f' of {total}' if total is not None else ''}.",
        "Use as identity/reference data only; verify broker tradability with broker tools.",
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


def _missing_service_result(tool_name: str) -> ToolResult:
    return ToolResult(
        status="error",
        output=f"{tool_name} is unavailable because no symbol-reference provider is configured.",
        error=ToolError(
            message="Symbol-reference provider is not configured.",
            code="symbol_reference_not_configured",
            hint="Configure SYMBOL_REFERENCE_PROVIDER=eodhd and EODHD_API_TOKEN.",
            retryable=False,
        ),
    )


def _exception_result(exc: Exception, *, operation: str) -> ToolResult:
    return ToolResult(
        status="error",
        output=(
            f"{operation} failed before usable reference data was produced. "
            "Validate the input and provider configuration."
        ),
        error=ToolError(
            message=str(exc),
            code="symbol_reference_tool_error",
            type=exc.__class__.__name__,
            hint="Retry with a valid reference query or identifier filter.",
            retryable=False,
        ),
    )


def _provider_name(service: "SymbolReferenceService | None") -> str:
    return str(getattr(service, "provider_name", None) or "symbol_reference")


def _result_provider(meta: dict[str, Any], service: "SymbolReferenceService | None") -> str:
    provider = meta.get("provider") if isinstance(meta, dict) else None
    return str(provider or _provider_name(service))
