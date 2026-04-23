"""Yahoo price-series analytics."""

from __future__ import annotations

import math
from typing import Any


class PriceSeriesAnalytics:
    @staticmethod
    def summarize_series(
        series_payload: dict[str, list[dict[str, Any]]],
    ) -> dict[str, dict[str, Any]]:
        return {
            symbol: PriceSeriesAnalytics.summarize_points(points)
            for symbol, points in series_payload.items()
        }

    @staticmethod
    def summarize_points(points: list[dict[str, Any]]) -> dict[str, Any]:
        if not points:
            return {
                "points": 0,
                "start_timestamp": None,
                "end_timestamp": None,
                "open": None,
                "close": None,
                "high": None,
                "low": None,
                "abs_change": None,
                "pct_change": None,
                "log_return": None,
                "annualized_volatility_pct": None,
                "max_drawdown_pct": None,
                "average_volume": None,
            }

        effective_closes = [
            close for point in points if (close := _effective_close(point)) is not None
        ]
        highs = [_to_float(point.get("high")) for point in points]
        highs = [value for value in highs if value is not None]
        lows = [_to_float(point.get("low")) for point in points]
        lows = [value for value in lows if value is not None]
        volumes = [_to_float(point.get("volume")) for point in points]
        volumes = [value for value in volumes if value is not None]

        first = points[0]
        last = points[-1]
        open_price = _first_number(first.get("open"), _effective_close(first))
        close_price = _first_number(
            last.get("close"),
            last.get("adj_close"),
            _effective_close(last),
        )
        high_price = (
            max(highs) if highs else (max(effective_closes) if effective_closes else None)
        )
        low_price = (
            min(lows) if lows else (min(effective_closes) if effective_closes else None)
        )

        abs_change = None
        pct_change = None
        log_return = None
        if open_price is not None and close_price is not None:
            abs_change = close_price - open_price
            if open_price != 0:
                pct_change = (abs_change / open_price) * 100.0
            if open_price > 0 and close_price > 0:
                log_return = math.log(close_price / open_price)

        returns = _returns(effective_closes)
        return {
            "points": len(points),
            "start_timestamp": str(first.get("timestamp") or "") or None,
            "end_timestamp": str(last.get("timestamp") or "") or None,
            "open": _round(open_price),
            "close": _round(close_price),
            "high": _round(high_price),
            "low": _round(low_price),
            "abs_change": _round(abs_change),
            "pct_change": _round(pct_change),
            "log_return": _round(log_return),
            "annualized_volatility_pct": _round(_annualized_volatility_pct(returns)),
            "max_drawdown_pct": _round(_max_drawdown_pct(effective_closes)),
            "average_volume": _round(sum(volumes) / len(volumes) if volumes else None),
        }


def _first_number(*values: Any) -> float | None:
    for value in values:
        numeric = _to_float(value)
        if numeric is not None:
            return numeric
    return None


def _effective_close(point: dict[str, Any]) -> float | None:
    return _first_number(
        point.get("close"),
        point.get("adj_close"),
        point.get("open"),
        point.get("high"),
        point.get("low"),
    )


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if value != value:
            return None
    except Exception:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _returns(prices: list[float]) -> list[float]:
    if len(prices) < 2:
        return []
    out: list[float] = []
    for idx in range(1, len(prices)):
        prev = prices[idx - 1]
        curr = prices[idx]
        if prev <= 0:
            continue
        out.append((curr / prev) - 1.0)
    return out


def _annualized_volatility_pct(returns: list[float]) -> float | None:
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((item - mean) ** 2 for item in returns) / (len(returns) - 1)
    if variance < 0:
        return None
    return math.sqrt(variance) * math.sqrt(252) * 100.0


def _max_drawdown_pct(prices: list[float]) -> float | None:
    if len(prices) < 2:
        return None
    peak = prices[0]
    max_drawdown = 0.0
    for price in prices:
        if price > peak:
            peak = price
        if peak <= 0:
            continue
        drawdown = (price / peak) - 1.0
        if drawdown < max_drawdown:
            max_drawdown = drawdown
    return max_drawdown * 100.0
