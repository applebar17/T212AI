"""Protocols for Trading 212 broker adapters."""

from __future__ import annotations

from typing import Protocol

from t212ai.brokers.models import (
    BrokerHistoricalOrdersPage,
    BrokerInstrumentResolution,
    BrokerOrder,
    BrokerOrderActionResult,
    BrokerOrderSide,
    BrokerOrderType,
    BrokerPortfolioSnapshot,
    BrokerTimeInForce,
    PreparedBrokerOrder,
)

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
)


class Trading212ApiProtocol(Protocol):
    """1:1 interface over the Trading 212 Public API contract."""

    def get_account_summary(self) -> AccountSummary: ...

    def list_dividends(
        self,
        *,
        cursor: str | int | None = None,
        ticker: str | None = None,
        limit: int | None = None,
    ) -> PaginatedResponseHistoryDividendItem: ...

    def list_reports(self) -> list[ReportResponse]: ...

    def request_report(self, request: PublicReportRequest) -> EnqueuedReportResponse: ...

    def list_historical_orders(
        self,
        *,
        cursor: str | int | None = None,
        ticker: str | None = None,
        limit: int | None = None,
    ) -> PaginatedResponseHistoricalOrder: ...

    def list_transactions(
        self,
        *,
        cursor: str | int | None = None,
        time: str | None = None,
        limit: int | None = None,
    ) -> PaginatedResponseHistoryTransactionItem: ...

    def list_exchanges(self) -> list[Exchange]: ...

    def list_instruments(self) -> list[TradableInstrument]: ...

    def list_pending_orders(self) -> list[Order]: ...

    def place_limit_order(self, request: LimitRequest) -> Order: ...

    def place_market_order(self, request: MarketRequest) -> Order: ...

    def place_stop_order(self, request: StopRequest) -> Order: ...

    def place_stop_limit_order(self, request: StopLimitRequest) -> Order: ...

    def cancel_order(self, order_id: int) -> None: ...

    def get_order(self, order_id: int) -> Order: ...

    def list_historical_orders(
        self,
        *,
        cursor: str | int | None = None,
        ticker: str | None = None,
        limit: int | None = None,
    ) -> PaginatedResponseHistoricalOrder: ...

    def list_pies(self) -> list[AccountBucketResultResponse]: ...

    def create_pie(
        self,
        request: PieRequest,
    ) -> AccountBucketInstrumentsDetailedResponse: ...

    def delete_pie(self, pie_id: int) -> None: ...

    def get_pie(self, pie_id: int) -> AccountBucketInstrumentsDetailedResponse: ...

    def update_pie(
        self,
        pie_id: int,
        request: PieRequest,
    ) -> AccountBucketInstrumentsDetailedResponse: ...

    def duplicate_pie(
        self,
        pie_id: int,
        request: DuplicateBucketRequest,
    ) -> AccountBucketInstrumentsDetailedResponse: ...

    def list_positions(self, *, ticker: str | None = None) -> list[Position]: ...


class Trading212AgentBrokerProtocol(Protocol):
    """Smaller broker surface intended for commands, workflows, and tools."""

    def get_portfolio_snapshot(self) -> BrokerPortfolioSnapshot: ...

    def list_pending_orders(self) -> list[BrokerOrder]: ...

    def get_order(self, order_ref: str) -> BrokerOrder: ...

    def list_historical_orders(
        self,
        *,
        cursor: str | int | None = None,
        ticker: str | None = None,
        limit: int | None = None,
    ) -> BrokerHistoricalOrdersPage: ...

    def resolve_instrument(
        self,
        query: str,
        *,
        limit: int = 8,
    ) -> BrokerInstrumentResolution: ...

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
    ) -> PreparedBrokerOrder: ...

    def submit_prepared_order(
        self,
        prepared_order: PreparedBrokerOrder,
    ) -> BrokerOrderActionResult: ...

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
    ) -> BrokerOrderActionResult: ...

    def cancel_order(self, order_ref: str) -> BrokerOrderActionResult: ...
