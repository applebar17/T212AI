"""Shared Alpaca provider components."""

from __future__ import annotations

from .base import (
    ALPACA_LIVE_TRADING_BASE_URL,
    ALPACA_MARKET_DATA_BASE_URL,
    ALPACA_PAPER_TRADING_BASE_URL,
    AlpacaApiError,
    AlpacaBaseClient,
)

__all__ = [
    "ALPACA_LIVE_TRADING_BASE_URL",
    "ALPACA_MARKET_DATA_BASE_URL",
    "ALPACA_PAPER_TRADING_BASE_URL",
    "AlpacaApiError",
    "AlpacaBaseClient",
    "AlpacaBrokerClient",
    "AlpacaBrokerService",
    "AlpacaMarketDataClient",
]


def __getattr__(name: str):
    if name == "AlpacaMarketDataClient":
        from .market_data import AlpacaMarketDataClient

        return AlpacaMarketDataClient
    if name in {"AlpacaBrokerClient", "AlpacaBrokerService"}:
        from .broker import AlpacaBrokerClient, AlpacaBrokerService

        return {
            "AlpacaBrokerClient": AlpacaBrokerClient,
            "AlpacaBrokerService": AlpacaBrokerService,
        }[name]
    raise AttributeError(name)
