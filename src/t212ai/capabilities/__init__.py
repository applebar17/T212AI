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
from .services import (
    AlpacaMarketDataService,
    AlphaVantageMarketIntelligenceService,
    EdgarDisclosureService,
    SearxngSearchService,
    YahooMarketDataService,
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
