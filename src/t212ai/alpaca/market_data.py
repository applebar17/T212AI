"""Alpaca market-data client."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any

from t212ai.capabilities.market_data_models import (
    MarketPriceHistoryResult,
    MarketQuoteSnapshotResult,
    MarketSymbolSearchResult,
)

from .base import AlpacaApiError, AlpacaBaseClient


class AlpacaMarketDataClient(AlpacaBaseClient):
    provider_name = "alpaca"

    def stream_client(self):
        from .streaming import AlpacaStreamClient

        return AlpacaStreamClient.from_client(self)

    def news_stream_url(self, *, sandbox: bool = False) -> str:
        return self.stream_client().news_stream_url(sandbox=sandbox)

    def stock_stream_url(
        self,
        *,
        feed: str | None = None,
        sandbox: bool = False,
    ) -> str:
        return self.stream_client().stock_stream_url(feed=feed, sandbox=sandbox)

    def test_stream_url(self, *, sandbox: bool = False) -> str:
        return self.stream_client().test_stream_url(sandbox=sandbox)

    async def stream_news(
        self,
        *,
        sandbox: bool = False,
        raise_on_error: bool = True,
    ) -> AsyncIterator[Any]:
        from .streaming import AlpacaStreamSubscription

        async for event in self.stream_client().connect_and_subscribe(
            AlpacaStreamSubscription.news_all(),
            stream="news",
            sandbox=sandbox,
            raise_on_error=raise_on_error,
        ):
            yield event

    def search_symbols(
        self,
        query: str,
        *,
        quotes_count: int = 8,
        news_count: int = 0,
    ) -> MarketSymbolSearchResult:
        del news_count
        resolved_query = str(query or "").strip()
        if not resolved_query:
            raise ValueError("query is required.")
        payload = self._request_json(
            base_url=self.trading_base_url,
            path="/v2/assets",
            query={"status": "active", "asset_class": "us_equity"},
        )
        if not isinstance(payload, list):
            raise AlpacaApiError("Alpaca assets endpoint returned an unexpected payload.")
        candidates = _rank_asset_candidates(payload, query=resolved_query)[: max(1, quotes_count)]
        return MarketSymbolSearchResult(
            query=resolved_query,
            candidates=candidates,
            meta={"provider": self.provider_name},
        )

    def get_quote_snapshot(self, symbols: list[str]) -> MarketQuoteSnapshotResult:
        cleaned = _clean_symbols(symbols)
        if not cleaned:
            raise ValueError("At least one symbol is required.")
        payload = self._request_json(
            base_url=self.market_data_base_url.rstrip("/"),
            path="/v2/stocks/snapshots",
            query={"symbols": ",".join(cleaned), "feed": self.data_feed},
        )
        if not isinstance(payload, dict):
            raise AlpacaApiError("Alpaca snapshots endpoint returned an unexpected payload.")
        quotes: dict[str, dict[str, Any]] = {}
        errors: dict[str, dict[str, Any]] = {}
        for symbol in cleaned:
            snapshot = payload.get(symbol) or {}
            if not isinstance(snapshot, dict) or not snapshot:
                errors[symbol] = {
                    "code": "missing_quote",
                    "message": "Alpaca did not return a snapshot for this symbol.",
                    "retryable": False,
                }
                continue
            quotes[symbol] = _snapshot_to_quote(symbol, snapshot)
        return MarketQuoteSnapshotResult(
            quotes=quotes,
            errors=errors,
            meta={"provider": self.provider_name, "feed": self.data_feed},
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
        cleaned = _clean_symbols(symbols)
        if not cleaned:
            raise ValueError("At least one symbol is required.")
        timeframe = _resolve_timeframe(interval)
        start_dt, end_dt = _resolve_time_range(period=period, start=start, end=end)
        payload = self._request_json(
            base_url=self.market_data_base_url.rstrip("/"),
            path="/v2/stocks/bars",
            query={
                "symbols": ",".join(cleaned),
                "timeframe": timeframe,
                "start": start_dt.isoformat().replace("+00:00", "Z"),
                "end": end_dt.isoformat().replace("+00:00", "Z"),
                "adjustment": "all" if auto_adjust else "raw",
                "feed": self.data_feed,
                "sort": "asc",
            },
        )
        if not isinstance(payload, dict):
            raise AlpacaApiError("Alpaca bars endpoint returned an unexpected payload.")
        raw_bars = payload.get("bars") or {}
        if not isinstance(raw_bars, dict):
            raise AlpacaApiError("Alpaca bars payload is missing the bars map.")
        series: dict[str, list[dict[str, Any]]] = {}
        errors: dict[str, dict[str, Any]] = {}
        for symbol in cleaned:
            bars = raw_bars.get(symbol)
            if not isinstance(bars, list) or not bars:
                errors[symbol] = {
                    "code": "missing_bars",
                    "message": "Alpaca did not return bars for this symbol.",
                    "retryable": False,
                }
                continue
            series[symbol] = [_bar_to_point(bar) for bar in bars if isinstance(bar, dict)]
        return MarketPriceHistoryResult(
            series=series,
            errors=errors,
            meta={
                "provider": self.provider_name,
                "feed": self.data_feed,
                "period": period,
                "interval": interval,
                "start": start_dt.isoformat().replace("+00:00", "Z"),
                "end": end_dt.isoformat().replace("+00:00", "Z"),
                "auto_adjust": bool(auto_adjust),
            },
        )


def _clean_symbols(values: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in values:
        symbol = str(raw).strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        cleaned.append(symbol)
    return cleaned


def _rank_asset_candidates(
    assets: list[dict[str, Any]],
    *,
    query: str,
) -> list[dict[str, Any]]:
    needle = query.strip().lower()
    ranked: list[tuple[tuple[int, str, str], dict[str, Any]]] = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        if not asset.get("tradable", True):
            continue
        symbol = str(asset.get("symbol") or "").strip().upper()
        name = str(asset.get("name") or "").strip()
        if not symbol:
            continue
        symbol_lower = symbol.lower()
        name_lower = name.lower()
        if needle not in symbol_lower and needle not in name_lower:
            continue
        exact_symbol = 0 if symbol_lower == needle else 1
        prefix_symbol = 0 if symbol_lower.startswith(needle) else 1
        exact_name = 0 if name_lower == needle else 1
        name_contains = 0 if needle in name_lower else 1
        ranked.append(
            (
                (exact_symbol, prefix_symbol, exact_name, name_contains, symbol, name),
                {
                    "symbol": symbol,
                    "name": name or None,
                    "exchange": asset.get("exchange"),
                    "asset_class": asset.get("class") or asset.get("asset_class"),
                    "status": asset.get("status"),
                    "tradable": bool(asset.get("tradable", True)),
                    "raw": asset,
                },
            )
        )
    ranked.sort(key=lambda item: item[0])
    return [candidate for _, candidate in ranked]


def _snapshot_to_quote(symbol: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    latest_trade = snapshot.get("latestTrade") or {}
    daily_bar = snapshot.get("dailyBar") or {}
    prev_daily_bar = snapshot.get("prevDailyBar") or {}
    price = _first_number(
        latest_trade.get("p"),
        daily_bar.get("c"),
        prev_daily_bar.get("c"),
    )
    prev_close = _first_number(prev_daily_bar.get("c"))
    change_pct = None
    if price is not None and prev_close not in {None, 0}:
        change_pct = ((price - prev_close) / prev_close) * 100.0
    return {
        "symbol": symbol,
        "name": None,
        "price": _round_number(price),
        "change_pct": _round_number(change_pct),
        "volume": _round_number(_first_number(daily_bar.get("v"), latest_trade.get("s"))),
        "currency": "USD",
        "exchange": latest_trade.get("x"),
        "market_state": None,
        "raw": snapshot,
    }


def _bar_to_point(bar: dict[str, Any]) -> dict[str, Any]:
    timestamp = str(bar.get("t") or "").strip()
    if timestamp.endswith("+00:00"):
        timestamp = timestamp.removesuffix("+00:00") + "Z"
    return {
        "timestamp": timestamp or None,
        "open": _round_number(_to_float(bar.get("o"))),
        "high": _round_number(_to_float(bar.get("h"))),
        "low": _round_number(_to_float(bar.get("l"))),
        "close": _round_number(_to_float(bar.get("c"))),
        "volume": _round_number(_to_float(bar.get("v"))),
        "trade_count": _round_number(_to_float(bar.get("n"))),
        "vwap": _round_number(_to_float(bar.get("vw"))),
    }


def _resolve_timeframe(interval: str) -> str:
    mapping = {
        "1m": "1Min",
        "5m": "5Min",
        "15m": "15Min",
        "30m": "30Min",
        "1h": "1Hour",
        "1d": "1Day",
        "1wk": "1Week",
        "1mo": "1Month",
    }
    key = str(interval or "1d").strip().lower()
    if key not in mapping:
        raise ValueError(f"Unsupported Alpaca interval '{interval}'.")
    return mapping[key]


def _resolve_time_range(
    *,
    period: str,
    start: str | None,
    end: str | None,
) -> tuple[datetime, datetime]:
    if start or end:
        start_dt = _parse_date(start) if start else datetime(1970, 1, 1, tzinfo=timezone.utc)
        end_dt = _parse_date(end, end_of_day=True) if end else datetime.now(tz=timezone.utc)
        return start_dt, end_dt
    now = datetime.now(tz=timezone.utc)
    normalized = str(period or "1mo").strip().lower()
    if normalized == "1d":
        return now - timedelta(days=1), now
    if normalized == "5d":
        return now - timedelta(days=5), now
    if normalized == "1mo":
        return now - timedelta(days=30), now
    if normalized == "3mo":
        return now - timedelta(days=90), now
    if normalized == "6mo":
        return now - timedelta(days=180), now
    if normalized == "1y":
        return now - timedelta(days=365), now
    if normalized == "2y":
        return now - timedelta(days=730), now
    if normalized == "5y":
        return now - timedelta(days=1825), now
    if normalized == "10y":
        return now - timedelta(days=3650), now
    if normalized == "ytd":
        return datetime(now.year, 1, 1, tzinfo=timezone.utc), now
    if normalized == "max":
        return datetime(1970, 1, 1, tzinfo=timezone.utc), now
    raise ValueError(f"Unsupported Alpaca period '{period}'.")


def _parse_date(value: str | None, *, end_of_day: bool = False) -> datetime:
    if not value:
        raise ValueError("Date value is required.")
    raw = str(value).strip()
    if "T" in raw:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    suffix = "T23:59:59+00:00" if end_of_day else "T00:00:00+00:00"
    return datetime.fromisoformat(f"{raw}{suffix}").astimezone(timezone.utc)


def _first_number(*values: Any) -> float | None:
    for value in values:
        numeric = _to_float(value)
        if numeric is not None:
            return numeric
    return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_number(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)
