"""Agent-facing Trading 212 broker service."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any

from .models import (
    LimitRequest,
    MarketRequest,
    Order,
    OrderActionResult,
    OrderSide,
    OrderType,
    PaginatedResponseHistoricalOrder,
    PortfolioSnapshot,
    PreparedOrder,
    StopLimitRequest,
    StopRequest,
    TimeValidity,
)
from .protocols import Trading212ApiProtocol


class Trading212BrokerService:
    """Composes low-level API calls into stable application operations."""

    def __init__(self, api: Trading212ApiProtocol) -> None:
        self.api = api

    def get_portfolio_snapshot(self) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            account=self.api.get_account_summary(),
            positions=self.api.list_positions(),
            pending_orders=self.api.list_pending_orders(),
        )

    def list_pending_orders(self) -> list[Order]:
        return self.api.list_pending_orders()

    def get_order(self, order_id: int) -> Order:
        return self.api.get_order(order_id)

    def list_historical_orders(
        self,
        *,
        cursor: str | int | None = None,
        ticker: str | None = None,
        limit: int | None = None,
    ) -> PaginatedResponseHistoricalOrder:
        return self.api.list_historical_orders(
            cursor=cursor,
            ticker=ticker,
            limit=limit,
        )

    def prepare_order(
        self,
        *,
        order_type: OrderType | str,
        side: OrderSide | str,
        ticker: str,
        quantity: str | int | float,
        limit_price: str | int | float | None = None,
        stop_price: str | int | float | None = None,
        time_validity: TimeValidity | str = TimeValidity.DAY,
        extended_hours: bool = False,
    ) -> PreparedOrder:
        resolved_type = _coerce_enum(OrderType, order_type, "order_type")
        resolved_side = _coerce_enum(OrderSide, side, "side")
        resolved_time_validity = _coerce_enum(TimeValidity, time_validity, "time_validity")
        resolved_ticker = _normalize_ticker(ticker)
        unsigned_quantity = _positive_decimal(quantity, "quantity")
        signed_quantity = (
            unsigned_quantity if resolved_side == OrderSide.BUY else -unsigned_quantity
        )
        warnings: list[str] = []

        if extended_hours and resolved_type != OrderType.MARKET:
            warnings.append("extended_hours is only supported for Trading 212 market orders.")

        request_payload = self._build_order_payload(
            order_type=resolved_type,
            ticker=resolved_ticker,
            signed_quantity=signed_quantity,
            limit_price=limit_price,
            stop_price=stop_price,
            time_validity=resolved_time_validity,
            extended_hours=extended_hours,
        )
        fingerprint = _fingerprint(
            {
                "orderType": resolved_type.value,
                "side": resolved_side.value,
                "ticker": resolved_ticker,
                "requestPayload": request_payload,
            }
        )
        return PreparedOrder(
            order_type=resolved_type,
            side=resolved_side,
            ticker=resolved_ticker,
            signed_quantity=signed_quantity,
            request_payload=request_payload,
            order_fingerprint=fingerprint,
            warnings=warnings,
        )

    def submit_prepared_order(self, prepared_order: PreparedOrder) -> OrderActionResult:
        order_type = prepared_order.order_type
        payload = prepared_order.request_payload
        if order_type == OrderType.MARKET:
            order = self.api.place_market_order(MarketRequest.model_validate(payload))
        elif order_type == OrderType.LIMIT:
            order = self.api.place_limit_order(LimitRequest.model_validate(payload))
        elif order_type == OrderType.STOP:
            order = self.api.place_stop_order(StopRequest.model_validate(payload))
        elif order_type == OrderType.STOP_LIMIT:
            order = self.api.place_stop_limit_order(StopLimitRequest.model_validate(payload))
        else:  # pragma: no cover - enum exhaustiveness guard
            raise ValueError(f"Unsupported order type: {order_type}")

        return OrderActionResult(
            action="submit_order",
            status=str(order.status or "submitted"),
            order_id=order.id,
            order=order,
            message="Order submitted to Trading 212.",
        )

    def place_order(
        self,
        *,
        order_type: OrderType | str,
        side: OrderSide | str,
        ticker: str,
        quantity: str | int | float,
        limit_price: str | int | float | None = None,
        stop_price: str | int | float | None = None,
        time_validity: TimeValidity | str = TimeValidity.DAY,
        extended_hours: bool = False,
    ) -> OrderActionResult:
        prepared = self.prepare_order(
            order_type=order_type,
            side=side,
            ticker=ticker,
            quantity=quantity,
            limit_price=limit_price,
            stop_price=stop_price,
            time_validity=time_validity,
            extended_hours=extended_hours,
        )
        return self.submit_prepared_order(prepared)

    def cancel_order(self, order_id: int) -> OrderActionResult:
        resolved_order_id = int(order_id)
        self.api.cancel_order(resolved_order_id)
        return OrderActionResult(
            action="cancel_order",
            status="accepted",
            order_id=resolved_order_id,
            message="Cancellation request accepted by Trading 212.",
        )

    def _build_order_payload(
        self,
        *,
        order_type: OrderType,
        ticker: str,
        signed_quantity: Decimal,
        limit_price: str | int | float | None,
        stop_price: str | int | float | None,
        time_validity: TimeValidity,
        extended_hours: bool,
    ) -> dict[str, Any]:
        if order_type == OrderType.MARKET:
            return MarketRequest(
                ticker=ticker,
                quantity=signed_quantity,
                extended_hours=bool(extended_hours),
            ).to_api_dict()
        if order_type == OrderType.LIMIT:
            return LimitRequest(
                ticker=ticker,
                quantity=signed_quantity,
                limit_price=_required_decimal(limit_price, "limit_price"),
                time_validity=time_validity,
            ).to_api_dict()
        if order_type == OrderType.STOP:
            return StopRequest(
                ticker=ticker,
                quantity=signed_quantity,
                stop_price=_required_decimal(stop_price, "stop_price"),
                time_validity=time_validity,
            ).to_api_dict()
        if order_type == OrderType.STOP_LIMIT:
            return StopLimitRequest(
                ticker=ticker,
                quantity=signed_quantity,
                limit_price=_required_decimal(limit_price, "limit_price"),
                stop_price=_required_decimal(stop_price, "stop_price"),
                time_validity=time_validity,
            ).to_api_dict()
        raise ValueError(f"Unsupported order type: {order_type}")


def _coerce_enum(enum_type: type[Any], value: Any, field_name: str) -> Any:
    raw = str(value or "").strip().upper()
    if not raw:
        raise ValueError(f"{field_name} is required.")
    try:
        return enum_type(raw)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ValueError(f"{field_name} must be one of: {allowed}.") from exc


def _normalize_ticker(value: str) -> str:
    ticker = str(value or "").strip().upper()
    if not ticker:
        raise ValueError("ticker is required.")
    return ticker


def _to_decimal(value: str | int | float | Decimal | None, field_name: str) -> Decimal:
    if value is None or value == "":
        raise ValueError(f"{field_name} is required.")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} must be a valid decimal number.") from exc


def _positive_decimal(value: str | int | float | Decimal, field_name: str) -> Decimal:
    resolved = _to_decimal(value, field_name)
    if resolved <= 0:
        raise ValueError(f"{field_name} must be greater than zero.")
    return resolved


def _required_decimal(value: str | int | float | Decimal | None, field_name: str) -> Decimal:
    return _positive_decimal(value, field_name)


def _fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
