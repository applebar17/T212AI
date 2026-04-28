"""Alpaca brokerage client and generic broker adapter."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any

from t212ai.brokers.models import (
    BrokerAccountSummary,
    BrokerCash,
    BrokerHistoricalOrder,
    BrokerHistoricalOrdersPage,
    BrokerInstrument,
    BrokerInvestments,
    BrokerOrder,
    BrokerOrderActionResult,
    BrokerOrderSide,
    BrokerOrderStatus,
    BrokerOrderType,
    BrokerPortfolioSnapshot,
    BrokerPosition,
    BrokerPositionWalletImpact,
    BrokerTimeInForce,
    PreparedBrokerOrder,
)

from .base import AlpacaApiError, AlpacaBaseClient


class AlpacaBrokerClient(AlpacaBaseClient):
    """HTTP client for Alpaca trading/account endpoints."""

    provider_name = "alpaca"

    def get_account(self) -> dict[str, Any]:
        payload = self._request_json(
            base_url=self.trading_base_url,
            path="/v2/account",
        )
        if not isinstance(payload, dict):
            raise AlpacaApiError("Alpaca account endpoint returned an unexpected payload.")
        return payload

    def list_positions(self) -> list[dict[str, Any]]:
        payload = self._request_json(
            base_url=self.trading_base_url,
            path="/v2/positions",
        )
        if not isinstance(payload, list):
            raise AlpacaApiError("Alpaca positions endpoint returned an unexpected payload.")
        return [item for item in payload if isinstance(item, dict)]

    def list_orders(
        self,
        *,
        status: str,
        limit: int | None = None,
        ticker: str | None = None,
        cursor: str | int | None = None,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {
            "status": status,
            "direction": "desc",
            "nested": False,
        }
        if limit is not None:
            query["limit"] = max(1, int(limit))
        if ticker:
            query["symbols"] = str(ticker).strip().upper()
        if cursor not in {None, ""}:
            query["after"] = str(cursor)
        payload = self._request_json(
            base_url=self.trading_base_url,
            path="/v2/orders",
            query=query,
        )
        if not isinstance(payload, list):
            raise AlpacaApiError("Alpaca orders endpoint returned an unexpected payload.")
        return [item for item in payload if isinstance(item, dict)]

    def get_order(self, order_ref: str) -> dict[str, Any]:
        payload = self._request_json(
            base_url=self.trading_base_url,
            path=f"/v2/orders/{str(order_ref).strip()}",
        )
        if not isinstance(payload, dict):
            raise AlpacaApiError("Alpaca order lookup returned an unexpected payload.")
        return payload

    def place_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request_json(
            base_url=self.trading_base_url,
            path="/v2/orders",
            method="POST",
            body=payload,
        )
        if not isinstance(response, dict):
            raise AlpacaApiError("Alpaca order submission returned an unexpected payload.")
        return response

    def cancel_order(self, order_ref: str) -> None:
        self._request_json(
            base_url=self.trading_base_url,
            path=f"/v2/orders/{str(order_ref).strip()}",
            method="DELETE",
            allow_empty=True,
        )


class AlpacaBrokerService:
    """Maps Alpaca brokerage into the generic broker contract."""

    provider_name = "alpaca"

    def __init__(self, api: AlpacaBrokerClient) -> None:
        self.api = api

    def get_portfolio_snapshot(self) -> BrokerPortfolioSnapshot:
        account_payload = self.api.get_account()
        positions_payload = self.api.list_positions()
        pending_orders_payload = self.api.list_orders(status="open", limit=200)
        positions = [_broker_position(item) for item in positions_payload]
        pending_orders = [_broker_order(item) for item in pending_orders_payload]
        return BrokerPortfolioSnapshot(
            account=_broker_account_summary(account_payload, positions=positions),
            positions=positions,
            pending_orders=pending_orders,
        )

    def list_pending_orders(self) -> list[BrokerOrder]:
        return [_broker_order(item) for item in self.api.list_orders(status="open", limit=200)]

    def get_order(self, order_ref: str) -> BrokerOrder:
        return _broker_order(self.api.get_order(str(order_ref)))

    def list_historical_orders(
        self,
        *,
        cursor: str | int | None = None,
        ticker: str | None = None,
        limit: int | None = None,
    ) -> BrokerHistoricalOrdersPage:
        orders = self.api.list_orders(
            status="all",
            cursor=cursor,
            ticker=ticker,
            limit=limit or 50,
        )
        return BrokerHistoricalOrdersPage(
            items=[BrokerHistoricalOrder(order=_broker_order(item)) for item in orders],
            next_page_path=None,
        )

    def prepare_order(
        self,
        *,
        order_type: BrokerOrderType | str,
        side: BrokerOrderSide | str,
        ticker: str,
        quantity: str | int | float,
        limit_price: str | int | float | None = None,
        stop_price: str | int | float | None = None,
        time_in_force: BrokerTimeInForce | str = BrokerTimeInForce.DAY,
        extended_hours: bool = False,
    ) -> PreparedBrokerOrder:
        resolved_type = _coerce_enum(BrokerOrderType, order_type, "order_type")
        resolved_side = _coerce_enum(BrokerOrderSide, side, "side")
        resolved_time_in_force = _coerce_enum(BrokerTimeInForce, time_in_force, "time_in_force")
        resolved_ticker = _normalize_symbol(ticker)
        resolved_quantity = _positive_decimal(quantity, "quantity")
        signed_quantity = (
            resolved_quantity
            if resolved_side == BrokerOrderSide.BUY
            else -resolved_quantity
        )
        _validate_alpaca_order_constraints(
            order_type=resolved_type,
            time_in_force=resolved_time_in_force,
            extended_hours=bool(extended_hours),
        )
        payload: dict[str, Any] = {
            "symbol": resolved_ticker,
            "qty": _decimal_to_wire(resolved_quantity),
            "side": resolved_side.value.lower(),
            "type": _alpaca_order_type(resolved_type),
            "time_in_force": _alpaca_time_in_force(resolved_time_in_force),
            "extended_hours": bool(extended_hours),
        }
        if resolved_type in {BrokerOrderType.LIMIT, BrokerOrderType.STOP_LIMIT}:
            payload["limit_price"] = _decimal_to_wire(_required_decimal(limit_price, "limit_price"))
        if resolved_type in {BrokerOrderType.STOP, BrokerOrderType.STOP_LIMIT}:
            payload["stop_price"] = _decimal_to_wire(_required_decimal(stop_price, "stop_price"))
        fingerprint = _fingerprint(
            {
                "orderType": resolved_type.value,
                "side": resolved_side.value,
                "ticker": resolved_ticker,
                "requestPayload": payload,
            }
        )
        payload["client_order_id"] = _alpaca_client_order_id(fingerprint)
        return PreparedBrokerOrder(
            broker_provider=self.provider_name,
            order_type=resolved_type,
            side=resolved_side,
            ticker=resolved_ticker,
            quantity=resolved_quantity,
            signed_quantity=signed_quantity,
            limit_price=_optional_decimal(limit_price),
            stop_price=_optional_decimal(stop_price),
            time_in_force=resolved_time_in_force,
            extended_hours=bool(extended_hours),
            request_payload=payload,
            order_fingerprint=fingerprint,
            warnings=[],
        )

    def submit_prepared_order(
        self,
        prepared_order: PreparedBrokerOrder,
    ) -> BrokerOrderActionResult:
        payload = dict(prepared_order.request_payload)
        response = self.api.place_order(payload)
        order = _broker_order(response)
        return BrokerOrderActionResult(
            broker_provider=self.provider_name,
            action="submit_order",
            status=str(order.status.value if order.status is not None else "accepted"),
            order_id=str(order.id) if order.id is not None else None,
            order=order,
            message="Order submitted to Alpaca.",
            raw_provider_payload=response,
        )

    def place_order(
        self,
        *,
        order_type: BrokerOrderType | str,
        side: BrokerOrderSide | str,
        ticker: str,
        quantity: str | int | float,
        limit_price: str | int | float | None = None,
        stop_price: str | int | float | None = None,
        time_in_force: BrokerTimeInForce | str = BrokerTimeInForce.DAY,
        extended_hours: bool = False,
    ) -> BrokerOrderActionResult:
        prepared = self.prepare_order(
            order_type=order_type,
            side=side,
            ticker=ticker,
            quantity=quantity,
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force=time_in_force,
            extended_hours=extended_hours,
        )
        return self.submit_prepared_order(prepared)

    def cancel_order(self, order_ref: str) -> BrokerOrderActionResult:
        self.api.cancel_order(str(order_ref))
        return BrokerOrderActionResult(
            broker_provider=self.provider_name,
            action="cancel_order",
            status="accepted",
            order_id=str(order_ref),
            message="Cancellation request accepted by Alpaca.",
        )


def _broker_account_summary(
    payload: dict[str, Any],
    *,
    positions: list[BrokerPosition],
) -> BrokerAccountSummary:
    currency = _string_or_none(
        payload.get("currency") or payload.get("base_currency") or "USD"
    )
    current_value = _sum_decimal(
        position.wallet_impact.current_value
        for position in positions
        if position.wallet_impact is not None
    )
    total_cost = _sum_decimal(
        position.wallet_impact.total_cost
        for position in positions
        if position.wallet_impact is not None
    )
    unrealized = _sum_decimal(
        position.wallet_impact.unrealized_profit_loss
        for position in positions
        if position.wallet_impact is not None
    )
    return BrokerAccountSummary(
        cash=BrokerCash(
            available_to_trade=_to_decimal(payload.get("buying_power") or payload.get("cash")),
            in_pies=None,
            reserved_for_orders=None,
        ),
        currency=currency,
        id=_string_or_none(payload.get("account_number") or payload.get("id")),
        investments=BrokerInvestments(
            current_value=current_value,
            realized_profit_loss=None,
            total_cost=total_cost,
            unrealized_profit_loss=unrealized,
        ),
        total_value=_to_decimal(payload.get("portfolio_value") or payload.get("equity")),
    )


def _broker_position(payload: dict[str, Any]) -> BrokerPosition:
    instrument = BrokerInstrument(
        currency=_string_or_none(payload.get("asset_currency") or "USD"),
        isin=None,
        name=_string_or_none(payload.get("symbol")),
        ticker=_string_or_none(payload.get("symbol")),
    )
    current_value = _to_decimal(payload.get("market_value"))
    total_cost = _to_decimal(payload.get("cost_basis"))
    unrealized = _to_decimal(payload.get("unrealized_pl"))
    return BrokerPosition(
        average_price_paid=_to_decimal(payload.get("avg_entry_price")),
        created_at=None,
        current_price=_to_decimal(payload.get("current_price")),
        instrument=instrument,
        quantity=_to_decimal(payload.get("qty")),
        quantity_available_for_trading=_to_decimal(
            payload.get("qty_available") or payload.get("qty")
        ),
        quantity_in_pies=None,
        wallet_impact=BrokerPositionWalletImpact(
            currency=instrument.currency,
            current_value=current_value,
            fx_impact=None,
            total_cost=total_cost,
            unrealized_profit_loss=unrealized,
        ),
    )


def _broker_order(payload: dict[str, Any]) -> BrokerOrder:
    symbol = _string_or_none(payload.get("symbol"))
    instrument = BrokerInstrument(
        currency="USD",
        isin=None,
        name=symbol,
        ticker=symbol,
    )
    raw_type = (
        payload.get("type")
        or payload.get("order_type")
        or payload.get("orderType")
    )
    raw_time_in_force = payload.get("time_in_force") or payload.get("timeInForce")
    return BrokerOrder(
        created_at=_parse_datetime(payload.get("created_at") or payload.get("createdAt")),
        currency="USD",
        extended_hours=_to_bool(payload.get("extended_hours") or payload.get("extendedHours")),
        filled_quantity=_to_decimal(payload.get("filled_qty") or payload.get("filledQuantity")),
        filled_value=_filled_value(payload),
        id=_string_or_none(payload.get("id")),
        initiated_from=_string_or_none(payload.get("source")),
        instrument=instrument,
        limit_price=_to_decimal(payload.get("limit_price") or payload.get("limitPrice")),
        quantity=_to_decimal(payload.get("qty") or payload.get("quantity")),
        side=_map_order_side(payload.get("side")),
        status=_map_order_status(payload.get("status")),
        stop_price=_to_decimal(payload.get("stop_price") or payload.get("stopPrice")),
        strategy=_string_or_none(payload.get("order_class") or payload.get("orderClass")),
        ticker=symbol,
        time_in_force=_map_time_in_force(raw_time_in_force),
        type=_map_order_type(raw_type),
        value=_to_decimal(payload.get("notional")),
        raw_provider_payload=payload,
    )


def _filled_value(payload: dict[str, Any]) -> Decimal | None:
    filled_qty = _to_decimal(payload.get("filled_qty") or payload.get("filledQuantity"))
    filled_avg_price = _to_decimal(
        payload.get("filled_avg_price") or payload.get("filledAvgPrice")
    )
    if filled_qty is None or filled_avg_price is None:
        return None
    return filled_qty * filled_avg_price


def _coerce_enum(enum_type: type[Any], value: Any, field_name: str) -> Any:
    raw = str(value or "").strip().upper()
    if not raw:
        raise ValueError(f"{field_name} is required.")
    try:
        return enum_type(raw)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ValueError(f"{field_name} must be one of: {allowed}.") from exc


def _normalize_symbol(value: str) -> str:
    symbol = str(value or "").strip().upper()
    if not symbol:
        raise ValueError("ticker is required.")
    return symbol


def _validate_alpaca_order_constraints(
    *,
    order_type: BrokerOrderType,
    time_in_force: BrokerTimeInForce,
    extended_hours: bool,
) -> None:
    if extended_hours and order_type != BrokerOrderType.LIMIT:
        raise ValueError(
            "Alpaca extended-hours orders currently require order_type=LIMIT."
        )
    if extended_hours and time_in_force != BrokerTimeInForce.DAY:
        raise ValueError(
            "Alpaca extended-hours orders currently require time_in_force=DAY."
        )


def _alpaca_order_type(value: BrokerOrderType) -> str:
    mapping = {
        BrokerOrderType.MARKET: "market",
        BrokerOrderType.LIMIT: "limit",
        BrokerOrderType.STOP: "stop",
        BrokerOrderType.STOP_LIMIT: "stop_limit",
        BrokerOrderType.TRAILING_STOP: "trailing_stop",
    }
    try:
        return mapping[value]
    except KeyError as exc:  # pragma: no cover - enum exhaustiveness guard
        raise ValueError(f"Unsupported Alpaca order type: {value}") from exc


def _alpaca_time_in_force(value: BrokerTimeInForce) -> str:
    mapping = {
        BrokerTimeInForce.DAY: "day",
        BrokerTimeInForce.GOOD_TILL_CANCEL: "gtc",
    }
    try:
        return mapping[value]
    except KeyError as exc:  # pragma: no cover - enum exhaustiveness guard
        raise ValueError(f"Unsupported Alpaca time_in_force: {value}") from exc


def _map_order_side(value: Any) -> BrokerOrderSide | None:
    raw = _string_or_none(value)
    if raw is None:
        return None
    try:
        return BrokerOrderSide(raw.strip().upper())
    except ValueError:
        return None


def _map_order_type(value: Any) -> BrokerOrderType | None:
    raw = _string_or_none(value)
    if raw is None:
        return None
    normalized = raw.strip().lower()
    mapping = {
        "market": BrokerOrderType.MARKET,
        "limit": BrokerOrderType.LIMIT,
        "stop": BrokerOrderType.STOP,
        "stop_limit": BrokerOrderType.STOP_LIMIT,
        "trailing_stop": BrokerOrderType.TRAILING_STOP,
    }
    return mapping.get(normalized)


def _map_time_in_force(value: Any) -> BrokerTimeInForce | None:
    raw = _string_or_none(value)
    if raw is None:
        return None
    mapping = {
        "day": BrokerTimeInForce.DAY,
        "gtc": BrokerTimeInForce.GOOD_TILL_CANCEL,
        "ioc": BrokerTimeInForce.IMMEDIATE_OR_CANCEL,
        "fok": BrokerTimeInForce.FILL_OR_KILL,
        "opg": BrokerTimeInForce.MARKET_OPEN,
        "cls": BrokerTimeInForce.MARKET_CLOSE,
    }
    return mapping.get(raw.strip().lower())


def _map_order_status(value: Any) -> BrokerOrderStatus | None:
    raw = _string_or_none(value)
    if raw is None:
        return None
    mapping = {
        "accepted": BrokerOrderStatus.ACCEPTED,
        "accepted_for_bidding": BrokerOrderStatus.ACCEPTED_FOR_BIDDING,
        "new": BrokerOrderStatus.NEW,
        "pending_new": BrokerOrderStatus.PENDING_NEW,
        "partially_filled": BrokerOrderStatus.PARTIALLY_FILLED,
        "filled": BrokerOrderStatus.FILLED,
        "done_for_day": BrokerOrderStatus.DONE_FOR_DAY,
        "canceled": BrokerOrderStatus.CANCELLED,
        "cancelled": BrokerOrderStatus.CANCELLED,
        "expired": BrokerOrderStatus.EXPIRED,
        "replaced": BrokerOrderStatus.REPLACED,
        "pending_cancel": BrokerOrderStatus.PENDING_CANCEL,
        "pending_replace": BrokerOrderStatus.PENDING_REPLACE,
        "pending_review": BrokerOrderStatus.PENDING_NEW,
        "stopped": BrokerOrderStatus.STOPPED,
        "rejected": BrokerOrderStatus.REJECTED,
        "suspended": BrokerOrderStatus.SUSPENDED,
        "calculated": BrokerOrderStatus.CALCULATED,
    }
    return mapping.get(raw.strip().lower())


def _positive_decimal(value: str | int | float | Decimal, field_name: str) -> Decimal:
    resolved = _required_decimal(value, field_name)
    if resolved <= 0:
        raise ValueError(f"{field_name} must be greater than zero.")
    return resolved


def _required_decimal(
    value: str | int | float | Decimal | None,
    field_name: str,
) -> Decimal:
    if value is None or value == "":
        raise ValueError(f"{field_name} is required.")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a valid decimal number.") from exc


def _optional_decimal(value: str | int | float | Decimal | None) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    if raw in {"true", "1", "yes", "y", "on"}:
        return True
    if raw in {"false", "0", "no", "n", "off"}:
        return False
    return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    return raw or None


def _decimal_to_wire(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _sum_decimal(values) -> Decimal | None:
    total = Decimal("0")
    seen = False
    for value in values:
        if value is None:
            continue
        seen = True
        total += value
    return total if seen else None


def _parse_datetime(value: Any):
    from datetime import datetime, timezone

    raw = _string_or_none(value)
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _alpaca_client_order_id(fingerprint: str) -> str:
    return f"t212ai-{fingerprint}"
