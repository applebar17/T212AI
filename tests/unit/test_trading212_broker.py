from __future__ import annotations

from decimal import Decimal

import pytest

from t212ai.brokers.models import (
    BrokerOrderSide,
    BrokerOrderType,
    BrokerTimeInForce,
    PreparedBrokerOrder,
)
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
    TradableInstrument,
)
from t212ai.brokers.trading212.service import Trading212BrokerService
from t212ai.brokers.trading212.tools import (
    Trading212ToolRuntime,
    t212_get_portfolio_snapshot,
    t212_place_order,
    t212_prepare_cancel_action,
    t212_prepare_order_action,
    t212_prepare_order,
)
from t212ai.pending_actions import PendingActionService
from t212ai.persistence.database import build_engine, build_session_factory, ensure_schema


class FakeTrading212Api:
    def __init__(self) -> None:
        self.placed_market_orders: list[MarketRequest] = []
        self.placed_limit_orders: list[LimitRequest] = []
        self.cancelled_order_ids: list[int] = []
        self.list_instruments_calls = 0

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

    def list_instruments(self) -> list[TradableInstrument]:
        self.list_instruments_calls += 1
        return [
            TradableInstrument(
                ticker="AAPL_US_EQ",
                name="Apple Inc.",
                short_name="Apple",
                isin="US0378331005",
                currency_code="USD",
            ),
            TradableInstrument(
                ticker="GOOGLE_ES_EQ",
                name="Alphabet Inc Class A",
                short_name="Google",
                isin="US02079K3059",
                currency_code="EUR",
            ),
        ]

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


def test_prepare_order_resolves_public_symbol_to_trading212_instrument() -> None:
    api = FakeTrading212Api()
    service = Trading212BrokerService(api)

    prepared = service.prepare_order(
        order_type="MARKET",
        side="BUY",
        ticker="googl",
        quantity="1",
    )

    assert prepared.ticker == "GOOGLE_ES_EQ"
    assert prepared.requested_ticker == "GOOGL"
    assert prepared.instrument is not None
    assert prepared.instrument.ticker == "GOOGLE_ES_EQ"
    assert prepared.instrument_resolution is not None
    assert prepared.instrument_resolution.resolved_ticker == "GOOGLE_ES_EQ"
    assert "GOOGL -> GOOGLE_ES_EQ" in prepared.warnings[0]
    assert prepared.request_payload["ticker"] == "GOOGLE_ES_EQ"
    assert api.list_instruments_calls == 1


def test_prepare_order_reports_ambiguous_trading212_instrument_candidates() -> None:
    class AmbiguousInstrumentApi(FakeTrading212Api):
        def list_instruments(self) -> list[TradableInstrument]:
            self.list_instruments_calls += 1
            return [
                TradableInstrument(
                    ticker="GOOGLE_ES_EQ",
                    name="Alphabet Inc Class A",
                    short_name="Google",
                    currency_code="EUR",
                ),
                TradableInstrument(
                    ticker="GOOGLE_US_EQ",
                    name="Alphabet Inc Class A",
                    short_name="Google",
                    currency_code="USD",
                ),
            ]

    service = Trading212BrokerService(AmbiguousInstrumentApi())

    with pytest.raises(ValueError) as exc_info:
        service.prepare_order(
            order_type="MARKET",
            side="BUY",
            ticker="googl",
            quantity="1",
        )

    message = str(exc_info.value)
    assert "ambiguous" in message
    assert "GOOGLE_ES_EQ" in message
    assert "GOOGLE_US_EQ" in message


def test_submit_prepared_order_rejects_unresolved_trading212_ticker_before_api_call() -> None:
    api = FakeTrading212Api()
    service = Trading212BrokerService(api)
    prepared = PreparedBrokerOrder(
        broker_provider="trading212",
        order_type=BrokerOrderType.MARKET,
        side=BrokerOrderSide.BUY,
        ticker="GOOGL",
        quantity=Decimal("1"),
        signed_quantity=Decimal("1"),
        time_in_force=BrokerTimeInForce.DAY,
        request_payload={"ticker": "GOOGL", "quantity": 1, "extendedHours": False},
        order_fingerprint="legacybad",
    )

    with pytest.raises(ValueError) as exc_info:
        service.submit_prepared_order(prepared)

    assert "unconfirmed ticker" in str(exc_info.value)
    assert "GOOGLE_ES_EQ" in str(exc_info.value)
    assert api.placed_market_orders == []


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


def test_prepare_order_action_persists_pending_action_and_returns_approval_payload(tmp_path) -> None:
    api = FakeTrading212Api()
    service = Trading212BrokerService(api)
    engine = build_engine(f"sqlite:///{tmp_path / 'order-actions.db'}")
    ensure_schema(engine)
    pending_action_service = PendingActionService(build_session_factory(engine), broker_service=service)
    runtime = Trading212ToolRuntime(
        service=service,
        pending_action_service=pending_action_service,
        chat_id="123",
        user_id=456,
        user_message="buy one apple share",
    )

    result = t212_prepare_order_action(
        order_type="MARKET",
        side="BUY",
        ticker="AAPL_US_EQ",
        quantity="1",
        limit_price=None,
        stop_price=None,
        time_validity="DAY",
        extended_hours=False,
        runtime=runtime,
    )
    pending = pending_action_service.get_awaiting_actions(chat_id="123", user_id=456)

    assert result.status == "ok"
    assert result.data is not None
    assert len(pending) == 1
    assert pending[0].original_user_message == "buy one apple share"
    assert result.data["telegramApproval"]["actionId"] == pending[0].action_id


def test_prepare_cancel_action_fails_loudly_when_multiple_pending_orders_are_ambiguous(tmp_path) -> None:
    class AmbiguousOrdersApi(FakeTrading212Api):
        def list_pending_orders(self) -> list[Order]:
            return [
                Order(
                    id=10,
                    ticker="MSFT_US_EQ",
                    quantity=Decimal("1"),
                    side=OrderSide.BUY,
                    status=OrderStatus.NEW,
                    type=OrderType.MARKET,
                ),
                Order(
                    id=11,
                    ticker="AAPL_US_EQ",
                    quantity=Decimal("2"),
                    side=OrderSide.BUY,
                    status=OrderStatus.NEW,
                    type=OrderType.LIMIT,
                ),
            ]

    service = Trading212BrokerService(AmbiguousOrdersApi())
    engine = build_engine(f"sqlite:///{tmp_path / 'cancel-actions.db'}")
    ensure_schema(engine)
    pending_action_service = PendingActionService(build_session_factory(engine), broker_service=service)
    runtime = Trading212ToolRuntime(
        service=service,
        pending_action_service=pending_action_service,
        chat_id="123",
        user_message="cancel my order",
    )

    result = t212_prepare_cancel_action(
        order_id=None,
        selector=None,
        reason=None,
        runtime=runtime,
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "ambiguous_cancel_target"
    assert pending_action_service.get_awaiting_actions(chat_id="123") == []
