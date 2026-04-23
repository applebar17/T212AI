"""Alpha Vantage response models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class AlphaVantageResponse:
    function: str
    data: dict[str, Any] | list[dict[str, Any]]
    request_params: dict[str, Any] = field(default_factory=dict)
    endpoint: str = "https://www.alphavantage.co/query"
    datatype: str = "json"

    def to_dict(self) -> dict[str, Any]:
        return {
            "function": self.function,
            "request_params": self.request_params,
            "endpoint": self.endpoint,
            "datatype": self.datatype,
            "data": self.data,
        }


@dataclass(frozen=True, slots=True)
class AlphaVantageErrorContext:
    function: str | None
    status_code: int | None = None
    message: str | None = None
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)
