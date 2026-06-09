"""EODHD symbol-reference models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class EodhdErrorContext:
    operation: str
    endpoint: str | None = None
    status_code: int | None = None
    message: str | None = None
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EodhdSearchCandidate:
    code: str
    exchange: str | None = None
    provider_symbol: str | None = None
    name: str | None = None
    instrument_type: str | None = None
    country: str | None = None
    currency: str | None = None
    isin: str | None = None
    previous_close: float | None = None
    previous_close_date: str | None = None
    is_primary: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "exchange": self.exchange,
            "provider_symbol": self.provider_symbol,
            "name": self.name,
            "instrument_type": self.instrument_type,
            "country": self.country,
            "currency": self.currency,
            "isin": self.isin,
            "previous_close": self.previous_close,
            "previous_close_date": self.previous_close_date,
            "is_primary": self.is_primary,
            "raw": self.raw,
        }


@dataclass(frozen=True, slots=True)
class EodhdSearchResult:
    query: str
    candidates: list[EodhdSearchCandidate]
    request_params: dict[str, Any] = field(default_factory=dict)
    endpoint: str = "https://eodhd.com/api/search"

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "request_params": self.request_params,
            "endpoint": self.endpoint,
        }


@dataclass(frozen=True, slots=True)
class EodhdIdentifierRecord:
    provider_symbol: str | None = None
    isin: str | None = None
    figi: str | None = None
    lei: str | None = None
    cusip: str | None = None
    cik: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_symbol": self.provider_symbol,
            "isin": self.isin,
            "figi": self.figi,
            "lei": self.lei,
            "cusip": self.cusip,
            "cik": self.cik,
            "raw": self.raw,
        }


@dataclass(frozen=True, slots=True)
class EodhdIdMappingResult:
    records: list[EodhdIdentifierRecord]
    total: int | None = None
    limit: int | None = None
    offset: int | None = None
    next_url: str | None = None
    request_params: dict[str, Any] = field(default_factory=dict)
    endpoint: str = "https://eodhd.com/api/id-mapping"

    def to_dict(self) -> dict[str, Any]:
        return {
            "records": [record.to_dict() for record in self.records],
            "total": self.total,
            "limit": self.limit,
            "offset": self.offset,
            "next_url": self.next_url,
            "request_params": self.request_params,
            "endpoint": self.endpoint,
        }
