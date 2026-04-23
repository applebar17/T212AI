"""Yahoo Finance data-source models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class YahooFinanceError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        details: dict[str, Any] | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}
        self.retryable = retryable


@dataclass(slots=True)
class YahooPriceHistoryResult:
    series: dict[str, list[dict[str, Any]]]
    errors: dict[str, dict[str, Any]]
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class YahooQuoteSnapshotResult:
    quotes: dict[str, dict[str, Any]]
    errors: dict[str, dict[str, Any]]
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class YahooSearchResult:
    query: str
    quotes: list[dict[str, Any]]
    news: list[dict[str, Any]]
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class YahooQuoteSummaryResult:
    symbol: str
    modules: list[str]
    data: dict[str, Any]
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class YahooOptionsResult:
    symbol: str
    expiration_dates: list[int]
    options: list[dict[str, Any]]
    quote: dict[str, Any] | None = None
    meta: dict[str, Any] = field(default_factory=dict)
