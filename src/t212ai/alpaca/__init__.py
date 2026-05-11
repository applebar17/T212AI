"""Shared Alpaca provider components."""

from __future__ import annotations

from .base import (
    ALPACA_LIVE_TRADING_BASE_URL,
    ALPACA_MARKET_DATA_BASE_URL,
    ALPACA_PAPER_TRADING_BASE_URL,
    ALPACA_STREAM_BASE_URL,
    ALPACA_STREAM_SANDBOX_BASE_URL,
    AlpacaApiError,
    AlpacaBaseClient,
)

__all__ = [
    "ALPACA_LIVE_TRADING_BASE_URL",
    "ALPACA_MARKET_DATA_BASE_URL",
    "ALPACA_PAPER_TRADING_BASE_URL",
    "ALPACA_STREAM_BASE_URL",
    "ALPACA_STREAM_SANDBOX_BASE_URL",
    "AlpacaApiError",
    "AlpacaBaseClient",
    "AlpacaBrokerClient",
    "AlpacaBrokerService",
    "AlpacaMarketDataClient",
    "AlpacaNewsEvent",
    "AlpacaStreamClient",
    "AlpacaStreamError",
    "AlpacaStreamEvent",
    "AlpacaStreamSubscription",
    "capture_alpaca_news_stream",
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
    if name in {
        "AlpacaNewsEvent",
        "AlpacaStreamClient",
        "AlpacaStreamError",
        "AlpacaStreamEvent",
        "AlpacaStreamSubscription",
        "capture_alpaca_news_stream",
    }:
        from .streaming import (
            AlpacaNewsEvent,
            AlpacaStreamClient,
            AlpacaStreamError,
            AlpacaStreamEvent,
            AlpacaStreamSubscription,
            capture_alpaca_news_stream,
        )

        return {
            "AlpacaNewsEvent": AlpacaNewsEvent,
            "AlpacaStreamClient": AlpacaStreamClient,
            "AlpacaStreamError": AlpacaStreamError,
            "AlpacaStreamEvent": AlpacaStreamEvent,
            "AlpacaStreamSubscription": AlpacaStreamSubscription,
            "capture_alpaca_news_stream": capture_alpaca_news_stream,
        }[name]
    raise AttributeError(name)
