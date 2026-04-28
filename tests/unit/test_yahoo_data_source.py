from __future__ import annotations

import json
import urllib.parse

from t212ai.data_sources.yahoo import (
    YahooFinanceClient,
    YahooOptionsResult,
    YahooPriceHistoryResult,
    YahooQuoteSnapshotResult,
    YahooQuoteSummaryResult,
    yahoo_analyst_snapshot,
    yahoo_market_snapshot,
    yahoo_options_snapshot,
    yahoo_quote_snapshot,
    yahoo_volume_monitor,
)
from t212ai.app.bootstrap import assess_settings
from t212ai.app.config import get_app_settings
from t212ai.genai.tools import (
    MARKET_DATA_TOOLBOX,
    YAHOO_MARKET_CONTEXT_TOOLBOX,
    build_market_data_toolbox,
)


class StubYahooClient(YahooFinanceClient):
    def __init__(self, payload_by_operation: dict[str, dict[str, object]]) -> None:
        super().__init__()
        self.payload_by_operation = payload_by_operation
        self.last_url: str | None = None

    def _read_json_url(self, url: str, *, operation: str) -> dict[str, object]:
        self.last_url = url
        return self.payload_by_operation[operation]


class FakeYahooClient:
    def get_quote_snapshot(self, symbols: list[str]) -> YahooQuoteSnapshotResult:
        return YahooQuoteSnapshotResult(
            quotes={
                symbol: {
                    "symbol": symbol,
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
            meta={"provider": "fake"},
        )

    def get_price_history(
        self,
        symbols: list[str],
        **_kwargs: object,
    ) -> YahooPriceHistoryResult:
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
            meta={"provider": "fake"},
        )

    def get_analyst_snapshot(self, symbol: str) -> YahooQuoteSummaryResult:
        return YahooQuoteSummaryResult(
            symbol=symbol,
            modules=["financialData", "recommendationTrend"],
            data={
                "financialData": {
                    "currentPrice": {"raw": 100},
                    "targetMeanPrice": {"raw": 120},
                    "targetLowPrice": {"raw": 80},
                    "targetHighPrice": {"raw": 150},
                    "recommendationKey": "buy",
                    "recommendationMean": {"raw": 2.0},
                },
                "recommendationTrend": {
                    "trend": [{"period": "0m", "buy": 10, "hold": 2}],
                },
                "upgradeDowngradeHistory": {"history": [{"firm": "Example"}]},
                "earningsTrend": {"trend": [{"period": "0q"}]},
            },
            meta={"provider": "fake"},
        )

    def get_options_chain(
        self,
        symbol: str,
        *,
        expiration: int | None,
    ) -> YahooOptionsResult:
        del expiration
        return YahooOptionsResult(
            symbol=symbol,
            expiration_dates=[1770000000],
            quote={"symbol": symbol},
            options=[
                {
                    "calls": [
                        {"contractSymbol": "LOW", "volume": 1, "openInterest": 1},
                        {"contractSymbol": "HIGH", "volume": 100, "openInterest": 10},
                    ],
                    "puts": [
                        {"contractSymbol": "PUT", "volume": 50, "openInterest": 5},
                    ],
                }
            ],
            meta={"provider": "fake"},
        )


def test_quote_snapshot_client_builds_query_and_reports_missing_symbols() -> None:
    client = StubYahooClient(
        {
            "quote": {
                "quoteResponse": {
                    "result": [{"symbol": "AAPL", "regularMarketPrice": 100}],
                    "error": None,
                }
            }
        }
    )

    result = client.get_quote_snapshot(["aapl", "missing"])
    query = urllib.parse.parse_qs(urllib.parse.urlparse(client.last_url or "").query)

    assert query["symbols"] == ["AAPL,MISSING"]
    assert "AAPL" in result.quotes
    assert result.errors["MISSING"]["code"] == "missing_quote"


def test_symbol_search_client_parses_quote_candidates() -> None:
    client = StubYahooClient(
        {
            "search": {
                "quotes": [{"symbol": "AAPL", "shortname": "Apple Inc."}],
                "news": [],
            }
        }
    )

    result = client.search_symbols("apple")

    assert result.query == "apple"
    assert result.quotes[0]["symbol"] == "AAPL"


def test_yahoo_quote_tool_returns_verbose_context() -> None:
    result = yahoo_quote_snapshot(
        tickers=["AAPL"],
        client=FakeYahooClient(),  # type: ignore[arg-type]
    )

    assert result.status == "ok"
    assert result.output is not None
    assert "informational/convenience" in result.output
    assert "price=100" in result.output


def test_yahoo_market_snapshot_combines_quotes_and_price_analytics() -> None:
    result = yahoo_market_snapshot(
        tickers=["AAPL"],
        period="1mo",
        interval="1d",
        start=None,
        end=None,
        auto_adjust=False,
        client=FakeYahooClient(),  # type: ignore[arg-type]
    )

    assert result.status == "ok"
    assert result.output is not None
    assert "Yahoo quote snapshot" in result.output
    assert "Yahoo price analytics" in result.output
    assert result.data["price_summary"]["AAPL"]["points"] == 2


def test_yahoo_volume_monitor_returns_relative_volume_context() -> None:
    result = yahoo_volume_monitor(
        tickers=["AAPL"],
        period="1mo",
        interval="1d",
        start=None,
        end=None,
        auto_adjust=False,
        client=FakeYahooClient(),  # type: ignore[arg-type]
    )

    assert result.status == "ok"
    assert result.output is not None
    assert "Yahoo volume monitor" in result.output
    assert "relative_volume=82.3x" in result.output
    assert result.data["monitor"]["AAPL"]["signal"] == "anomalous"


def test_yahoo_analyst_tool_returns_decision_caveat() -> None:
    result = yahoo_analyst_snapshot(
        symbol="AAPL",
        client=FakeYahooClient(),  # type: ignore[arg-type]
    )

    assert result.status == "ok"
    assert result.output is not None
    assert "target_mean=120" in result.output
    assert "not a standalone trade signal" in result.output


def test_yahoo_options_tool_limits_and_ranks_contracts() -> None:
    result = yahoo_options_snapshot(
        symbol="AAPL",
        expiration=None,
        max_contracts=1,
        client=FakeYahooClient(),  # type: ignore[arg-type]
    )

    assert result.status == "ok"
    calls = result.data["options"][0]["calls"]
    assert len(calls) == 1
    assert calls[0]["contractSymbol"] == "HIGH"


def test_market_data_toolbox_includes_yahoo_context_tools() -> None:
    names = MARKET_DATA_TOOLBOX.tools_by_name

    assert "yahoo_market_snapshot" in names
    assert "yahoo_analyst_snapshot" in names
    assert "yahoo_volume_monitor" in names


def test_yahoo_market_context_toolbox_includes_volume_monitor() -> None:
    names = YAHOO_MARKET_CONTEXT_TOOLBOX.tools_by_name

    assert "yahoo_volume_monitor" in names


def test_market_data_toolbox_hides_yahoo_tools_when_market_data_is_disabled() -> None:
    settings = get_app_settings(env={"MARKET_DATA_PROVIDER": "none", "YAHOO_ENABLED": "true"})
    toolbox = build_market_data_toolbox(
        settings=settings,
        assessment=assess_settings(settings),
    )

    assert toolbox.tools_by_name == {}
