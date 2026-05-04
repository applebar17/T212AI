from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from t212ai.brokers.models import BrokerOrderActionResult, PreparedBrokerOrder
from t212ai.brokers.trading212.models import (
    Order,
    OrderActionResult,
    OrderSide,
    OrderStatus,
    OrderType,
    PreparedOrder,
    TimeValidity,
)
from t212ai.pending_actions import (
    PendingActionDecisionStatus,
    PendingActionService,
    PendingActionState,
)
from t212ai.persistence.database import build_engine, build_session_factory, ensure_schema


class FakeExecutionBroker:
    def __init__(self) -> None:
        self.submitted_orders: list[PreparedOrder] = []
        self.cancelled_order_ids: list[int] = []

    def submit_prepared_order(self, prepared_order: PreparedOrder) -> OrderActionResult:
        self.submitted_orders.append(prepared_order)
        return OrderActionResult(
            action="submit_order",
            status="submitted",
            order_id=321,
            message="Submitted.",
        )

    def cancel_order(self, order_id: int) -> OrderActionResult:
        self.cancelled_order_ids.append(order_id)
        return OrderActionResult(
            action="cancel_order",
            status="submitted",
            order_id=order_id,
            message="Cancellation sent.",
        )


class CloseOnlyExecutionBroker(FakeExecutionBroker):
    def submit_prepared_order(self, prepared_order: PreparedOrder) -> OrderActionResult:
        del prepared_order
        error = RuntimeError("Trading 212 API request failed with HTTP 400.")
        error.status_code = 400
        error.body = (
            '{"type":"/api-errors/instrument-close-only-mode",'
            '"title":"Error while placing the order","status":400,'
            '"detail":"Close only mode","traceId":"trace-close-only"}'
        )
        raise error


def _service(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'pending-actions.db'}")
    ensure_schema(engine)
    broker = FakeExecutionBroker()
    return PendingActionService(build_session_factory(engine), broker_service=broker), broker


def _prepared_order() -> PreparedOrder:
    return PreparedOrder(
        order_type=OrderType.MARKET,
        side=OrderSide.BUY,
        ticker="TSLA_US_EQ",
        signed_quantity=Decimal("1"),
        request_payload={
            "ticker": "TSLA_US_EQ",
            "quantity": 1.0,
            "extendedHours": False,
        },
        order_fingerprint="fingerprint123456",
    )


def test_pending_action_service_creates_and_executes_submit_action(tmp_path) -> None:
    service, broker = _service(tmp_path)
    action = service.create_submit_action(
        chat_id="123",
        user_id=456,
        prepared_order=_prepared_order(),
        original_user_message="buy tesla",
        summary_text="Prepared TSLA order.",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )

    fetched = service.get_action(action.action_id)
    result = service.approve_and_execute(action.action_id, chat_id="123", user_id=456)
    finalized = service.get_action(action.action_id)

    assert fetched is not None
    assert fetched.state == PendingActionState.AWAITING_APPROVAL
    assert result.status == PendingActionDecisionStatus.SUBMITTED
    assert len(broker.submitted_orders) == 1
    assert broker.submitted_orders[0].ticker == "TSLA_US_EQ"
    assert finalized is not None
    assert finalized.state == PendingActionState.SUBMITTED


def test_pending_action_service_reports_close_only_execution_failure(tmp_path) -> None:
    engine = build_engine(f"sqlite:///{tmp_path / 'pending-actions-close-only.db'}")
    ensure_schema(engine)
    broker = CloseOnlyExecutionBroker()
    service = PendingActionService(build_session_factory(engine), broker_service=broker)
    action = service.create_submit_action(
        chat_id="123",
        user_id=456,
        prepared_order=_prepared_order(),
        original_user_message="buy suspended stock",
        summary_text="Prepared suspended-stock order.",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        broker_provider="trading212",
    )

    result = service.approve_and_execute(action.action_id, chat_id="123", user_id=456)
    finalized = service.get_action(action.action_id)

    assert result.status == PendingActionDecisionStatus.FAILED
    assert "close-only mode" in result.message
    assert "temporarily not allowed" in result.message
    assert "HTTP 400" not in result.message
    assert finalized is not None
    assert finalized.state == PendingActionState.FAILED


def test_pending_action_service_rejects_cancel_action_and_is_idempotent(tmp_path) -> None:
    service, broker = _service(tmp_path)
    action = service.create_cancel_action(
        chat_id="123",
        user_id=456,
        target_order=Order(
            id=77,
            ticker="MSFT_US_EQ",
            side=OrderSide.BUY,
            status=OrderStatus.NEW,
            type=OrderType.LIMIT,
            quantity=Decimal("2"),
            time_in_force=TimeValidity.DAY,
        ),
        original_user_message="cancel my msft order",
        summary_text="Prepared cancellation.",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )

    rejected = service.reject(action.action_id, chat_id="123", user_id=456)
    repeated = service.reject(action.action_id, chat_id="123", user_id=456)

    assert rejected.status == PendingActionDecisionStatus.REJECTED
    assert repeated.status == PendingActionDecisionStatus.ALREADY_FINALIZED
    assert broker.cancelled_order_ids == []


def test_pending_action_service_expires_stale_actions(tmp_path) -> None:
    service, broker = _service(tmp_path)
    action = service.create_submit_action(
        chat_id="123",
        user_id=None,
        prepared_order=_prepared_order(),
        original_user_message="buy tesla",
        summary_text="Prepared TSLA order.",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    result = service.approve_and_execute(action.action_id, chat_id="123", user_id=None)

    assert result.status == PendingActionDecisionStatus.EXPIRED
    assert broker.submitted_orders == []


def test_pending_action_service_filters_awaiting_actions_by_chat_and_user(tmp_path) -> None:
    service, _broker = _service(tmp_path)
    action = service.create_submit_action(
        chat_id="123",
        user_id=456,
        prepared_order=_prepared_order(),
        original_user_message="buy tesla",
        summary_text="Prepared TSLA order.",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )

    matching = service.get_awaiting_actions(chat_id="123", user_id=456)
    other_user = service.get_awaiting_actions(chat_id="123", user_id=999)
    other_chat = service.get_awaiting_actions(chat_id="999", user_id=456)

    assert [item.action_id for item in matching] == [action.action_id]
    assert other_user == []
    assert other_chat == []


def test_pending_action_service_executes_alpaca_prepared_order_with_provider_mapping(tmp_path) -> None:
    engine = build_engine(f"sqlite:///{tmp_path / 'pending-actions-alpaca.db'}")
    ensure_schema(engine)

    class FakeAlpacaExecutionBroker:
        def __init__(self) -> None:
            self.submitted_orders: list[PreparedBrokerOrder] = []

        def submit_prepared_order(self, prepared_order: PreparedBrokerOrder) -> BrokerOrderActionResult:
            self.submitted_orders.append(prepared_order)
            return BrokerOrderActionResult(
                broker_provider="alpaca",
                action="submit_order",
                status="accepted",
                order_id="alpaca-order-1",
                message="Submitted to Alpaca.",
            )

        def cancel_order(self, order_ref: str) -> BrokerOrderActionResult:
            return BrokerOrderActionResult(
                broker_provider="alpaca",
                action="cancel_order",
                status="accepted",
                order_id=order_ref,
                message="Cancelled.",
            )

    broker = FakeAlpacaExecutionBroker()
    service = PendingActionService(
        build_session_factory(engine),
        broker_services_by_provider={"alpaca": broker},
    )
    action = service.create_submit_action(
        chat_id="123",
        user_id=456,
        prepared_order=PreparedBrokerOrder(
            broker_provider="alpaca",
            order_type="LIMIT",
            side="BUY",
            ticker="AAPL",
            quantity=Decimal("1"),
            signed_quantity=Decimal("1"),
            limit_price=Decimal("180"),
            time_in_force="DAY",
            extended_hours=False,
            request_payload={
                "symbol": "AAPL",
                "qty": "1",
                "side": "buy",
                "type": "limit",
                "time_in_force": "day",
                "limit_price": "180",
                "client_order_id": "t212ai-test",
            },
            order_fingerprint="alpaca1234567890",
        ),
        original_user_message="buy apple",
        summary_text="Prepared AAPL order.",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        broker_provider="alpaca",
    )

    result = service.approve_and_execute(action.action_id, chat_id="123", user_id=456)

    assert result.status == PendingActionDecisionStatus.SUBMITTED
    assert broker.submitted_orders[0].broker_provider == "alpaca"
    assert broker.submitted_orders[0].request_payload["client_order_id"] == "t212ai-test"
