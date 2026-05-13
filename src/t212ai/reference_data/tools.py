"""Provider-neutral reference-data tool facade."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING, Any

from t212ai.genai.models import ToolError, ToolResult, ToolSpec
from t212ai.genai.tools.base import ToolBox, build_tool_index
from t212ai.genai.tracing import set_trace_metadata, traceable

if TYPE_CHECKING:
    from t212ai.capabilities.protocols import ReferenceDataService


_REFERENCE_COMMON_FILTERS: dict[str, Any] = {
    "exch_code": {
        "type": ["string", "null"],
        "default": None,
        "description": "Optional OpenFIGI exchange code such as US.",
    },
    "mic_code": {
        "type": ["string", "null"],
        "default": None,
        "description": "Optional ISO MIC code. Do not combine with exch_code.",
    },
    "currency": {
        "type": ["string", "null"],
        "default": None,
        "description": "Optional instrument currency such as USD or EUR.",
    },
    "market_sector": {
        "type": ["string", "null"],
        "default": None,
        "description": "Optional OpenFIGI market sector, for example Equity.",
    },
    "security_type": {
        "type": ["string", "null"],
        "default": None,
        "description": "Optional OpenFIGI security type.",
    },
    "security_type2": {
        "type": ["string", "null"],
        "default": None,
        "description": "Optional broad OpenFIGI security type such as Common Stock.",
    },
    "include_unlisted_equities": {
        "type": ["boolean", "null"],
        "default": None,
        "description": "Whether OpenFIGI should include unlisted equities when supported.",
    },
    "limit": {
        "type": "integer",
        "minimum": 1,
        "maximum": 100,
        "default": 10,
        "description": "Maximum normalized reference candidates to return.",
    },
}


REFERENCE_SECURITY_SEARCH_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "reference_security_search",
        "description": (
            "Broker-agnostic OpenFIGI keyword search for public security identifiers. "
            "Use this to narrow company names, public tickers, exchange/currency "
            "ambiguity, or reference-data candidates before broker-native resolution. "
            "Results are reference data only, not broker tradability."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword, company name, public ticker, or security phrase.",
                },
                **_REFERENCE_COMMON_FILTERS,
            },
            "required": [
                "query",
                "exch_code",
                "mic_code",
                "currency",
                "market_sector",
                "security_type",
                "security_type2",
                "include_unlisted_equities",
                "limit",
            ],
            "additionalProperties": False,
        },
    },
}


REFERENCE_IDENTIFIER_MAP_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "reference_identifier_map",
        "description": (
            "Broker-agnostic OpenFIGI identifier mapping. Use id_type='ID_ISIN' "
            "for ISINs, or TICKER/ID_BB_GLOBAL/COMPOSITE_ID_BB_GLOBAL/"
            "ID_EXCH_SYMBOL/BASE_TICKER for known public identifiers. This can "
            "validate or enrich an identifier before broker_resolve_instrument, "
            "but broker resolution is still required before order preparation."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "id_type": {
                    "type": "string",
                    "enum": [
                        "ID_ISIN",
                        "TICKER",
                        "ID_BB_GLOBAL",
                        "COMPOSITE_ID_BB_GLOBAL",
                        "ID_EXCH_SYMBOL",
                        "BASE_TICKER",
                    ],
                    "description": "OpenFIGI mapping identifier type.",
                },
                "id_value": {
                    "type": "string",
                    "description": "Identifier value, such as an ISIN or public ticker.",
                },
                **_REFERENCE_COMMON_FILTERS,
            },
            "required": [
                "id_type",
                "id_value",
                "exch_code",
                "mic_code",
                "currency",
                "market_sector",
                "security_type",
                "security_type2",
                "include_unlisted_equities",
                "limit",
            ],
            "additionalProperties": False,
        },
    },
}


REFERENCE_DATA_TOOLS: list[ToolSpec] = [
    REFERENCE_SECURITY_SEARCH_TOOL,
    REFERENCE_IDENTIFIER_MAP_TOOL,
]


def build_reference_data_toolbox() -> ToolBox:
    return ToolBox(
        name="reference_data",
        tools=list(REFERENCE_DATA_TOOLS),
        tools_by_name=build_tool_index(REFERENCE_DATA_TOOLS),
    )


def build_reference_data_tool_mapping(
    service: ReferenceDataService | None,
) -> dict[str, Callable[..., ToolResult]]:
    return {
        "reference_security_search": partial(reference_security_search, service=service),
        "reference_identifier_map": partial(reference_identifier_map, service=service),
    }


@traceable(name="reference_security_search", run_type="tool")
def reference_security_search(
    *,
    query: str,
    exch_code: str | None = None,
    mic_code: str | None = None,
    currency: str | None = None,
    market_sector: str | None = None,
    security_type: str | None = None,
    security_type2: str | None = None,
    include_unlisted_equities: bool | None = None,
    limit: int = 10,
    service: ReferenceDataService | None = None,
) -> ToolResult:
    provider = _provider_name(service)
    set_trace_metadata(provider=provider, tool_name="reference_security_search")
    if service is None:
        return _reference_unavailable("reference_security_search")
    return service.search_security(
        query=query,
        exch_code=exch_code,
        mic_code=mic_code,
        currency=currency,
        market_sector=market_sector,
        security_type=security_type,
        security_type2=security_type2,
        include_unlisted_equities=include_unlisted_equities,
        limit=limit,
    )


@traceable(name="reference_identifier_map", run_type="tool")
def reference_identifier_map(
    *,
    id_type: str,
    id_value: str,
    exch_code: str | None = None,
    mic_code: str | None = None,
    currency: str | None = None,
    market_sector: str | None = None,
    security_type: str | None = None,
    security_type2: str | None = None,
    include_unlisted_equities: bool | None = None,
    limit: int = 10,
    service: ReferenceDataService | None = None,
) -> ToolResult:
    provider = _provider_name(service)
    set_trace_metadata(provider=provider, tool_name="reference_identifier_map")
    if service is None:
        return _reference_unavailable("reference_identifier_map")
    return service.map_identifier(
        id_type=id_type,
        id_value=id_value,
        exch_code=exch_code,
        mic_code=mic_code,
        currency=currency,
        market_sector=market_sector,
        security_type=security_type,
        security_type2=security_type2,
        include_unlisted_equities=include_unlisted_equities,
        limit=limit,
    )


def _reference_unavailable(tool_name: str) -> ToolResult:
    return ToolResult(
        status="error",
        output=f"{tool_name} is unavailable because reference data is not configured.",
        error=ToolError(
            message="Reference-data service is not configured.",
            code="reference_data_not_configured",
            hint="Set REFERENCE_DATA_PROVIDER=openfigi and restart the app.",
            retryable=False,
        ),
    )


def _provider_name(service: ReferenceDataService | None) -> str:
    return str(getattr(service, "provider_name", "reference_data") or "reference_data")
