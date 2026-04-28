"""Provider-neutral market-data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MarketPriceHistoryResult:
    series: dict[str, list[dict[str, Any]]]
    errors: dict[str, dict[str, Any]]
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MarketQuoteSnapshotResult:
    quotes: dict[str, dict[str, Any]]
    errors: dict[str, dict[str, Any]]
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MarketSymbolSearchResult:
    query: str
    candidates: list[dict[str, Any]]
    meta: dict[str, Any] = field(default_factory=dict)
