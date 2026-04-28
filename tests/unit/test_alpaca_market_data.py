from __future__ import annotations

from t212ai.alpaca import AlpacaMarketDataClient
from t212ai.capabilities import AlpacaMarketDataService
from t212ai.genai.tools import (
    market_get_bars,
    market_get_chart_context,
    market_get_market_snapshot,
    market_get_quote,
    market_get_volume_monitor,
    market_search_symbol,
)


class StubAlpacaMarketDataClient(AlpacaMarketDataClient):
    def __init__(self, payload_by_path: dict[str, object]) -> None:
        super().__init__(api_key="alpaca-key", api_secret="alpaca-secret")
        self.payload_by_path = payload_by_path

    def _request_json(self, *, base_url: str, path: str, query=None):
        del base_url, query
        return self.payload_by_path[path]


def _service() -> AlpacaMarketDataService:
    client = StubAlpacaMarketDataClient(
        {
            "/v2/assets": [
                {
                    "symbol": "MSFT",
                    "name": "Microsoft Corporation",
                    "exchange": "NASDAQ",
                    "status": "active",
                    "tradable": True,
                    "class": "us_equity",
                },
                {
                    "symbol": "AAPL",
                    "name": "Apple Inc.",
                    "exchange": "NASDAQ",
                    "status": "active",
                    "tradable": True,
                    "class": "us_equity",
                },
            ],
            "/v2/stocks/snapshots": {
                "AAPL": {
                    "latestTrade": {"p": 100.0, "x": "IEX"},
                    "dailyBar": {"c": 100.0, "v": 2000},
                    "prevDailyBar": {"c": 98.0},
                }
            },
            "/v2/stocks/bars": {
                "bars": {
                    "AAPL": [
                        {
                            "t": "2026-01-01T00:00:00+00:00",
                            "o": 95,
                            "h": 101,
                            "l": 94,
                            "c": 98,
                            "v": 500,
                            "n": 10,
                            "vw": 97,
                        },
                        {
                            "t": "2026-01-02T00:00:00+00:00",
                            "o": 98,
                            "h": 102,
                            "l": 97,
                            "c": 100,
                            "v": 1000,
                            "n": 12,
                            "vw": 99,
                        },
                    ]
                }
            },
        }
    )
    return AlpacaMarketDataService(client)


def test_alpaca_client_search_symbols_ranks_exact_symbol_first() -> None:
    result = _service().search_symbols("aapl")

    assert result.meta["provider"] == "alpaca"
    assert result.candidates[0]["symbol"] == "AAPL"


def test_generic_market_tools_work_through_alpaca_service() -> None:
    service = _service()

    search = market_search_symbol(query="apple", service=service)
    quote = market_get_quote(symbols=["AAPL"], service=service)
    bars = market_get_bars(symbols=["AAPL"], service=service)
    snapshot = market_get_market_snapshot(symbols=["AAPL"], service=service)
    volume = market_get_volume_monitor(symbols=["AAPL"], service=service)
    chart = market_get_chart_context(symbols=["AAPL"], service=service)

    assert search.data["provider"] == "alpaca"
    assert search.data["candidates"][0]["symbol"] == "AAPL"
    assert quote.data["provider"] == "alpaca"
    assert quote.data["quotes"]["AAPL"]["price"] == 100.0
    assert bars.data["provider"] == "alpaca"
    assert bars.data["series"]["AAPL"][1]["close"] == 100
    assert snapshot.data["provider"] == "alpaca"
    assert snapshot.data["price_summary"]["AAPL"]["points"] == 2
    assert volume.data["provider"] == "alpaca"
    assert volume.data["monitor"]["AAPL"]["signal"] == "elevated"
    assert chart.data["provider"] == "alpaca"
    assert "AAPL" in chart.data["chart_refs"]
