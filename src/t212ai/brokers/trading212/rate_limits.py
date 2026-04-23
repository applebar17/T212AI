"""Trading 212 endpoint rate-limit metadata and response header parsing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class EndpointRateLimit:
    method: str
    path: str
    limit: int
    period_seconds: int


@dataclass(frozen=True)
class RateLimitState:
    limit: int | None = None
    period_seconds: int | None = None
    remaining: int | None = None
    reset_timestamp: int | None = None
    used: int | None = None


ENDPOINT_RATE_LIMITS: dict[tuple[str, str], EndpointRateLimit] = {
    ("GET", "/api/v0/equity/account/summary"): EndpointRateLimit(
        "GET", "/api/v0/equity/account/summary", 1, 5
    ),
    ("GET", "/api/v0/equity/history/dividends"): EndpointRateLimit(
        "GET", "/api/v0/equity/history/dividends", 6, 60
    ),
    ("GET", "/api/v0/equity/history/exports"): EndpointRateLimit(
        "GET", "/api/v0/equity/history/exports", 1, 60
    ),
    ("POST", "/api/v0/equity/history/exports"): EndpointRateLimit(
        "POST", "/api/v0/equity/history/exports", 1, 30
    ),
    ("GET", "/api/v0/equity/history/orders"): EndpointRateLimit(
        "GET", "/api/v0/equity/history/orders", 6, 60
    ),
    ("GET", "/api/v0/equity/history/transactions"): EndpointRateLimit(
        "GET", "/api/v0/equity/history/transactions", 6, 60
    ),
    ("GET", "/api/v0/equity/metadata/exchanges"): EndpointRateLimit(
        "GET", "/api/v0/equity/metadata/exchanges", 1, 30
    ),
    ("GET", "/api/v0/equity/metadata/instruments"): EndpointRateLimit(
        "GET", "/api/v0/equity/metadata/instruments", 1, 50
    ),
    ("GET", "/api/v0/equity/orders"): EndpointRateLimit(
        "GET", "/api/v0/equity/orders", 1, 5
    ),
    ("POST", "/api/v0/equity/orders/limit"): EndpointRateLimit(
        "POST", "/api/v0/equity/orders/limit", 1, 2
    ),
    ("POST", "/api/v0/equity/orders/market"): EndpointRateLimit(
        "POST", "/api/v0/equity/orders/market", 50, 60
    ),
    ("POST", "/api/v0/equity/orders/stop"): EndpointRateLimit(
        "POST", "/api/v0/equity/orders/stop", 1, 2
    ),
    ("POST", "/api/v0/equity/orders/stop_limit"): EndpointRateLimit(
        "POST", "/api/v0/equity/orders/stop_limit", 1, 2
    ),
    ("DELETE", "/api/v0/equity/orders/{id}"): EndpointRateLimit(
        "DELETE", "/api/v0/equity/orders/{id}", 50, 60
    ),
    ("GET", "/api/v0/equity/orders/{id}"): EndpointRateLimit(
        "GET", "/api/v0/equity/orders/{id}", 1, 1
    ),
    ("GET", "/api/v0/equity/pies"): EndpointRateLimit(
        "GET", "/api/v0/equity/pies", 1, 30
    ),
    ("POST", "/api/v0/equity/pies"): EndpointRateLimit(
        "POST", "/api/v0/equity/pies", 1, 5
    ),
    ("DELETE", "/api/v0/equity/pies/{id}"): EndpointRateLimit(
        "DELETE", "/api/v0/equity/pies/{id}", 1, 5
    ),
    ("GET", "/api/v0/equity/pies/{id}"): EndpointRateLimit(
        "GET", "/api/v0/equity/pies/{id}", 1, 5
    ),
    ("POST", "/api/v0/equity/pies/{id}"): EndpointRateLimit(
        "POST", "/api/v0/equity/pies/{id}", 1, 5
    ),
    ("POST", "/api/v0/equity/pies/{id}/duplicate"): EndpointRateLimit(
        "POST", "/api/v0/equity/pies/{id}/duplicate", 1, 5
    ),
    ("GET", "/api/v0/equity/positions"): EndpointRateLimit(
        "GET", "/api/v0/equity/positions", 1, 1
    ),
}


def declared_rate_limit(method: str, path: str) -> EndpointRateLimit | None:
    return ENDPOINT_RATE_LIMITS.get((method.upper(), path))


def parse_rate_limit_headers(headers: Mapping[str, str]) -> RateLimitState:
    lower = {str(key).lower(): str(value) for key, value in headers.items()}
    return RateLimitState(
        limit=_to_int(lower.get("x-ratelimit-limit")),
        period_seconds=_to_int(lower.get("x-ratelimit-period")),
        remaining=_to_int(lower.get("x-ratelimit-remaining")),
        reset_timestamp=_to_int(lower.get("x-ratelimit-reset")),
        used=_to_int(lower.get("x-ratelimit-used")),
    )


def _to_int(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        return int(value)
    except ValueError:
        return None
