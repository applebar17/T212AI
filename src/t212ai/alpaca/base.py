"""Shared Alpaca HTTP client foundation."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from t212ai.app.config import AppSettings


ALPACA_MARKET_DATA_BASE_URL = "https://data.alpaca.markets"
ALPACA_PAPER_TRADING_BASE_URL = "https://paper-api.alpaca.markets"
ALPACA_LIVE_TRADING_BASE_URL = "https://api.alpaca.markets"


class AlpacaApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: str | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.code = code


@dataclass(slots=True)
class AlpacaBaseClient:
    api_key: str
    api_secret: str
    environment: str = "paper"
    market_data_base_url: str = ALPACA_MARKET_DATA_BASE_URL
    paper_trading_base_url: str = ALPACA_PAPER_TRADING_BASE_URL
    live_trading_base_url: str = ALPACA_LIVE_TRADING_BASE_URL
    data_feed: str = "iex"
    timeout_seconds: float = 20.0

    @classmethod
    def from_settings(cls, settings: "AppSettings | None" = None) -> "AlpacaBaseClient":
        if settings is None:
            from t212ai.app.config import get_app_settings

            resolved = get_app_settings()
        else:
            resolved = settings
        if not resolved.alpaca_api_key or not resolved.alpaca_api_secret:
            raise RuntimeError("Alpaca API credentials are missing.")
        return cls(
            api_key=resolved.alpaca_api_key,
            api_secret=resolved.alpaca_api_secret,
            environment=resolved.alpaca_environment,
            market_data_base_url=resolved.alpaca_market_data_base_url,
            paper_trading_base_url=resolved.alpaca_paper_trading_base_url,
            live_trading_base_url=resolved.alpaca_live_trading_base_url,
            data_feed=resolved.alpaca_data_feed,
        )

    @property
    def trading_base_url(self) -> str:
        if str(self.environment or "").strip().lower() == "live":
            return self.live_trading_base_url.rstrip("/")
        return self.paper_trading_base_url.rstrip("/")

    def _request_json(
        self,
        *,
        base_url: str,
        path: str,
        query: dict[str, Any] | None = None,
    ) -> Any:
        url = self._build_url(base_url, path, query=query)
        request = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise AlpacaApiError(
                f"Alpaca request failed with HTTP {exc.code}.",
                status_code=exc.code,
                body=body,
                code="http_error",
            ) from exc
        except urllib.error.URLError as exc:
            raise AlpacaApiError(
                f"Network error contacting Alpaca: {exc.reason}",
                code="network_error",
            ) from exc
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise AlpacaApiError(
                "Alpaca returned invalid JSON.",
                code="invalid_json",
                body=payload,
            ) from exc

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
            "User-Agent": "t212ai-alpaca/1.0",
        }

    def _build_url(
        self,
        base_url: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
    ) -> str:
        cleaned_base = base_url.rstrip("/")
        cleaned_path = path if path.startswith("/") else f"/{path}"
        if not query:
            return f"{cleaned_base}{cleaned_path}"
        encoded = urllib.parse.urlencode(_clean_params(query), doseq=True)
        return f"{cleaned_base}{cleaned_path}?{encoded}"


def _clean_params(values: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, bool):
            cleaned[key] = "true" if value else "false"
            continue
        cleaned[key] = value
    return cleaned
