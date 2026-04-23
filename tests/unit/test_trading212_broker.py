from __future__ import annotations

from decimal import Decimal

from t212ai.brokers.trading212.client import Trading212Client
from t212ai.brokers.trading212.models import (
    AccountSummary,
    Cash,
    Instrument,
    Investments,
    LimitRequest,
    MarketRequest,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    PositionWalletImpact,
    TimeValidity,
)
from t212ai.brokers.trading212.service import Trading212BrokerService
from t212ai.brokers.trading212.tools import (
    Trading212ToolRuntime,
    t212_get_portfolio_snapshot,
    t212_place_order,
    t212_prepare_order,
)


class FakeTrading212Api:
    def __init__(self) -> None:
        self.placed_market_orders: list[MarketRequest] = []
        self.placed_limit_orders: list[LimitRequest] = []
        self.cancelled_order_ids: list[int] = []

    def get_account_summary(self) -> AccountSummary:
        return AccountSummary(
            id=1,
            currency="EUR",
            cash=Cash(available_to_trade=Decimal("1000")),
            investments=Investments(current_value=Decimal("2500")),
            total_value=Decimal("3500"),
        )

    def list_positions(self, *, ticker: str | None = None) -> list[Position]:
        position = Position(
            instrument=Instrument(ticker="AAPL_US_EQ", name="Apple", currency="USD"),
            quantity=Decimal("2"),
            current_price=Decimal("200"),
            wallet_impact=PositionWalletImpact(
                currency="EUR",
                current_value=Decimal("400"),
                total_cost=Decimal("300"),
                unrealized_profit_loss=Decimal("100"),
            ),
        )
        if ticker and ticker != position.instrument.ticker:
            return []
        return [position]

    def list_pending_orders(self) -> list[Order]:
        return [
            Order(
                id=10,
                ticker="MSFT_US_EQ",
                quantity=Decimal("1"),
                side=OrderSide.BUY,
                status=OrderStatus.NEW,
                type=OrderType.MARKET,
            )
        ]

    def get_order(self, order_id: int) -> Order:
        return Order(id=order_id, ticker="MSFT_US_EQ", status=OrderStatus.NEW)

    def place_market_order(self, request: MarketRequest) -> Order:
        self.placed_market_orders.append(request)
        return Order(
            id=123,
            ticker=request.ticker,
            quantity=request.quantity,
            status=OrderStatus.NEW,
            type=OrderType.MARKET,
        )

    def place_limit_order(self, request: LimitRequest) -> Order:
        self.placed_limit_orders.append(request)
        return Order(
            id=124,
            ticker=request.ticker,
            quantity=request.quantity,
            limit_price=request.limit_price,
            status=OrderStatus.NEW,
            type=OrderType.LIMIT,
        )

    def cancel_order(self, order_id: int) -> None:
        self.cancelled_order_ids.append(order_id)


class FailingSnapshotApi(FakeTrading212Api):
    def get_account_summary(self) -> AccountSummary:
        raise RuntimeError("missing portfolio scope")


def test_request_models_serialize_decimal_numbers_for_api() -> None:
    request = LimitRequest(
        ticker="AAPL_US_EQ",
        quantity=Decimal("0.1"),
        limit_price=Decimal("100.23"),
        time_validity=TimeValidity.DAY,
    )

    payload = request.to_api_dict()

    assert payload == {
        "ticker": "AAPL_US_EQ",
        "quantity": 0.1,
        "limitPrice": 100.23,
        "timeValidity": "DAY",
    }


def test_client_does_not_duplicate_api_prefix_in_urls() -> None:
    client = Trading212Client(
        base_url="https://demo.trading212.com/api/v0",
        api_key="key",
        api_secret="secret",
    )

    url = client._build_url(  # noqa: SLF001
        "/api/v0/equity/orders",
        query={"ticker": "AAPL_US_EQ", "cursor": None},
    )

    assert url == "https://demo.trading212.com/api/v0/equity/orders?ticker=AAPL_US_EQ"


def test_portfolio_snapshot_composes_account_positions_and_orders() -> None:
    service = Trading212BrokerService(FakeTrading212Api())

    snapshot = service.get_portfolio_snapshot()

    assert snapshot.account.currency == "EUR"
    assert len(snapshot.positions) == 1
    assert len(snapshot.pending_orders) == 1


def test_portfolio_snapshot_tool_returns_llm_readable_context() -> None:
    service = Trading212BrokerService(FakeTrading212Api())
    runtime = Trading212ToolRuntime(service=service)

    result = t212_get_portfolio_snapshot(runtime=runtime)

    assert result.status == "ok"
    assert result.output is not None
    assert "broker-authoritative" in result.output
    assert "available_to_trade=1000 EUR" in result.output
    assert "AAPL_US_EQ (Apple)" in result.output
    assert "Pending orders: 1 active/pending order(s)." in result.output
    assert result.data["account"]["currency"] == "EUR"


def test_portfolio_snapshot_tool_returns_actionable_error_context() -> None:
    service = Trading212BrokerService(FailingSnapshotApi())
    runtime = Trading212ToolRuntime(service=service)

    result = t212_get_portfolio_snapshot(runtime=runtime)

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "broker_snapshot_failed"
    assert "Unable to retrieve" in result.error.message
    assert result.error.hint is not None
    assert "Do not infer broker state" in result.error.hint


def test_prepare_sell_limit_order_builds_signed_payload_and_fingerprint() -> None:
    service = Trading212BrokerService(FakeTrading212Api())

    prepared = service.prepare_order(
        order_type="LIMIT",
        side="SELL",
        ticker="aapl_us_eq",
        quantity="2.5",
        limit_price="150.25",
    )

    assert prepared.ticker == "AAPL_US_EQ"
    assert prepared.signed_quantity == Decimal("-2.5")
    assert prepared.request_payload["quantity"] == -2.5
    assert prepared.request_payload["limitPrice"] == 150.25
    assert len(prepared.order_fingerprint) == 16


def test_execution_tool_requires_state_change_runtime_and_matching_fingerprint() -> None:
    api = FakeTrading212Api()
    service = Trading212BrokerService(api)
    read_runtime = Trading212ToolRuntime(service=service, allow_state_changes=False)
    execution_runtime = Trading212ToolRuntime(service=service, allow_state_changes=True)

    prepared_result = t212_prepare_order(
        order_type="MARKET",
        side="BUY",
        ticker="AAPL_US_EQ",
        quantity="1",
        limit_price=None,
        stop_price=None,
        time_validity="DAY",
        extended_hours=False,
        runtime=read_runtime,
    )
    fingerprint = prepared_result.data["orderFingerprint"]

    disabled_result = t212_place_order(
        order_type="MARKET",
        side="BUY",
        ticker="AAPL_US_EQ",
        quantity="1",
        limit_price=None,
        stop_price=None,
        time_validity="DAY",
        extended_hours=False,
        confirmed=True,
        confirmation_reference=fingerprint,
        runtime=read_runtime,
    )
    mismatch_result = t212_place_order(
        order_type="MARKET",
        side="BUY",
        ticker="AAPL_US_EQ",
        quantity="1",
        limit_price=None,
        stop_price=None,
        time_validity="DAY",
        extended_hours=False,
        confirmed=True,
        confirmation_reference="wrong",
        runtime=execution_runtime,
    )
    ok_result = t212_place_order(
        order_type="MARKET",
        side="BUY",
        ticker="AAPL_US_EQ",
        quantity="1",
        limit_price=None,
        stop_price=None,
        time_validity="DAY",
        extended_hours=False,
        confirmed=True,
        confirmation_reference=fingerprint,
        runtime=execution_runtime,
    )

    assert disabled_result.status == "error"
    assert disabled_result.error is not None
    assert disabled_result.error.code == "state_changes_disabled"
    assert mismatch_result.status == "error"
    assert mismatch_result.error is not None
    assert mismatch_result.error.code == "fingerprint_mismatch"
    assert ok_result.status == "ok"
    assert len(api.placed_market_orders) == 1
