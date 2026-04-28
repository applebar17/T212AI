"""Application-level capability interfaces."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from t212ai.brokers.trading212.models import (
    Order,
    OrderActionResult,
    OrderSide,
    OrderType,
    PaginatedResponseHistoricalOrder,
    PortfolioSnapshot,
    PreparedOrder,
    TimeValidity,
)
from t212ai.data_sources.reddit.models import (
    RedditDiscussionScanResult,
    RedditSearchResult,
    RedditSubredditSnapshot,
    RedditThreadDigest,
)
from t212ai.data_sources.sec_edgar.models import EdgarFilingActivityResult
from t212ai.data_sources.yahoo.models import (
    YahooPriceHistoryResult,
    YahooQuoteSnapshotResult,
    YahooSearchResult,
)
from t212ai.genai.models import ToolResult
from t212ai.genai.tools.search_registry import SearchResultRegistry


@runtime_checkable
class BrokerReadService(Protocol):
    def get_portfolio_snapshot(self) -> PortfolioSnapshot: ...

    def list_pending_orders(self) -> list[Order]: ...

    def get_order(self, order_id: int) -> Order: ...

    def list_historical_orders(
        self,
        *,
        cursor: str | int | None = None,
        ticker: str | None = None,
        limit: int | None = None,
    ) -> PaginatedResponseHistoricalOrder: ...


@runtime_checkable
class BrokerExecutionService(Protocol):
    def prepare_order(
        self,
        *,
        order_type: OrderType | str,
        side: OrderSide | str,
        ticker: str,
        quantity: str | int | float,
        limit_price: str | int | float | None = None,
        stop_price: str | int | float | None = None,
        time_validity: TimeValidity | str = TimeValidity.DAY,
        extended_hours: bool = False,
    ) -> PreparedOrder: ...

    def submit_prepared_order(self, prepared_order: PreparedOrder) -> OrderActionResult: ...

    def place_order(
        self,
        *,
        order_type: OrderType | str,
        side: OrderSide | str,
        ticker: str,
        quantity: str | int | float,
        limit_price: str | int | float | None = None,
        stop_price: str | int | float | None = None,
        time_validity: TimeValidity | str = TimeValidity.DAY,
        extended_hours: bool = False,
    ) -> OrderActionResult: ...

    def cancel_order(self, order_id: int) -> OrderActionResult: ...


@runtime_checkable
class MarketDataService(Protocol):
    def get_quote_snapshot(
        self,
        symbols: list[str],
    ) -> YahooQuoteSnapshotResult: ...

    def get_price_history(
        self,
        symbols: list[str],
        *,
        period: str = "1mo",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
        auto_adjust: bool = False,
    ) -> YahooPriceHistoryResult: ...

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
    ) -> YahooSearchResult: ...


@runtime_checkable
class MarketIntelligenceService(Protocol):
    def get_most_actively_traded(
        self,
        *,
        entitlement: str | None = None,
        limit: int = 20,
    ) -> ToolResult: ...


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

    def get_subreddit_snapshot(
        self,
        subreddit: str,
        *,
        listing: str = "hot",
        time: str | None = None,
        limit: int = 10,
    ) -> RedditSubredditSnapshot: ...

    def get_thread_digest(
        self,
        subreddit: str,
        post_id: str,
        *,
        comment_sort: str = "confidence",
        top_comment_limit: int = 8,
    ) -> RedditThreadDigest: ...

    def scan_company_discussion(
        self,
        ticker: str,
        *,
        company_name: str | None = None,
        subreddits: list[str] | None = None,
        time: str = "month",
        limit_per_subreddit: int = 5,
        max_results: int = 20,
    ) -> RedditDiscussionScanResult: ...


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
        runtime: SearchResultRegistry | None = None,
        timeout_seconds: float = 20.0,
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
