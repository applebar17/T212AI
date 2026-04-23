"""Protocols for Trading 212 broker adapters."""

from __future__ import annotations

from typing import Protocol

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
    OrderActionResult,
    OrderSide,
    OrderType,
    PaginatedResponseHistoricalOrder,
    PaginatedResponseHistoryDividendItem,
    PaginatedResponseHistoryTransactionItem,
    PieRequest,
    PortfolioSnapshot,
    Position,
    PreparedOrder,
    PublicReportRequest,
    ReportResponse,
    StopLimitRequest,
    StopRequest,
    TimeValidity,
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

    def get_portfolio_snapshot(self) -> PortfolioSnapshot: ...

    def list_pending_orders(self) -> list[Order]: ...

    def get_order(self, order_id: int) -> Order: ...

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
    ) -> PreparedOrder: ...

    def submit_prepared_order(self, prepared_order: PreparedOrder) -> OrderActionResult: ...

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
    ) -> OrderActionResult: ...

    def cancel_order(self, order_id: int) -> OrderActionResult: ...
