"""Thin capability adapters over existing provider implementations."""

from __future__ import annotations

from dataclasses import dataclass

from t212ai.data_sources.alpha_vantage import (
    AlphaVantageClient,
    AlphaVantageToolRuntime,
    alpha_vantage_most_actively_traded,
)
from t212ai.data_sources.sec_edgar import EdgarInsiderManager
from t212ai.data_sources.yahoo import (
    YahooFinanceClient,
    yahoo_market_snapshot,
    yahoo_volume_monitor,
)
from t212ai.genai.models import ToolResult
from t212ai.genai.tools.scrape_article import scrape_article
from t212ai.genai.tools.search_registry import SearchResultRegistry
from t212ai.genai.tools.searxng import searxng_search


@dataclass(slots=True)
class YahooMarketDataService:
    client: YahooFinanceClient

    def get_quote_snapshot(self, symbols: list[str]):
        return self.client.get_quote_snapshot(symbols)

    def get_price_history(
        self,
        symbols: list[str],
        *,
        period: str = "1mo",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
        auto_adjust: bool = False,
    ):
        return self.client.get_price_history(
            symbols,
            period=period,
            interval=interval,
            start=start,
            end=end,
            auto_adjust=auto_adjust,
        )

    def get_market_snapshot(
        self,
        symbols: list[str] | tuple[str, ...],
        *,
        period: str = "1mo",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
        auto_adjust: bool = False,
    ) -> ToolResult:
        return yahoo_market_snapshot(
            tickers=symbols,
            period=period,
            interval=interval,
            start=start,
            end=end,
            auto_adjust=auto_adjust,
            client=self.client,
        )

    def get_volume_monitor(
        self,
        symbols: list[str] | tuple[str, ...],
        *,
        period: str = "1mo",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
        auto_adjust: bool = False,
    ) -> ToolResult:
        return yahoo_volume_monitor(
            tickers=symbols,
            period=period,
            interval=interval,
            start=start,
            end=end,
            auto_adjust=auto_adjust,
            client=self.client,
        )

    def search_symbols(
        self,
        query: str,
        *,
        quotes_count: int = 8,
        news_count: int = 0,
    ):
        return self.client.search_symbols(
            query,
            quotes_count=quotes_count,
            news_count=news_count,
        )


@dataclass(slots=True)
class AlphaVantageMarketIntelligenceService:
    client: AlphaVantageClient

    def get_most_actively_traded(
        self,
        *,
        entitlement: str | None = None,
        limit: int = 20,
    ) -> ToolResult:
        return alpha_vantage_most_actively_traded(
            entitlement=entitlement,
            limit=limit,
            runtime=AlphaVantageToolRuntime(client=self.client),
        )


@dataclass(slots=True)
class EdgarDisclosureService:
    manager: EdgarInsiderManager

    def get_recent_ownership_activity(
        self,
        symbol: str,
        *,
        since_days: int = 30,
        limit: int = 10,
    ):
        return self.manager.recent_ownership_activity(
            symbol,
            since_days=since_days,
            limit=limit,
        )

    def get_recent_major_stake_activity(
        self,
        symbol: str,
        *,
        since_days: int = 90,
        limit: int = 10,
    ):
        return self.manager.recent_major_stake_activity(
            symbol,
            since_days=since_days,
            limit=limit,
        )

    def get_company_disclosure_snapshot(
        self,
        symbol: str,
        *,
        since_days: int = 30,
        limit: int = 12,
    ):
        return self.manager.company_disclosure_snapshot(
            symbol,
            since_days=since_days,
            limit=limit,
        )


@dataclass(slots=True)
class SearxngSearchService:
    base_url: str

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
    ) -> ToolResult:
        return searxng_search(
            query=query,
            categories=categories,
            language=language,
            time_range=time_range,
            max_results=max_results,
            base_url=self.base_url,
            runtime=runtime,
            timeout_seconds=timeout_seconds,
        )

    def scrape_article(
        self,
        *,
        url: str | None = None,
        url_id: str | None = None,
        include_images: bool = True,
        max_images: int = 5,
        timeout_seconds: float = 20.0,
        runtime: SearchResultRegistry | None = None,
    ) -> ToolResult:
        return scrape_article(
            url=url,
            url_id=url_id,
            include_images=include_images,
            max_images=max_images,
            timeout_seconds=timeout_seconds,
            runtime=runtime,
        )
