"""Capability interfaces and thin provider adapters."""

from .market_data_models import (
    MarketPriceHistoryResult,
    MarketQuoteSnapshotResult,
    MarketSymbolSearchResult,
)
from .models import CapabilityBinding
from .protocols import (
    BrokerExecutionService,
    BrokerReadService,
    CommunityResearchService,
    DisclosureService,
    MarketDataService,
    MarketIntelligenceService,
    SearchService,
    SymbolReferenceService,
)
from .symbol_reference_models import (
    SymbolIdentifierMappingResult,
    SymbolReferenceSearchResult,
)
__all__ = [
    "AlpacaMarketDataService",
    "AlphaVantageMarketIntelligenceService",
    "BrokerExecutionService",
    "BrokerReadService",
    "CapabilityBinding",
    "CommunityResearchService",
    "DisclosureService",
    "EodhdSymbolReferenceService",
    "EdgarDisclosureService",
    "MarketDataService",
    "MarketPriceHistoryResult",
    "MarketQuoteSnapshotResult",
    "MarketSymbolSearchResult",
    "MarketIntelligenceService",
    "SearchService",
    "SearxngSearchService",
    "SymbolIdentifierMappingResult",
    "SymbolReferenceSearchResult",
    "SymbolReferenceService",
    "YahooMarketDataService",
]


def __getattr__(name: str):
    if name in {
        "AlpacaMarketDataService",
        "AlphaVantageMarketIntelligenceService",
        "EodhdSymbolReferenceService",
        "EdgarDisclosureService",
        "SearxngSearchService",
        "YahooMarketDataService",
    }:
        from .services import (
            AlpacaMarketDataService,
            AlphaVantageMarketIntelligenceService,
            EodhdSymbolReferenceService,
            EdgarDisclosureService,
            SearxngSearchService,
            YahooMarketDataService,
        )

        return {
            "AlpacaMarketDataService": AlpacaMarketDataService,
            "AlphaVantageMarketIntelligenceService": AlphaVantageMarketIntelligenceService,
            "EodhdSymbolReferenceService": EodhdSymbolReferenceService,
            "EdgarDisclosureService": EdgarDisclosureService,
            "SearxngSearchService": SearxngSearchService,
            "YahooMarketDataService": YahooMarketDataService,
        }[name]
    raise AttributeError(name)
