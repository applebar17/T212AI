"""Agent-facing Trading 212 broker service."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any

from t212ai.brokers.models import (
    BrokerAccountSummary,
    BrokerCash,
    BrokerFill,
    BrokerFillWalletImpact,
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
    BrokerTax,
    BrokerTimeInForce,
    PreparedBrokerOrder,
)

from .models import (
    LimitRequest,
    MarketRequest,
    Order,
    StopLimitRequest,
    StopRequest,
    TimeValidity,
)
from .protocols import Trading212ApiProtocol


class Trading212BrokerService:
    """Composes low-level API calls into stable application operations."""

    provider_name = "trading212"

    def __init__(self, api: Trading212ApiProtocol) -> None:
        self.api = api

    def get_portfolio_snapshot(self) -> BrokerPortfolioSnapshot:
        return BrokerPortfolioSnapshot(
            account=_broker_account_summary(self.api.get_account_summary()),
            positions=[_broker_position(position) for position in self.api.list_positions()],
            pending_orders=[_broker_order(order) for order in self.api.list_pending_orders()],
        )

    def list_pending_orders(self) -> list[BrokerOrder]:
        return [_broker_order(order) for order in self.api.list_pending_orders()]

    def get_order(self, order_ref: str) -> BrokerOrder:
        return _broker_order(self.api.get_order(int(order_ref)))

    def list_historical_orders(
        self,
        *,
        cursor: str | int | None = None,
        ticker: str | None = None,
        limit: int | None = None,
    ) -> BrokerHistoricalOrdersPage:
        page = self.api.list_historical_orders(
            cursor=cursor,
            ticker=ticker,
            limit=limit,
        )
        return BrokerHistoricalOrdersPage(
            items=[
                BrokerHistoricalOrder(
                    fill=_broker_fill(item.fill) if item.fill is not None else None,
                    order=_broker_order(item.order) if item.order is not None else None,
                )
                for item in page.items
            ],
            next_page_path=page.next_page_path,
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
        resolved_ticker = _normalize_ticker(ticker)
        unsigned_quantity = _positive_decimal(quantity, "quantity")
        signed_quantity = (
            unsigned_quantity if resolved_side == BrokerOrderSide.BUY else -unsigned_quantity
        )
        warnings: list[str] = []

        if extended_hours and resolved_type != BrokerOrderType.MARKET:
            warnings.append("extended_hours is only supported for Trading 212 market orders.")

        request_payload = self._build_order_payload(
            order_type=resolved_type,
            ticker=resolved_ticker,
            signed_quantity=signed_quantity,
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force=resolved_time_in_force,
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
        return PreparedBrokerOrder(
            broker_provider="trading212",
            order_type=resolved_type,
            side=resolved_side,
            ticker=resolved_ticker,
            quantity=unsigned_quantity,
            signed_quantity=signed_quantity,
            limit_price=_optional_decimal(limit_price),
            stop_price=_optional_decimal(stop_price),
            time_in_force=resolved_time_in_force,
            extended_hours=bool(extended_hours),
            request_payload=request_payload,
            order_fingerprint=fingerprint,
            warnings=warnings,
        )

    def submit_prepared_order(
        self,
        prepared_order: PreparedBrokerOrder,
    ) -> BrokerOrderActionResult:
        order_type = prepared_order.order_type
        payload = prepared_order.request_payload
        if order_type == BrokerOrderType.MARKET:
            order = self.api.place_market_order(MarketRequest.model_validate(payload))
        elif order_type == BrokerOrderType.LIMIT:
            order = self.api.place_limit_order(LimitRequest.model_validate(payload))
        elif order_type == BrokerOrderType.STOP:
            order = self.api.place_stop_order(StopRequest.model_validate(payload))
        elif order_type == BrokerOrderType.STOP_LIMIT:
            order = self.api.place_stop_limit_order(StopLimitRequest.model_validate(payload))
        else:  # pragma: no cover - enum exhaustiveness guard
            raise ValueError(f"Unsupported order type: {order_type}")

        return BrokerOrderActionResult(
            broker_provider="trading212",
            action="submit_order",
            status=str(order.status or "submitted"),
            order_id=str(order.id) if order.id is not None else None,
            order=_broker_order(order),
            message="Order submitted to Trading 212.",
            raw_provider_payload=order.model_dump(mode="json", by_alias=True, exclude_none=True),
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
        resolved_order_id = int(order_ref)
        self.api.cancel_order(resolved_order_id)
        return BrokerOrderActionResult(
            broker_provider="trading212",
            action="cancel_order",
            status="accepted",
            order_id=str(resolved_order_id),
            message="Cancellation request accepted by Trading 212.",
        )

    def _build_order_payload(
        self,
        *,
        order_type: BrokerOrderType,
        ticker: str,
        signed_quantity: Decimal,
        limit_price: str | int | float | None,
        stop_price: str | int | float | None,
        time_in_force: BrokerTimeInForce,
        extended_hours: bool,
    ) -> dict[str, Any]:
        if order_type == BrokerOrderType.MARKET:
            return MarketRequest(
                ticker=ticker,
                quantity=signed_quantity,
                extended_hours=bool(extended_hours),
            ).to_api_dict()
        if order_type == BrokerOrderType.LIMIT:
            return LimitRequest(
                ticker=ticker,
                quantity=signed_quantity,
                limit_price=_required_decimal(limit_price, "limit_price"),
                time_validity=_trading212_time_in_force(time_in_force),
            ).to_api_dict()
        if order_type == BrokerOrderType.STOP:
            return StopRequest(
                ticker=ticker,
                quantity=signed_quantity,
                stop_price=_required_decimal(stop_price, "stop_price"),
                time_validity=_trading212_time_in_force(time_in_force),
            ).to_api_dict()
        if order_type == BrokerOrderType.STOP_LIMIT:
            return StopLimitRequest(
                ticker=ticker,
                quantity=signed_quantity,
                limit_price=_required_decimal(limit_price, "limit_price"),
                stop_price=_required_decimal(stop_price, "stop_price"),
                time_validity=_trading212_time_in_force(time_in_force),
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


def _optional_decimal(value: str | int | float | Decimal | None) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _trading212_time_in_force(value: BrokerTimeInForce) -> TimeValidity:
    return TimeValidity(value.value)


def _fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _broker_account_summary(account) -> BrokerAccountSummary:
    return BrokerAccountSummary(
        cash=(
            BrokerCash.model_validate(
                account.cash.model_dump(by_alias=True, exclude_none=True, mode="json")
            )
            if account.cash is not None
            else None
        ),
        currency=account.currency,
        id=str(account.id) if account.id is not None else None,
        investments=(
            BrokerInvestments.model_validate(
                account.investments.model_dump(by_alias=True, exclude_none=True, mode="json")
            )
            if account.investments is not None
            else None
        ),
        total_value=account.total_value,
    )


def _broker_instrument(instrument) -> BrokerInstrument | None:
    if instrument is None:
        return None
    return BrokerInstrument.model_validate(
        instrument.model_dump(by_alias=True, exclude_none=True, mode="json")
    )


def _broker_tax(tax) -> BrokerTax:
    return BrokerTax.model_validate(tax.model_dump(by_alias=True, exclude_none=True, mode="json"))


def _broker_fill_wallet_impact(wallet) -> BrokerFillWalletImpact | None:
    if wallet is None:
        return None
    return BrokerFillWalletImpact(
        currency=wallet.currency,
        fx_rate=wallet.fx_rate,
        net_value=wallet.net_value,
        realised_profit_loss=wallet.realised_profit_loss,
        taxes=[_broker_tax(tax) for tax in wallet.taxes],
    )


def _broker_fill(fill) -> BrokerFill | None:
    if fill is None:
        return None
    return BrokerFill(
        filled_at=fill.filled_at,
        id=str(fill.id) if fill.id is not None else None,
        price=fill.price,
        quantity=fill.quantity,
        trading_method=fill.trading_method,
        type=fill.type,
        wallet_impact=_broker_fill_wallet_impact(fill.wallet_impact),
    )


def _broker_order(order: Order) -> BrokerOrder:
    return BrokerOrder(
        created_at=order.created_at,
        currency=order.currency,
        extended_hours=order.extended_hours,
        filled_quantity=order.filled_quantity,
        filled_value=order.filled_value,
        id=str(order.id) if order.id is not None else None,
        initiated_from=order.initiated_from,
        instrument=_broker_instrument(order.instrument),
        limit_price=order.limit_price,
        quantity=order.quantity,
        side=BrokerOrderSide(order.side.value) if order.side is not None else None,
        status=BrokerOrderStatus(order.status.value) if order.status is not None else None,
        stop_price=order.stop_price,
        strategy=str(order.strategy.value) if order.strategy is not None else None,
        ticker=order.ticker,
        time_in_force=(
            BrokerTimeInForce(order.time_in_force.value)
            if order.time_in_force is not None
            else None
        ),
        type=BrokerOrderType(order.type.value) if order.type is not None else None,
        value=order.value,
        raw_provider_payload=order.model_dump(by_alias=True, exclude_none=True, mode="json"),
    )


def _broker_position(position) -> BrokerPosition:
    return BrokerPosition(
        average_price_paid=position.average_price_paid,
        created_at=position.created_at,
        current_price=position.current_price,
        instrument=_broker_instrument(position.instrument),
        quantity=position.quantity,
        quantity_available_for_trading=position.quantity_available_for_trading,
        quantity_in_pies=position.quantity_in_pies,
        wallet_impact=(
            BrokerPositionWalletImpact.model_validate(
                position.wallet_impact.model_dump(by_alias=True, exclude_none=True, mode="json")
            )
            if position.wallet_impact is not None
            else None
        ),
    )
