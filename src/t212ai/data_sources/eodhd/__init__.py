"""EODHD symbol-reference integration."""

from .client import EODHD_BASE_URL, EodhdApiError, EodhdClient
from .models import (
    EodhdErrorContext,
    EodhdIdentifierRecord,
    EodhdIdMappingResult,
    EodhdSearchCandidate,
    EodhdSearchResult,
)
from .tools import (
    SYMBOL_REFERENCE_MAP_IDENTIFIERS_TOOL,
    SYMBOL_REFERENCE_SEARCH_TOOL,
    SYMBOL_REFERENCE_TOOLBOX,
    SYMBOL_REFERENCE_TOOLS,
    EodhdToolRuntime,
    build_eodhd_tool_mapping,
    symbol_reference_map_identifiers,
    symbol_reference_search,
)

__all__ = [
    "EODHD_BASE_URL",
    "SYMBOL_REFERENCE_MAP_IDENTIFIERS_TOOL",
    "SYMBOL_REFERENCE_SEARCH_TOOL",
    "SYMBOL_REFERENCE_TOOLBOX",
    "SYMBOL_REFERENCE_TOOLS",
    "EodhdApiError",
    "EodhdClient",
    "EodhdErrorContext",
    "EodhdIdentifierRecord",
    "EodhdIdMappingResult",
    "EodhdSearchCandidate",
    "EodhdSearchResult",
    "EodhdToolRuntime",
    "build_eodhd_tool_mapping",
    "symbol_reference_map_identifiers",
    "symbol_reference_search",
]
