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
)
__all__ = [
    "AlpacaMarketDataService",
    "AlphaVantageMarketIntelligenceService",
    "BrokerExecutionService",
    "BrokerReadService",
    "CapabilityBinding",
    "CommunityResearchService",
    "DisclosureService",
    "EdgarDisclosureService",
    "MarketDataService",
    "MarketPriceHistoryResult",
    "MarketQuoteSnapshotResult",
    "MarketSymbolSearchResult",
    "MarketIntelligenceService",
    "SearchService",
    "SearxngSearchService",
    "YahooMarketDataService",
]


def __getattr__(name: str):
    if name in {
        "AlpacaMarketDataService",
        "AlphaVantageMarketIntelligenceService",
        "EdgarDisclosureService",
        "SearxngSearchService",
        "YahooMarketDataService",
    }:
        from .services import (
            AlpacaMarketDataService,
            AlphaVantageMarketIntelligenceService,
            EdgarDisclosureService,
            SearxngSearchService,
            YahooMarketDataService,
        )

        return {
            "AlpacaMarketDataService": AlpacaMarketDataService,
            "AlphaVantageMarketIntelligenceService": AlphaVantageMarketIntelligenceService,
            "EdgarDisclosureService": EdgarDisclosureService,
            "SearxngSearchService": SearxngSearchService,
            "YahooMarketDataService": YahooMarketDataService,
        }[name]
    raise AttributeError(name)
