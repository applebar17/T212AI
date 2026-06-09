"""Application-level capability interfaces."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from t212ai.brokers.models import (
    BrokerHistoricalOrdersPage,
    BrokerInstrumentResolution,
    BrokerInstrumentSnapshot,
    BrokerOrder,
    BrokerOrderActionResult,
    BrokerOrderSide,
    BrokerOrderType,
    BrokerPortfolioSnapshot,
    BrokerTimeInForce,
    PreparedBrokerOrder,
)
from t212ai.data_sources.reddit.models import (
    RedditSearchResult,
    RedditSubredditPostsResult,
    RedditThreadDigest,
)
from t212ai.data_sources.sec_edgar.models import EdgarFilingActivityResult
from t212ai.genai.models import ToolResult
from t212ai.genai.tools.search_registry import SearchResultRegistry

from .market_data_models import (
    MarketPriceHistoryResult,
    MarketQuoteSnapshotResult,
    MarketSymbolSearchResult,
)
from .symbol_reference_models import (
    SymbolIdentifierMappingResult,
    SymbolReferenceSearchResult,
)


@runtime_checkable
class BrokerReadService(Protocol):
    def get_portfolio_snapshot(self) -> BrokerPortfolioSnapshot: ...

    def list_pending_orders(self) -> list[BrokerOrder]: ...

    def get_order(self, order_ref: str) -> BrokerOrder: ...

    def list_historical_orders(
        self,
        *,
        cursor: str | int | None = None,
        ticker: str | None = None,
        limit: int | None = None,
    ) -> BrokerHistoricalOrdersPage: ...

    def resolve_instrument(
        self,
        query: str,
        *,
        limit: int = 8,
    ) -> BrokerInstrumentResolution: ...

    def get_instrument_snapshot(self, ticker: str) -> BrokerInstrumentSnapshot: ...


@runtime_checkable
class BrokerExecutionService(Protocol):
    def prepare_order(
        self,
        *,
        order_type: BrokerOrderType | str,
        side: BrokerOrderSide | str,
        ticker: str,
        quantity: str | int | float | None,
        notional_amount: str | int | float | None = None,
        notional_currency: str | None = None,
        limit_price: str | int | float | None = None,
        stop_price: str | int | float | None = None,
        time_in_force: BrokerTimeInForce | str = BrokerTimeInForce.DAY,
        extended_hours: bool = False,
    ) -> PreparedBrokerOrder: ...

    def submit_prepared_order(
        self,
        prepared_order: PreparedBrokerOrder,
    ) -> BrokerOrderActionResult: ...

    def place_order(
        self,
        *,
        order_type: BrokerOrderType | str,
        side: BrokerOrderSide | str,
        ticker: str,
        quantity: str | int | float | None,
        notional_amount: str | int | float | None = None,
        notional_currency: str | None = None,
        limit_price: str | int | float | None = None,
        stop_price: str | int | float | None = None,
        time_in_force: BrokerTimeInForce | str = BrokerTimeInForce.DAY,
        extended_hours: bool = False,
    ) -> BrokerOrderActionResult: ...

    def cancel_order(self, order_ref: str) -> BrokerOrderActionResult: ...


@runtime_checkable
class MarketDataService(Protocol):
    def get_quote_snapshot(
        self,
        symbols: list[str],
    ) -> MarketQuoteSnapshotResult: ...

    def get_price_history(
        self,
        symbols: list[str],
        *,
        period: str = "1mo",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
        auto_adjust: bool = False,
    ) -> MarketPriceHistoryResult: ...

    def get_market_snapshot(
        self,
        symbols: list[str] | tuple[str, ...],
        *,
        period: str = "1mo",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
        auto_adjust: bool = False,
    ) -> ToolResult: ...

    def get_volume_monitor(
        self,
        symbols: list[str] | tuple[str, ...],
        *,
        period: str = "1mo",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
        auto_adjust: bool = False,
    ) -> ToolResult: ...

    def search_symbols(
        self,
        query: str,
        *,
        quotes_count: int = 8,
        news_count: int = 0,
    ) -> MarketSymbolSearchResult: ...

    def get_chart_context(
        self,
        symbols: list[str] | tuple[str, ...],
        *,
        period: str = "1mo",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
        auto_adjust: bool = False,
    ) -> ToolResult: ...


@runtime_checkable
class MarketIntelligenceService(Protocol):
    def get_most_actively_traded(
        self,
        *,
        entitlement: str | None = None,
        limit: int = 20,
    ) -> ToolResult: ...


@runtime_checkable
class SymbolReferenceService(Protocol):
    def search(
        self,
        query: str,
        *,
        limit: int = 15,
        asset_type: str = "all",
        exchange: str | None = None,
        bonds_only: bool = False,
    ) -> SymbolReferenceSearchResult: ...

    def map_identifiers(
        self,
        *,
        symbol: str | None = None,
        exchange: str | None = None,
        isin: str | None = None,
        figi: str | None = None,
        lei: str | None = None,
        cusip: str | None = None,
        cik: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> SymbolIdentifierMappingResult: ...


@runtime_checkable
class DisclosureService(Protocol):
    def get_recent_ownership_activity(
        self,
        symbol: str,
        *,
        since_days: int = 30,
        limit: int = 10,
    ) -> EdgarFilingActivityResult: ...

    def get_recent_major_stake_activity(
        self,
        symbol: str,
        *,
        since_days: int = 90,
        limit: int = 10,
    ) -> EdgarFilingActivityResult: ...

    def get_company_disclosure_snapshot(
        self,
        symbol: str,
        *,
        since_days: int = 30,
        limit: int = 12,
    ) -> EdgarFilingActivityResult: ...


@runtime_checkable
class CommunityResearchService(Protocol):
    def search_posts(
        self,
        query: str,
        *,
        subreddit: str | None = None,
        sort: str = "relevance",
        time: str = "month",
        limit: int = 10,
        after: str | None = None,
    ) -> RedditSearchResult: ...

    def get_subreddit_posts(
        self,
        subreddit: str,
        *,
        sort: str = "hot",
        time: str | None = None,
        limit: int = 10,
        after: str | None = None,
    ) -> RedditSubredditPostsResult: ...

    def get_thread_digest(
        self,
        subreddit: str,
        post_id: str,
        *,
        comment_sort: str = "confidence",
        top_comment_limit: int = 8,
    ) -> RedditThreadDigest: ...

@runtime_checkable
class SearchService(Protocol):
    def search(
        self,
        *,
        query: str,
        categories: str | None = None,
        language: str = "en",
        time_range: str | None = None,
        max_results: int = 8,
        scrape_results: bool = False,
        scrape_top_n: int = 3,
        scrape_timeout_seconds: float = 8.0,
        include_scraped_text: bool = False,
        include_scraped_images: bool = False,
        runtime: SearchResultRegistry | None = None,
        timeout_seconds: float = 20.0,
    ) -> ToolResult: ...

    def scrape_page(
        self,
        *,
        url: str | None = None,
        url_id: str | None = None,
        include_images: bool = True,
        max_images: int = 5,
        timeout_seconds: float = 20.0,
        runtime: SearchResultRegistry | None = None,
    ) -> ToolResult: ...

    def scrape_article(
        self,
        *,
        url: str | None = None,
        url_id: str | None = None,
        include_images: bool = True,
        max_images: int = 5,
        timeout_seconds: float = 20.0,
        runtime: SearchResultRegistry | None = None,
    ) -> ToolResult: ...
