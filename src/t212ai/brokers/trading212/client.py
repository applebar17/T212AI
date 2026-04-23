"""1:1 Trading 212 Public API client."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from t212ai.app.config import AppSettings, get_app_settings

from .models import (
    AccountBucketInstrumentsDetailedResponse,
    AccountBucketResultResponse,
    AccountSummary,
    DuplicateBucketRequest,
    EnqueuedReportResponse,
    Exchange,
    LimitRequest,
    MarketRequest,
    Order,
    PaginatedResponseHistoricalOrder,
    PaginatedResponseHistoryDividendItem,
    PaginatedResponseHistoryTransactionItem,
    PieRequest,
    Position,
    PublicReportRequest,
    ReportResponse,
    StopLimitRequest,
    StopRequest,
    TradableInstrument,
    Trading212Model,
)
from .rate_limits import RateLimitState, parse_rate_limit_headers


class Trading212ApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: str | None = None,
        rate_limit: RateLimitState | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.rate_limit = rate_limit


@dataclass(slots=True)
class Trading212Client:
    base_url: str
    api_key: str
    api_secret: str
    timeout_seconds: float = 30.0

    @classmethod
    def from_settings(cls, settings: AppSettings | None = None) -> "Trading212Client":
        resolved = settings or get_app_settings()
        if not resolved.trading212_api_key or not resolved.trading212_api_secret:
            raise RuntimeError("Trading 212 API credentials are missing.")
        return cls(
            base_url=resolved.trading212_base_url,
            api_key=resolved.trading212_api_key,
            api_secret=resolved.trading212_api_secret,
        )

    def get_account_summary(self) -> AccountSummary:
        return AccountSummary.model_validate(
            self._request_json("GET", "/api/v0/equity/account/summary")
        )

    def list_dividends(
        self,
        *,
        cursor: str | int | None = None,
        ticker: str | None = None,
        limit: int | None = None,
    ) -> PaginatedResponseHistoryDividendItem:
        return PaginatedResponseHistoryDividendItem.model_validate(
            self._request_json(
                "GET",
                "/api/v0/equity/history/dividends",
                query={"cursor": cursor, "ticker": ticker, "limit": limit},
            )
        )

    def list_reports(self) -> list[ReportResponse]:
        payload = self._request_json("GET", "/api/v0/equity/history/exports")
        return _parse_list(payload, ReportResponse)

    def request_report(self, request: PublicReportRequest) -> EnqueuedReportResponse:
        return EnqueuedReportResponse.model_validate(
            self._request_json(
                "POST",
                "/api/v0/equity/history/exports",
                body=request.to_api_dict(),
            )
        )

    def list_historical_orders(
        self,
        *,
        cursor: str | int | None = None,
        ticker: str | None = None,
        limit: int | None = None,
    ) -> PaginatedResponseHistoricalOrder:
        return PaginatedResponseHistoricalOrder.model_validate(
            self._request_json(
                "GET",
                "/api/v0/equity/history/orders",
                query={"cursor": cursor, "ticker": ticker, "limit": limit},
            )
        )

    def list_transactions(
        self,
        *,
        cursor: str | int | None = None,
        time: str | None = None,
        limit: int | None = None,
    ) -> PaginatedResponseHistoryTransactionItem:
        return PaginatedResponseHistoryTransactionItem.model_validate(
            self._request_json(
                "GET",
                "/api/v0/equity/history/transactions",
                query={"cursor": cursor, "time": time, "limit": limit},
            )
        )

    def list_exchanges(self) -> list[Exchange]:
        payload = self._request_json("GET", "/api/v0/equity/metadata/exchanges")
        return _parse_list(payload, Exchange)

    def list_instruments(self) -> list[TradableInstrument]:
        payload = self._request_json("GET", "/api/v0/equity/metadata/instruments")
        return _parse_list(payload, TradableInstrument)

    def list_pending_orders(self) -> list[Order]:
        payload = self._request_json("GET", "/api/v0/equity/orders")
        return _parse_list(payload, Order)

    def place_limit_order(self, request: LimitRequest) -> Order:
        return Order.model_validate(
            self._request_json("POST", "/api/v0/equity/orders/limit", body=request.to_api_dict())
        )

    def place_market_order(self, request: MarketRequest) -> Order:
        return Order.model_validate(
            self._request_json("POST", "/api/v0/equity/orders/market", body=request.to_api_dict())
        )

    def place_stop_order(self, request: StopRequest) -> Order:
        return Order.model_validate(
            self._request_json("POST", "/api/v0/equity/orders/stop", body=request.to_api_dict())
        )

    def place_stop_limit_order(self, request: StopLimitRequest) -> Order:
        return Order.model_validate(
            self._request_json(
                "POST", "/api/v0/equity/orders/stop_limit", body=request.to_api_dict()
            )
        )

    def cancel_order(self, order_id: int) -> None:
        self._request_json("DELETE", f"/api/v0/equity/orders/{int(order_id)}")

    def get_order(self, order_id: int) -> Order:
        return Order.model_validate(
            self._request_json("GET", f"/api/v0/equity/orders/{int(order_id)}")
        )

    def list_pies(self) -> list[AccountBucketResultResponse]:
        payload = self._request_json("GET", "/api/v0/equity/pies")
        return _parse_list(payload, AccountBucketResultResponse)

    def create_pie(self, request: PieRequest) -> AccountBucketInstrumentsDetailedResponse:
        return AccountBucketInstrumentsDetailedResponse.model_validate(
            self._request_json("POST", "/api/v0/equity/pies", body=request.to_api_dict())
        )

    def delete_pie(self, pie_id: int) -> None:
        self._request_json("DELETE", f"/api/v0/equity/pies/{int(pie_id)}")

    def get_pie(self, pie_id: int) -> AccountBucketInstrumentsDetailedResponse:
        return AccountBucketInstrumentsDetailedResponse.model_validate(
            self._request_json("GET", f"/api/v0/equity/pies/{int(pie_id)}")
        )

    def update_pie(self, pie_id: int, request: PieRequest) -> AccountBucketInstrumentsDetailedResponse:
        return AccountBucketInstrumentsDetailedResponse.model_validate(
            self._request_json(
                "POST",
                f"/api/v0/equity/pies/{int(pie_id)}",
                body=request.to_api_dict(),
            )
        )

    def duplicate_pie(
        self,
        pie_id: int,
        request: DuplicateBucketRequest,
    ) -> AccountBucketInstrumentsDetailedResponse:
        return AccountBucketInstrumentsDetailedResponse.model_validate(
            self._request_json(
                "POST",
                f"/api/v0/equity/pies/{int(pie_id)}/duplicate",
                body=request.to_api_dict(),
            )
        )

    def list_positions(self, *, ticker: str | None = None) -> list[Position]:
        payload = self._request_json(
            "GET",
            "/api/v0/equity/positions",
            query={"ticker": ticker},
        )
        return _parse_list(payload, Position)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        url = self._build_url(path, query=query)
        data = None
        headers = {
            "Authorization": self._authorization_header(),
            "Accept": "application/json",
            "User-Agent": "t212ai-trading212-client/0.1",
        }
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=method.upper(),
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
                if not raw.strip():
                    return None
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            raw_body = exc.read().decode("utf-8", errors="replace")
            raise Trading212ApiError(
                f"Trading 212 API request failed with HTTP {exc.code}.",
                status_code=exc.code,
                body=raw_body,
                rate_limit=parse_rate_limit_headers(dict(exc.headers.items())),
            ) from exc
        except urllib.error.URLError as exc:
            raise Trading212ApiError(f"Trading 212 API request failed: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise Trading212ApiError("Trading 212 API returned invalid JSON.") from exc

    def _build_url(self, path: str, *, query: dict[str, Any] | None = None) -> str:
        base = self.base_url.rstrip("/")
        resolved_path = path
        if base.endswith("/api/v0") and resolved_path.startswith("/api/v0/"):
            resolved_path = resolved_path.removeprefix("/api/v0")
        url = f"{base}/{resolved_path.lstrip('/')}"
        clean_query = {
            key: value
            for key, value in (query or {}).items()
            if value is not None and value != ""
        }
        if clean_query:
            url = f"{url}?{urllib.parse.urlencode(clean_query)}"
        return url

    def _authorization_header(self) -> str:
        raw = f"{self.api_key}:{self.api_secret}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")


def _parse_list(payload: Any, model_type: type[Trading212Model]) -> list[Any]:
    items = payload if isinstance(payload, list) else (payload or [])
    return [model_type.model_validate(item) for item in items]
