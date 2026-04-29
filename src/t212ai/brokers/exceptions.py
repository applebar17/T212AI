"""Shared broker exception types."""

from __future__ import annotations

from typing import Any

from .models import BrokerInstrumentResolution


class BrokerInstrumentResolutionError(ValueError):
    """Raised when a broker cannot map a user-facing symbol to a tradable id."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        resolution: BrokerInstrumentResolution,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.resolution = resolution

    def details(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "resolution": self.resolution.model_dump(
                by_alias=True,
                exclude_none=True,
                mode="json",
            ),
        }
