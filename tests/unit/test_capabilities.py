from __future__ import annotations

from t212ai.alpaca.broker import AlpacaBrokerService
from t212ai.brokers.trading212.service import Trading212BrokerService
from t212ai.capabilities import (
    AlpacaMarketDataService,
    AlphaVantageMarketIntelligenceService,
    BrokerExecutionService,
    BrokerReadService,
    CommunityResearchService,
    DisclosureService,
    EodhdSymbolReferenceService,
    EdgarDisclosureService,
    MarketDataService,
    MarketIntelligenceService,
    SearchService,
    SearxngSearchService,
    SymbolReferenceService,
    YahooMarketDataService,
)
from t212ai.data_sources.eodhd.models import (
    EodhdIdentifierRecord,
    EodhdIdMappingResult,
    EodhdSearchCandidate,
    EodhdSearchResult,
)
from t212ai.capabilities.market_data_models import (
    MarketPriceHistoryResult,
    MarketQuoteSnapshotResult,
    MarketSymbolSearchResult,
)
from t212ai.data_sources.reddit import RedditResearchService
from t212ai.data_sources.yahoo.models import (
    YahooPriceHistoryResult,
    YahooQuoteSnapshotResult,
    YahooSearchResult,
)
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
    def get_quote_snapshot(self, symbols: list[str]) -> YahooQuoteSnapshotResult:
        return YahooQuoteSnapshotResult(
            quotes={
                symbol: {
                    "shortName": f"{symbol} Inc.",
                    "regularMarketPrice": 100.0,
                    "regularMarketChangePercent": 2.5,
                    "regularMarketVolume": 123456,
                    "marketCap": 1000000,
                    "currency": "USD",
                    "fullExchangeName": "NasdaqGS",
                    "marketState": "REGULAR",
                }
                for symbol in symbols
            },
            errors={},
            meta={"source": "fake"},
        )

    def get_price_history(
        self,
        symbols: list[str],
        *,
        period: str = "1mo",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
        auto_adjust: bool = False,
    ) -> YahooPriceHistoryResult:
        del period, interval, start, end, auto_adjust
        return YahooPriceHistoryResult(
            series={
                symbol: [
                    {
                        "timestamp": "2026-01-01T00:00:00Z",
                        "open": 90,
                        "high": 101,
                        "low": 89,
                        "close": 100,
                        "volume": 1000,
                    },
                    {
                        "timestamp": "2026-01-02T00:00:00Z",
                        "open": 100,
                        "high": 111,
                        "low": 99,
                        "close": 110,
                        "volume": 2000,
                    },
                ]
                for symbol in symbols
            },
            errors={},
            meta={"source": "fake"},
        )

    def search_symbols(
        self,
        query: str,
        *,
        quotes_count: int = 8,
        news_count: int = 0,
    ) -> YahooSearchResult:
        del quotes_count, news_count
        return YahooSearchResult(
            query=query,
            quotes=[
                {
                    "symbol": "AAPL",
                    "shortname": "Apple Inc.",
                    "exchDisp": "NasdaqGS",
                    "quoteType": "EQUITY",
                }
            ],
            news=[],
            meta={"source": "fake"},
        )


class _FakeAlpacaClient:
    def get_quote_snapshot(self, symbols: list[str]) -> MarketQuoteSnapshotResult:
        return MarketQuoteSnapshotResult(
            quotes={
                symbol: {
                    "symbol": symbol,
                    "name": None,
                    "price": 101.0,
                    "change_pct": 1.25,
                    "volume": 777.0,
                    "currency": "USD",
                    "exchange": "IEX",
                    "market_state": None,
                }
                for symbol in symbols
            },
            errors={},
            meta={"provider": "alpaca", "feed": "iex"},
        )

    def get_price_history(
        self,
        symbols: list[str],
        *,
        period: str = "1mo",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
        auto_adjust: bool = False,
    ) -> MarketPriceHistoryResult:
        del period, interval, start, end, auto_adjust
        return MarketPriceHistoryResult(
            series={
                symbol: [
                    {
                        "timestamp": "2026-01-01T00:00:00Z",
                        "open": 95,
                        "high": 102,
                        "low": 94,
                        "close": 100,
                        "volume": 500,
                    },
                    {
                        "timestamp": "2026-01-02T00:00:00Z",
                        "open": 100,
                        "high": 104,
                        "low": 99,
                        "close": 101,
                        "volume": 1000,
                    },
                ]
                for symbol in symbols
            },
            errors={},
            meta={"provider": "alpaca", "feed": "iex"},
        )

    def search_symbols(
        self,
        query: str,
        *,
        quotes_count: int = 8,
        news_count: int = 0,
    ) -> MarketSymbolSearchResult:
        del quotes_count, news_count
        return MarketSymbolSearchResult(
            query=query,
            candidates=[
                {
                    "symbol": "AAPL",
                    "name": "Apple Inc.",
                    "exchange": "NASDAQ",
                    "asset_class": "us_equity",
                    "status": "active",
                    "tradable": True,
                }
            ],
            meta={"provider": "alpaca"},
        )


class _FakeAlpacaBrokerClient:
    def get_account(self):
        return {
            "account_number": "PA123",
            "currency": "USD",
            "buying_power": "1000",
            "portfolio_value": "1200",
        }

    def list_positions(self):
        return []

    def list_orders(
        self,
        *,
        status: str,
        limit: int | None = None,
        ticker: str | None = None,
        cursor=None,
    ):
        del status, limit, ticker, cursor
        return []

    def get_order(self, order_ref: str):
        return {
            "id": order_ref,
            "symbol": "AAPL",
            "qty": "1",
            "side": "buy",
            "status": "new",
            "type": "market",
            "time_in_force": "day",
        }

    def place_order(self, payload):
        return {
            "id": "alpaca-order-1",
            "symbol": payload["symbol"],
            "qty": payload["qty"],
            "side": payload["side"],
            "status": "accepted",
            "type": payload["type"],
            "time_in_force": payload["time_in_force"],
        }

    def cancel_order(self, order_ref: str):
        del order_ref


class _FakeAlphaClient:
    pass


class _FakeEodhdClient:
    def search(self, query: str, **_kwargs):
        return EodhdSearchResult(
            query=query,
            candidates=[
                EodhdSearchCandidate(
                    code="AAPL",
                    exchange="US",
                    provider_symbol="AAPL.US",
                    name="Apple Inc.",
                    isin="US0378331005",
                )
            ],
            request_params={"fmt": "json"},
        )

    def id_mapping(self, **_kwargs):
        return EodhdIdMappingResult(
            records=[
                EodhdIdentifierRecord(
                    provider_symbol="AAPL.US",
                    isin="US0378331005",
                    cusip="037833100",
                )
            ],
            total=1,
            limit=100,
            offset=0,
            request_params={"fmt": "json"},
        )


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


def test_alpaca_broker_service_satisfies_capability_protocols() -> None:
    service = AlpacaBrokerService(_FakeAlpacaBrokerClient())  # type: ignore[arg-type]

    assert isinstance(service, BrokerReadService)
    assert isinstance(service, BrokerExecutionService)


def test_yahoo_market_data_service_returns_provider_neutral_contract() -> None:
    service = YahooMarketDataService(_FakeYahooClient())  # type: ignore[arg-type]

    assert isinstance(service, MarketDataService)
    quotes = service.get_quote_snapshot(["AAPL"])
    history = service.get_price_history(["AAPL"])
    search = service.search_symbols("apple")
    snapshot = service.get_market_snapshot(["AAPL"])
    volume = service.get_volume_monitor(["AAPL"])
    chart = service.get_chart_context(["AAPL"])

    assert quotes.meta["provider"] == "yahoo"
    assert quotes.quotes["AAPL"]["price"] == 100.0
    assert history.series["AAPL"][0]["close"] == 100
    assert search.candidates[0]["symbol"] == "AAPL"
    assert snapshot.data["quotes"]["AAPL"]["volume"] == 123456.0
    assert volume.data["monitor"]["AAPL"]["signal"] == "anomalous"
    assert chart.data["summary"]["AAPL"]["points"] == 2


def test_alpaca_market_data_service_satisfies_same_capability_contract() -> None:
    service = AlpacaMarketDataService(_FakeAlpacaClient())  # type: ignore[arg-type]

    assert isinstance(service, MarketDataService)
    quotes = service.get_quote_snapshot(["AAPL"])
    history = service.get_price_history(["AAPL"])
    search = service.search_symbols("apple")
    snapshot = service.get_market_snapshot(["AAPL"])
    volume = service.get_volume_monitor(["AAPL"])
    chart = service.get_chart_context(["AAPL"])

    assert quotes.meta["provider"] == "alpaca"
    assert quotes.quotes["AAPL"]["price"] == 101.0
    assert history.series["AAPL"][1]["close"] == 101
    assert search.candidates[0]["symbol"] == "AAPL"
    assert snapshot.data["quotes"]["AAPL"]["volume"] == 777.0
    assert volume.data["monitor"]["AAPL"]["signal"] == "normal"
    assert chart.data["summary"]["AAPL"]["points"] == 2


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


def test_eodhd_symbol_reference_service_satisfies_capability_protocol() -> None:
    service = EodhdSymbolReferenceService(_FakeEodhdClient())  # type: ignore[arg-type]

    assert isinstance(service, SymbolReferenceService)
    search = service.search("apple")
    mapping = service.map_identifiers(isin="US0378331005")
    assert search.candidates[0]["provider_symbol"] == "AAPL.US"
    assert search.meta["authority"] == "reference_data_only"
    assert mapping.records[0]["cusip"] == "037833100"


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
    expected_scrape_page = ToolResult(status="ok", output="scrape-page")
    expected_scrape = ToolResult(status="ok", output="scrape")
    captured: dict[str, object] = {}

    def _fake_search(**kwargs):
        captured["search"] = kwargs
        return expected_search

    def _fake_scrape(**kwargs):
        captured["scrape"] = kwargs
        return expected_scrape

    def _fake_scrape_page(**kwargs):
        captured["scrape_page"] = kwargs
        return expected_scrape_page

    monkeypatch.setattr(capability_services, "searxng_search", _fake_search)
    monkeypatch.setattr(capability_services, "scrape_article", _fake_scrape)
    monkeypatch.setattr(capability_services, "scrape_page", _fake_scrape_page)
    service = SearxngSearchService("http://searxng:8080")

    assert isinstance(service, SearchService)
    assert (
        service.search(query="market", max_results=3, scrape_results=True, scrape_top_n=2)
        is expected_search
    )
    assert service.scrape_page(url="https://example.com/page") is expected_scrape_page
    assert service.scrape_article(url="https://example.com") is expected_scrape
    assert captured["search"]["base_url"] == "http://searxng:8080"
    assert captured["search"]["query"] == "market"
    assert captured["search"]["scrape_results"] is True
    assert captured["search"]["scrape_top_n"] == 2
    assert captured["scrape_page"]["url"] == "https://example.com/page"
    assert captured["scrape"]["url"] == "https://example.com"
