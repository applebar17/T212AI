"""Broker-agnostic domain models used by orchestration and capabilities."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_serializer


class BrokerModel(BaseModel):
    """Base model for generic broker payloads."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    @field_serializer("*", when_used="json", check_fields=False)
    def _serialize_json_value(self, value: Any) -> Any:
        return _json_safe(value)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_json_safe(item) for item in value]
    return value


class BrokerTimeInForce(StrEnum):
    DAY = "DAY"
    GOOD_TILL_CANCEL = "GOOD_TILL_CANCEL"
    IMMEDIATE_OR_CANCEL = "IMMEDIATE_OR_CANCEL"
    FILL_OR_KILL = "FILL_OR_KILL"
    MARKET_OPEN = "MARKET_OPEN"
    MARKET_CLOSE = "MARKET_CLOSE"


class BrokerOrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class BrokerOrderStatus(StrEnum):
    LOCAL = "LOCAL"
    UNCONFIRMED = "UNCONFIRMED"
    CONFIRMED = "CONFIRMED"
    NEW = "NEW"
    CANCELLING = "CANCELLING"
    PENDING_CANCEL = "PENDING_CANCEL"
    CANCELLED = "CANCELLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    REPLACING = "REPLACING"
    PENDING_REPLACE = "PENDING_REPLACE"
    REPLACED = "REPLACED"
    ACCEPTED = "ACCEPTED"
    ACCEPTED_FOR_BIDDING = "ACCEPTED_FOR_BIDDING"
    PENDING_NEW = "PENDING_NEW"
    DONE_FOR_DAY = "DONE_FOR_DAY"
    EXPIRED = "EXPIRED"
    STOPPED = "STOPPED"
    SUSPENDED = "SUSPENDED"
    CALCULATED = "CALCULATED"


class BrokerOrderType(StrEnum):
    LIMIT = "LIMIT"
    STOP = "STOP"
    MARKET = "MARKET"
    STOP_LIMIT = "STOP_LIMIT"
    TRAILING_STOP = "TRAILING_STOP"


class BrokerOrderAction(StrEnum):
    PREPARE_SUBMIT_ORDER = "prepare_submit_order"
    PREPARE_CANCEL_ORDER = "prepare_cancel_order"


class BrokerCancelTargetSelector(StrEnum):
    LATEST = "latest"
    OLDEST = "oldest"
    ONLY = "only"


class BrokerCash(BrokerModel):
    available_to_trade: Decimal | None = Field(default=None, alias="availableToTrade")
    in_pies: Decimal | None = Field(default=None, alias="inPies")
    reserved_for_orders: Decimal | None = Field(default=None, alias="reservedForOrders")


class BrokerInvestments(BrokerModel):
    current_value: Decimal | None = Field(default=None, alias="currentValue")
    realized_profit_loss: Decimal | None = Field(default=None, alias="realizedProfitLoss")
    total_cost: Decimal | None = Field(default=None, alias="totalCost")
    unrealized_profit_loss: Decimal | None = Field(default=None, alias="unrealizedProfitLoss")


class BrokerAccountSummary(BrokerModel):
    cash: BrokerCash | None = None
    currency: str | None = None
    id: str | None = None
    investments: BrokerInvestments | None = None
    total_value: Decimal | None = Field(default=None, alias="totalValue")


class BrokerInstrument(BrokerModel):
    currency: str | None = None
    isin: str | None = None
    name: str | None = None
    ticker: str | None = None


class BrokerTax(BrokerModel):
    charged_at: datetime | None = Field(default=None, alias="chargedAt")
    currency: str | None = None
    name: str | None = None
    quantity: Decimal | None = None


class BrokerFillWalletImpact(BrokerModel):
    currency: str | None = None
    fx_rate: Decimal | None = Field(default=None, alias="fxRate")
    net_value: Decimal | None = Field(default=None, alias="netValue")
    realised_profit_loss: Decimal | None = Field(default=None, alias="realisedProfitLoss")
    taxes: list[BrokerTax] = Field(default_factory=list)


class BrokerFill(BrokerModel):
    filled_at: datetime | None = Field(default=None, alias="filledAt")
    id: str | None = None
    price: Decimal | None = None
    quantity: Decimal | None = None
    trading_method: str | None = Field(default=None, alias="tradingMethod")
    type: str | None = None
    wallet_impact: BrokerFillWalletImpact | None = Field(default=None, alias="walletImpact")


class BrokerOrder(BrokerModel):
    created_at: datetime | None = Field(default=None, alias="createdAt")
    currency: str | None = None
    extended_hours: bool | None = Field(default=None, alias="extendedHours")
    filled_quantity: Decimal | None = Field(default=None, alias="filledQuantity")
    filled_value: Decimal | None = Field(default=None, alias="filledValue")
    id: str | None = None
    initiated_from: str | None = Field(default=None, alias="initiatedFrom")
    instrument: BrokerInstrument | None = None
    limit_price: Decimal | None = Field(default=None, alias="limitPrice")
    quantity: Decimal | None = None
    side: BrokerOrderSide | None = None
    status: BrokerOrderStatus | None = None
    stop_price: Decimal | None = Field(default=None, alias="stopPrice")
    strategy: str | None = None
    ticker: str | None = None
    time_in_force: BrokerTimeInForce | None = Field(default=None, alias="timeInForce")
    type: BrokerOrderType | None = None
    value: Decimal | None = None
    raw_provider_payload: dict[str, Any] | None = Field(default=None, alias="rawProviderPayload")


class BrokerHistoricalOrder(BrokerModel):
    fill: BrokerFill | None = None
    order: BrokerOrder | None = None


class BrokerHistoricalOrdersPage(BrokerModel):
    items: list[BrokerHistoricalOrder] = Field(default_factory=list)
    next_page_path: str | None = Field(default=None, alias="nextPagePath")


class BrokerPositionWalletImpact(BrokerModel):
    currency: str | None = None
    current_value: Decimal | None = Field(default=None, alias="currentValue")
    fx_impact: Decimal | None = Field(default=None, alias="fxImpact")
    total_cost: Decimal | None = Field(default=None, alias="totalCost")
    unrealized_profit_loss: Decimal | None = Field(default=None, alias="unrealizedProfitLoss")


class BrokerPosition(BrokerModel):
    average_price_paid: Decimal | None = Field(default=None, alias="averagePricePaid")
    created_at: datetime | None = Field(default=None, alias="createdAt")
    current_price: Decimal | None = Field(default=None, alias="currentPrice")
    instrument: BrokerInstrument | None = None
    quantity: Decimal | None = None
    quantity_available_for_trading: Decimal | None = Field(
        default=None,
        alias="quantityAvailableForTrading",
    )
    quantity_in_pies: Decimal | None = Field(default=None, alias="quantityInPies")
    wallet_impact: BrokerPositionWalletImpact | None = Field(default=None, alias="walletImpact")


class BrokerPortfolioSnapshot(BrokerModel):
    as_of: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), alias="asOf")
    account: BrokerAccountSummary
    positions: list[BrokerPosition] = Field(default_factory=list)
    pending_orders: list[BrokerOrder] = Field(default_factory=list, alias="pendingOrders")


class PreparedBrokerOrder(BrokerModel):
    broker_provider: str = Field(alias="brokerProvider")
    order_type: BrokerOrderType = Field(alias="orderType")
    side: BrokerOrderSide
    ticker: str
    quantity: Decimal = Field(alias="quantity")
    signed_quantity: Decimal = Field(alias="signedQuantity")
    limit_price: Decimal | None = Field(default=None, alias="limitPrice")
    stop_price: Decimal | None = Field(default=None, alias="stopPrice")
    time_in_force: BrokerTimeInForce = Field(alias="timeInForce")
    extended_hours: bool = Field(default=False, alias="extendedHours")
    request_payload: dict[str, Any] = Field(alias="requestPayload")
    order_fingerprint: str = Field(alias="orderFingerprint")
    warnings: list[str] = Field(default_factory=list)


class BrokerOrderActionResult(BrokerModel):
    broker_provider: str = Field(alias="brokerProvider")
    action: str
    status: str
    order_id: str | None = Field(default=None, alias="orderId")
    order: BrokerOrder | None = None
    message: str | None = None
    raw_provider_payload: dict[str, Any] | None = Field(default=None, alias="rawProviderPayload")


class BrokerOrderActionRequest(BrokerModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    action: BrokerOrderAction
    order_type: str | None = None
    side: str | None = None
    ticker: str | None = None
    quantity: str | int | float | None = None
    limit_price: str | int | float | None = None
    stop_price: str | int | float | None = None
    time_in_force: str = Field(
        default="DAY",
        validation_alias=AliasChoices("time_in_force", "time_validity"),
    )
    extended_hours: bool = False
    target_order_ref: str | None = Field(
        default=None,
        validation_alias=AliasChoices("target_order_ref", "target_order_id"),
    )
    cancel_selector: BrokerCancelTargetSelector | None = None
    reason: str | None = None
    thesis: str | None = None
    risks: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
