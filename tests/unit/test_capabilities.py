from __future__ import annotations

from t212ai.brokers.trading212.service import Trading212BrokerService
from t212ai.capabilities import (
    AlphaVantageMarketIntelligenceService,
    BrokerExecutionService,
    BrokerReadService,
    CommunityResearchService,
    DisclosureService,
    EdgarDisclosureService,
    MarketDataService,
    MarketIntelligenceService,
    SearchService,
    SearxngSearchService,
    YahooMarketDataService,
)
from t212ai.data_sources.reddit import RedditResearchService
from t212ai.genai.models import ToolResult


class _FakeTrading212Api:
    def get_account_summary(self):
        return object()

    def list_positions(self, *, ticker: str | None = None):
        del ticker
        return []

    def list_pending_orders(self):
        return []

    def get_order(self, order_id: int):
        return {"id": order_id}

    def list_historical_orders(self, *, cursor=None, ticker=None, limit=None):
        del cursor, ticker, limit
        return []

    def place_market_order(self, request):
        return object()

    def place_limit_order(self, request):
        return object()

    def place_stop_order(self, request):
        return object()

    def place_stop_limit_order(self, request):
        return object()

    def cancel_order(self, order_id: int):
        del order_id


class _FakeYahooClient:
    def get_quote_snapshot(self, symbols: list[str]):
        return {"quotes": symbols}

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
        del period, interval, start, end, auto_adjust
        return {"series": symbols}

    def search_symbols(
        self,
        query: str,
        *,
        quotes_count: int = 8,
        news_count: int = 0,
    ):
        del quotes_count, news_count
        return {"query": query}


class _FakeAlphaClient:
    pass


class _FakeEdgarManager:
    def recent_ownership_activity(self, symbol: str, *, since_days: int = 30, limit: int = 10):
        return {"symbol": symbol, "kind": "ownership", "since_days": since_days, "limit": limit}

    def recent_major_stake_activity(
        self,
        symbol: str,
        *,
        since_days: int = 90,
        limit: int = 10,
    ):
        return {"symbol": symbol, "kind": "stake", "since_days": since_days, "limit": limit}

    def company_disclosure_snapshot(
        self,
        symbol: str,
        *,
        since_days: int = 30,
        limit: int = 12,
    ):
        return {"symbol": symbol, "kind": "snapshot", "since_days": since_days, "limit": limit}


def test_trading212_broker_service_satisfies_capability_protocols() -> None:
    service = Trading212BrokerService(_FakeTrading212Api())  # type: ignore[arg-type]

    assert isinstance(service, BrokerReadService)
    assert isinstance(service, BrokerExecutionService)


def test_yahoo_market_data_service_delegates_to_existing_helpers(monkeypatch) -> None:
    import t212ai.capabilities.services as capability_services

    market_snapshot_result = ToolResult(status="ok", output="market snapshot")
    volume_result = ToolResult(status="ok", output="volume monitor")
    chart_result = ToolResult(status="ok", output="chart context")
    monkeypatch.setattr(
        capability_services,
        "yahoo_market_snapshot",
        lambda **kwargs: market_snapshot_result,
    )
    monkeypatch.setattr(
        capability_services,
        "yahoo_volume_monitor",
        lambda **kwargs: volume_result,
    )
    monkeypatch.setattr(
        capability_services,
        "yahoo_price_summary_with_chart_refs",
        lambda **kwargs: chart_result,
    )
    service = YahooMarketDataService(_FakeYahooClient())  # type: ignore[arg-type]

    assert isinstance(service, MarketDataService)
    assert service.get_quote_snapshot(["AAPL"]) == {"quotes": ["AAPL"]}
    assert service.get_price_history(["AAPL"]) == {"series": ["AAPL"]}
    assert service.search_symbols("apple") == {"query": "apple"}
    assert service.get_market_snapshot(["AAPL"]) is market_snapshot_result
    assert service.get_volume_monitor(["AAPL"]) is volume_result
    assert service.get_chart_context(["AAPL"]) is chart_result


def test_alpha_vantage_market_intelligence_service_delegates_to_tool(monkeypatch) -> None:
    import t212ai.capabilities.services as capability_services

    expected = ToolResult(status="ok", output="most active")
    captured: dict[str, object] = {}

    def _fake_tool(*, entitlement, limit, runtime):
        captured["entitlement"] = entitlement
        captured["limit"] = limit
        captured["runtime_type"] = type(runtime).__name__
        return expected

    monkeypatch.setattr(capability_services, "alpha_vantage_most_actively_traded", _fake_tool)
    service = AlphaVantageMarketIntelligenceService(_FakeAlphaClient())  # type: ignore[arg-type]

    assert isinstance(service, MarketIntelligenceService)
    assert service.get_most_actively_traded(entitlement="delayed", limit=7) is expected
    assert captured == {
        "entitlement": "delayed",
        "limit": 7,
        "runtime_type": "AlphaVantageToolRuntime",
    }


def test_edgar_disclosure_service_satisfies_capability_protocol() -> None:
    service = EdgarDisclosureService(_FakeEdgarManager())  # type: ignore[arg-type]

    assert isinstance(service, DisclosureService)
    assert service.get_recent_ownership_activity("AAPL")["kind"] == "ownership"
    assert service.get_recent_major_stake_activity("AAPL")["kind"] == "stake"
    assert service.get_company_disclosure_snapshot("AAPL")["kind"] == "snapshot"


def test_reddit_research_service_satisfies_community_capability_protocol() -> None:
    service = RedditResearchService(object())  # type: ignore[arg-type]

    assert isinstance(service, CommunityResearchService)


def test_searxng_search_service_delegates_to_existing_helpers(monkeypatch) -> None:
    import t212ai.capabilities.services as capability_services

    expected_search = ToolResult(status="ok", output="search")
    expected_scrape = ToolResult(status="ok", output="scrape")
    captured: dict[str, object] = {}

    def _fake_search(**kwargs):
        captured["search"] = kwargs
        return expected_search

    def _fake_scrape(**kwargs):
        captured["scrape"] = kwargs
        return expected_scrape

    monkeypatch.setattr(capability_services, "searxng_search", _fake_search)
    monkeypatch.setattr(capability_services, "scrape_article", _fake_scrape)
    service = SearxngSearchService("http://searxng:8080")

    assert isinstance(service, SearchService)
    assert service.search(query="market", max_results=3) is expected_search
    assert service.scrape_article(url="https://example.com") is expected_scrape
    assert captured["search"]["base_url"] == "http://searxng:8080"
    assert captured["search"]["query"] == "market"
    assert captured["scrape"]["url"] == "https://example.com"
