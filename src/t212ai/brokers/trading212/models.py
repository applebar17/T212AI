"""Trading 212 API and agent-facing domain models."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class Trading212Model(BaseModel):
    """Base model for Trading 212 API payloads.

    The API uses camelCase. Internally we keep snake_case and preserve aliases
    for request/response serialization.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    @field_serializer("*", when_used="json", check_fields=False)
    def _serialize_json_value(self, value: Any) -> Any:
        return _json_safe(value)

    def to_api_dict(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=True, mode="json")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_json_safe(item) for item in value]
    return value


class TimeValidity(StrEnum):
    DAY = "DAY"
    GOOD_TILL_CANCEL = "GOOD_TILL_CANCEL"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(StrEnum):
    LOCAL = "LOCAL"
    UNCONFIRMED = "UNCONFIRMED"
    CONFIRMED = "CONFIRMED"
    NEW = "NEW"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    REPLACING = "REPLACING"
    REPLACED = "REPLACED"


class OrderType(StrEnum):
    LIMIT = "LIMIT"
    STOP = "STOP"
    MARKET = "MARKET"
    STOP_LIMIT = "STOP_LIMIT"


class OrderStrategy(StrEnum):
    QUANTITY = "QUANTITY"
    VALUE = "VALUE"


class InstrumentType(StrEnum):
    CRYPTOCURRENCY = "CRYPTOCURRENCY"
    ETF = "ETF"
    FOREX = "FOREX"
    FUTURES = "FUTURES"
    INDEX = "INDEX"
    STOCK = "STOCK"
    WARRANT = "WARRANT"
    CRYPTO = "CRYPTO"
    CVR = "CVR"
    CORPACT = "CORPACT"


class AccountCurrencyAction(StrEnum):
    REINVEST = "REINVEST"
    TO_ACCOUNT_CASH = "TO_ACCOUNT_CASH"


class Cash(Trading212Model):
    available_to_trade: Decimal | None = Field(default=None, alias="availableToTrade")
    in_pies: Decimal | None = Field(default=None, alias="inPies")
    reserved_for_orders: Decimal | None = Field(default=None, alias="reservedForOrders")


class Investments(Trading212Model):
    current_value: Decimal | None = Field(default=None, alias="currentValue")
    realized_profit_loss: Decimal | None = Field(default=None, alias="realizedProfitLoss")
    total_cost: Decimal | None = Field(default=None, alias="totalCost")
    unrealized_profit_loss: Decimal | None = Field(default=None, alias="unrealizedProfitLoss")


class AccountSummary(Trading212Model):
    cash: Cash | None = None
    currency: str | None = None
    id: int | None = None
    investments: Investments | None = None
    total_value: Decimal | None = Field(default=None, alias="totalValue")


class Instrument(Trading212Model):
    currency: str | None = None
    isin: str | None = None
    name: str | None = None
    ticker: str | None = None


class Tax(Trading212Model):
    charged_at: datetime | None = Field(default=None, alias="chargedAt")
    currency: str | None = None
    name: str | None = None
    quantity: Decimal | None = None


class FillWalletImpact(Trading212Model):
    currency: str | None = None
    fx_rate: Decimal | None = Field(default=None, alias="fxRate")
    net_value: Decimal | None = Field(default=None, alias="netValue")
    realised_profit_loss: Decimal | None = Field(default=None, alias="realisedProfitLoss")
    taxes: list[Tax] = Field(default_factory=list)


class Fill(Trading212Model):
    filled_at: datetime | None = Field(default=None, alias="filledAt")
    id: int | None = None
    price: Decimal | None = None
    quantity: Decimal | None = None
    trading_method: str | None = Field(default=None, alias="tradingMethod")
    type: str | None = None
    wallet_impact: FillWalletImpact | None = Field(default=None, alias="walletImpact")


class Order(Trading212Model):
    created_at: datetime | None = Field(default=None, alias="createdAt")
    currency: str | None = None
    extended_hours: bool | None = Field(default=None, alias="extendedHours")
    filled_quantity: Decimal | None = Field(default=None, alias="filledQuantity")
    filled_value: Decimal | None = Field(default=None, alias="filledValue")
    id: int | None = None
    initiated_from: str | None = Field(default=None, alias="initiatedFrom")
    instrument: Instrument | None = None
    limit_price: Decimal | None = Field(default=None, alias="limitPrice")
    quantity: Decimal | None = None
    side: OrderSide | None = None
    status: OrderStatus | None = None
    stop_price: Decimal | None = Field(default=None, alias="stopPrice")
    strategy: OrderStrategy | None = None
    ticker: str | None = None
    time_in_force: TimeValidity | None = Field(default=None, alias="timeInForce")
    type: OrderType | None = None
    value: Decimal | None = None


class HistoricalOrder(Trading212Model):
    fill: Fill | None = None
    order: Order | None = None


class HistoryDividendItem(Trading212Model):
    amount: Decimal | None = None
    amount_in_euro: Decimal | None = Field(default=None, alias="amountInEuro")
    currency: str | None = None
    gross_amount_per_share: Decimal | None = Field(default=None, alias="grossAmountPerShare")
    instrument: Instrument | None = None
    paid_on: datetime | None = Field(default=None, alias="paidOn")
    quantity: Decimal | None = None
    reference: str | None = None
    ticker: str | None = None
    ticker_currency: str | None = Field(default=None, alias="tickerCurrency")
    type: str | None = None


class HistoryTransactionItem(Trading212Model):
    amount: Decimal | None = None
    currency: str | None = None
    date_time: datetime | None = Field(default=None, alias="dateTime")
    reference: str | None = None
    type: str | None = None


class TimeEvent(Trading212Model):
    date: datetime | None = None
    type: str | None = None


class WorkingSchedule(Trading212Model):
    id: int | None = None
    time_events: list[TimeEvent] = Field(default_factory=list, alias="timeEvents")


class Exchange(Trading212Model):
    id: int | None = None
    name: str | None = None
    working_schedules: list[WorkingSchedule] = Field(default_factory=list, alias="workingSchedules")


class TradableInstrument(Trading212Model):
    added_on: datetime | None = Field(default=None, alias="addedOn")
    currency_code: str | None = Field(default=None, alias="currencyCode")
    extended_hours: bool | None = Field(default=None, alias="extendedHours")
    isin: str | None = None
    max_open_quantity: Decimal | None = Field(default=None, alias="maxOpenQuantity")
    name: str | None = None
    short_name: str | None = Field(default=None, alias="shortName")
    ticker: str | None = None
    type: InstrumentType | None = None
    working_schedule_id: int | None = Field(default=None, alias="workingScheduleId")


class PositionWalletImpact(Trading212Model):
    currency: str | None = None
    current_value: Decimal | None = Field(default=None, alias="currentValue")
    fx_impact: Decimal | None = Field(default=None, alias="fxImpact")
    total_cost: Decimal | None = Field(default=None, alias="totalCost")
    unrealized_profit_loss: Decimal | None = Field(default=None, alias="unrealizedProfitLoss")


class Position(Trading212Model):
    average_price_paid: Decimal | None = Field(default=None, alias="averagePricePaid")
    created_at: datetime | None = Field(default=None, alias="createdAt")
    current_price: Decimal | None = Field(default=None, alias="currentPrice")
    instrument: Instrument | None = None
    quantity: Decimal | None = None
    quantity_available_for_trading: Decimal | None = Field(
        default=None, alias="quantityAvailableForTrading"
    )
    quantity_in_pies: Decimal | None = Field(default=None, alias="quantityInPies")
    wallet_impact: PositionWalletImpact | None = Field(default=None, alias="walletImpact")


class LimitRequest(Trading212Model):
    limit_price: Decimal = Field(alias="limitPrice")
    quantity: Decimal
    ticker: str
    time_validity: TimeValidity = Field(alias="timeValidity")


class MarketRequest(Trading212Model):
    extended_hours: bool = Field(default=False, alias="extendedHours")
    quantity: Decimal
    ticker: str


class StopRequest(Trading212Model):
    quantity: Decimal
    stop_price: Decimal = Field(alias="stopPrice")
    ticker: str
    time_validity: TimeValidity = Field(alias="timeValidity")


class StopLimitRequest(Trading212Model):
    limit_price: Decimal = Field(alias="limitPrice")
    quantity: Decimal
    stop_price: Decimal = Field(alias="stopPrice")
    ticker: str
    time_validity: TimeValidity = Field(alias="timeValidity")


class ReportDataIncluded(Trading212Model):
    include_dividends: bool | None = Field(default=None, alias="includeDividends")
    include_interest: bool | None = Field(default=None, alias="includeInterest")
    include_orders: bool | None = Field(default=None, alias="includeOrders")
    include_transactions: bool | None = Field(default=None, alias="includeTransactions")


class PublicReportRequest(Trading212Model):
    data_included: ReportDataIncluded = Field(alias="dataIncluded")
    time_from: datetime = Field(alias="timeFrom")
    time_to: datetime = Field(alias="timeTo")


class EnqueuedReportResponse(Trading212Model):
    report_id: int | None = Field(default=None, alias="reportId")


class ReportResponse(Trading212Model):
    data_included: ReportDataIncluded | None = Field(default=None, alias="dataIncluded")
    download_link: str | None = Field(default=None, alias="downloadLink")
    report_id: int | None = Field(default=None, alias="reportId")
    status: str | None = None
    time_from: datetime | None = Field(default=None, alias="timeFrom")
    time_to: datetime | None = Field(default=None, alias="timeTo")


class DividendDetails(Trading212Model):
    gained: Decimal | None = None
    in_cash: Decimal | None = Field(default=None, alias="inCash")
    reinvested: Decimal | None = None


class InvestmentResult(Trading212Model):
    price_avg_invested_value: Decimal | None = Field(default=None, alias="priceAvgInvestedValue")
    price_avg_result: Decimal | None = Field(default=None, alias="priceAvgResult")
    price_avg_result_coef: Decimal | None = Field(default=None, alias="priceAvgResultCoef")
    price_avg_value: Decimal | None = Field(default=None, alias="priceAvgValue")


class InstrumentIssue(Trading212Model):
    name: str | None = None
    severity: str | None = None


class AccountBucketDetailedResponse(Trading212Model):
    creation_date: datetime | None = Field(default=None, alias="creationDate")
    dividend_cash_action: AccountCurrencyAction | None = Field(
        default=None, alias="dividendCashAction"
    )
    end_date: datetime | None = Field(default=None, alias="endDate")
    goal: Decimal | None = None
    icon: str | None = None
    id: int | None = None
    initial_investment: Decimal | None = Field(default=None, alias="initialInvestment")
    instrument_shares: dict[str, Decimal] = Field(default_factory=dict, alias="instrumentShares")
    name: str | None = None
    public_url: str | None = Field(default=None, alias="publicUrl")


class AccountBucketInstrumentResult(Trading212Model):
    current_share: Decimal | None = Field(default=None, alias="currentShare")
    expected_share: Decimal | None = Field(default=None, alias="expectedShare")
    issues: list[InstrumentIssue] = Field(default_factory=list)
    owned_quantity: Decimal | None = Field(default=None, alias="ownedQuantity")
    result: InvestmentResult | None = None
    ticker: str | None = None


class AccountBucketInstrumentsDetailedResponse(Trading212Model):
    instruments: list[AccountBucketInstrumentResult] = Field(default_factory=list)
    settings: AccountBucketDetailedResponse | None = None


class AccountBucketResultResponse(Trading212Model):
    cash: Decimal | None = None
    dividend_details: DividendDetails | None = Field(default=None, alias="dividendDetails")
    id: int | None = None
    progress: Decimal | None = None
    result: InvestmentResult | None = None
    status: str | None = None


class DuplicateBucketRequest(Trading212Model):
    icon: str | None = None
    name: str


class PieRequest(Trading212Model):
    dividend_cash_action: AccountCurrencyAction | None = Field(
        default=None, alias="dividendCashAction"
    )
    end_date: datetime | None = Field(default=None, alias="endDate")
    goal: Decimal | None = None
    icon: str | None = None
    instrument_shares: dict[str, Decimal] = Field(default_factory=dict, alias="instrumentShares")
    name: str


class PaginatedResponseHistoryDividendItem(Trading212Model):
    items: list[HistoryDividendItem] = Field(default_factory=list)
    next_page_path: str | None = Field(default=None, alias="nextPagePath")


class PaginatedResponseHistoricalOrder(Trading212Model):
    items: list[HistoricalOrder] = Field(default_factory=list)
    next_page_path: str | None = Field(default=None, alias="nextPagePath")


class PaginatedResponseHistoryTransactionItem(Trading212Model):
    items: list[HistoryTransactionItem] = Field(default_factory=list)
    next_page_path: str | None = Field(default=None, alias="nextPagePath")


class PortfolioSnapshot(Trading212Model):
    as_of: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), alias="asOf")
    account: AccountSummary
    positions: list[Position] = Field(default_factory=list)
    pending_orders: list[Order] = Field(default_factory=list, alias="pendingOrders")


class PreparedOrder(Trading212Model):
    order_type: OrderType = Field(alias="orderType")
    side: OrderSide
    ticker: str
    signed_quantity: Decimal = Field(alias="signedQuantity")
    request_payload: dict[str, Any] = Field(alias="requestPayload")
    order_fingerprint: str = Field(alias="orderFingerprint")
    warnings: list[str] = Field(default_factory=list)


class OrderActionResult(Trading212Model):
    action: str
    status: str
    order_id: int | None = Field(default=None, alias="orderId")
    order: Order | None = None
    message: str | None = None
