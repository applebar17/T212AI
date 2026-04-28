from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from t212ai.brokers.trading212.models import (
    AccountSummary,
    Cash,
    HistoricalOrder,
    Investments,
    MarketRequest,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    PaginatedResponseHistoricalOrder,
    Position,
)
from t212ai.brokers.trading212.service import Trading212BrokerService
from t212ai.alpaca.broker import AlpacaBrokerService
from t212ai.pending_actions import PendingActionService, PendingActionState
from t212ai.persistence.database import build_engine, build_session_factory, ensure_schema
from t212ai.proposals import (
    ExecutionAttemptRow,
    ExecutionAttemptStatus,
    ProposalActionKind,
    ProposalService,
    ProposalStatus,
)
from t212ai.reconciliation import ReconciliationService


class FakeReconciliationApi:
    def __init__(
        self,
        *,
        pending_orders: list[Order] | None = None,
        historical_orders: list[HistoricalOrder] | None = None,
        remote_order_id: int = 401,
    ) -> None:
        self.pending_orders = pending_orders or []
        self.historical_orders = historical_orders or []
        self.remote_order_id = remote_order_id

    def get_account_summary(self) -> AccountSummary:
        return AccountSummary(
            id=1,
            currency="EUR",
            cash=Cash(available_to_trade=Decimal("1000")),
            investments=Investments(current_value=Decimal("2500")),
            total_value=Decimal("3500"),
        )

    def list_positions(self, *, ticker: str | None = None) -> list[Position]:
        del ticker
        return []

    def list_pending_orders(self) -> list[Order]:
        return list(self.pending_orders)

    def list_historical_orders(
        self,
        *,
        cursor: str | int | None = None,
        ticker: str | None = None,
        limit: int | None = None,
    ) -> PaginatedResponseHistoricalOrder:
        del cursor, ticker, limit
        return PaginatedResponseHistoricalOrder(items=list(self.historical_orders))

    def get_order(self, order_id: int) -> Order:
        return Order(id=order_id, ticker="AAPL_US_EQ", status=OrderStatus.NEW)

    def place_market_order(self, request: MarketRequest) -> Order:
        return Order(
            id=self.remote_order_id,
            ticker=request.ticker,
            quantity=request.quantity,
            side=OrderSide.BUY if request.quantity >= 0 else OrderSide.SELL,
            status=OrderStatus.NEW,
            type=OrderType.MARKET,
            created_at=datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc),
        )

    def place_limit_order(self, request):
        raise NotImplementedError

    def place_stop_order(self, request):
        raise NotImplementedError

    def place_stop_limit_order(self, request):
        raise NotImplementedError

    def cancel_order(self, order_id: int) -> None:
        del order_id


class FakeAlpacaReconciliationApi:
    def __init__(
        self,
        *,
        pending_orders: list[dict] | None = None,
        historical_orders: list[dict] | None = None,
        remote_order_ref: str = "alpaca-401",
    ) -> None:
        self.pending_orders = pending_orders or []
        self.historical_orders = historical_orders or []
        self.remote_order_ref = remote_order_ref

    def get_account(self):
        return {
            "account_number": "PA1234567",
            "currency": "USD",
            "buying_power": "1000",
            "portfolio_value": "3500",
        }

    def list_positions(self):
        return []

    def list_orders(self, *, status: str, limit: int | None = None, ticker: str | None = None, cursor=None):
        del limit, ticker, cursor
        if status == "open":
            return list(self.pending_orders)
        return list(self.historical_orders)

    def get_order(self, order_ref: str):
        return {
            "id": order_ref,
            "symbol": "AAPL",
            "qty": "1",
            "side": "buy",
            "status": "new",
            "type": "market",
            "time_in_force": "day",
        }

    def place_order(self, payload):
        return {
            "id": self.remote_order_ref,
            "symbol": payload["symbol"],
            "qty": payload["qty"],
            "filled_qty": "0",
            "side": payload["side"],
            "status": "accepted",
            "type": payload["type"],
            "time_in_force": payload["time_in_force"],
            "client_order_id": payload.get("client_order_id"),
            "created_at": "2026-04-28T12:00:00Z",
        }

    def cancel_order(self, order_ref: str) -> None:
        del order_ref


def _build_services(tmp_path, *, api: FakeReconciliationApi):
    engine = build_engine(f"sqlite:///{tmp_path / 'reconcile.db'}")
    ensure_schema(engine)
    session_factory = build_session_factory(engine)
    broker_service = Trading212BrokerService(api)
    pending_action_service = PendingActionService(
        session_factory,
        broker_service=broker_service,
    )
    proposal_service = ProposalService(session_factory)
    reconciliation_service = ReconciliationService(
        broker_service=broker_service,
        broker_provider="trading212",
        pending_action_service=pending_action_service,
        proposal_service=proposal_service,
    )
    return session_factory, broker_service, pending_action_service, proposal_service, reconciliation_service


def _build_alpaca_services(tmp_path, *, api: FakeAlpacaReconciliationApi):
    engine = build_engine(f"sqlite:///{tmp_path / 'reconcile-alpaca.db'}")
    ensure_schema(engine)
    session_factory = build_session_factory(engine)
    broker_service = AlpacaBrokerService(api)  # type: ignore[arg-type]
    pending_action_service = PendingActionService(
        session_factory,
        broker_service=broker_service,
        broker_services_by_provider={"alpaca": broker_service},
    )
    proposal_service = ProposalService(session_factory)
    reconciliation_service = ReconciliationService(
        broker_service=broker_service,
        broker_provider="alpaca",
        pending_action_service=pending_action_service,
        proposal_service=proposal_service,
    )
    return session_factory, broker_service, pending_action_service, proposal_service, reconciliation_service


def _prepare_submitted_submit_order(
    *,
    broker_service: Trading212BrokerService,
    pending_action_service: PendingActionService,
    proposal_service: ProposalService,
):
    proposal = proposal_service.create_submit_order_proposal(
        chat_id="123",
        user_id=456,
        intent_kind="propose_trade",
        original_user_message="buy one share",
        action_summary="BUY AAPL_US_EQ via MARKET order",
        order_intent={"ticker": "AAPL_US_EQ", "side": "BUY", "quantity": "1"},
        thesis="User requested a direct market order.",
        risks=["Immediate execution risk"],
        confidence=0.7,
    )
    prepared_order = broker_service.prepare_order(
        order_type="MARKET",
        side="BUY",
        ticker="AAPL_US_EQ",
        quantity="1",
    )
    pending_action = pending_action_service.create_submit_action(
        chat_id="123",
        user_id=456,
        prepared_order=prepared_order,
        original_user_message="buy one share",
        summary_text="Prepared buy order.",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    proposal_service.attach_pending_action(
        proposal.proposal_id,
        pending_action_id=pending_action.action_id,
    )
    decision = pending_action_service.approve_and_execute(
        pending_action.action_id,
        chat_id="123",
        user_id=456,
    )
    updated_action = decision.action
    assert updated_action is not None
    proposal_service.record_execution_attempt(
        proposal_id=proposal.proposal_id,
        pending_action_id=updated_action.action_id,
        broker_provider=updated_action.broker_provider,
        action_kind=ProposalActionKind.SUBMIT_ORDER,
        status=ExecutionAttemptStatus.SUBMITTED,
        broker_order_id=401,
        broker_response=updated_action.broker_result,
    )
    proposal_service.mark_submitted(proposal.proposal_id)
    return proposal.proposal_id, updated_action.action_id


def test_reconciliation_keeps_active_remote_order_submitted(tmp_path) -> None:
    pending_order = Order(
        id=401,
        ticker="AAPL_US_EQ",
        quantity=Decimal("1"),
        side=OrderSide.BUY,
        status=OrderStatus.NEW,
        type=OrderType.MARKET,
    )
    session_factory, broker_service, pending_action_service, proposal_service, reconciliation_service = _build_services(
        tmp_path,
        api=FakeReconciliationApi(pending_orders=[pending_order]),
    )
    proposal_id, action_id = _prepare_submitted_submit_order(
        broker_service=broker_service,
        pending_action_service=pending_action_service,
        proposal_service=proposal_service,
    )

    result = reconciliation_service.reconcile_once()
    action = pending_action_service.get_action(action_id)
    detail = proposal_service.get_proposal(proposal_id)

    assert result.pending_actions == 1
    assert action is not None
    assert action.state == PendingActionState.SUBMITTED
    assert detail is not None
    assert detail.proposal.status == ProposalStatus.SUBMITTED
    assert detail.latest_execution_attempt is not None
    assert detail.latest_execution_attempt.status == ExecutionAttemptStatus.PENDING
    with session_factory() as session:
        assert session.query(ExecutionAttemptRow).count() == 1


def test_reconciliation_finalizes_filled_orders_idempotently(tmp_path) -> None:
    historical = HistoricalOrder(
        order=Order(
            id=401,
            ticker="AAPL_US_EQ",
            quantity=Decimal("1"),
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            type=OrderType.MARKET,
        )
    )
    session_factory, broker_service, pending_action_service, proposal_service, reconciliation_service = _build_services(
        tmp_path,
        api=FakeReconciliationApi(historical_orders=[historical]),
    )
    proposal_id, action_id = _prepare_submitted_submit_order(
        broker_service=broker_service,
        pending_action_service=pending_action_service,
        proposal_service=proposal_service,
    )

    first = reconciliation_service.reconcile_once()
    second = reconciliation_service.reconcile_once()
    action = pending_action_service.get_action(action_id)
    detail = proposal_service.get_proposal(proposal_id)

    assert first.finalized_actions == 1
    assert second.scanned_actions == 0
    assert action is not None
    assert action.state == PendingActionState.RECONCILED
    assert detail is not None
    assert detail.proposal.status == ProposalStatus.RECONCILED
    assert detail.latest_execution_attempt is not None
    assert detail.latest_execution_attempt.status == ExecutionAttemptStatus.FILLED
    with session_factory() as session:
        assert session.query(ExecutionAttemptRow).count() == 1


@pytest.mark.parametrize(
    ("remote_status", "expected_action_state", "expected_proposal_status", "expected_attempt_status"),
    [
        (
            OrderStatus.CANCELLED,
            PendingActionState.CANCELLED,
            ProposalStatus.CANCELLED,
            ExecutionAttemptStatus.CANCELLED,
        ),
        (
            OrderStatus.REJECTED,
            PendingActionState.FAILED,
            ProposalStatus.EXECUTION_FAILED,
            ExecutionAttemptStatus.REJECTED,
        ),
    ],
)
def test_reconciliation_maps_terminal_remote_statuses(
    tmp_path,
    remote_status,
    expected_action_state,
    expected_proposal_status,
    expected_attempt_status,
) -> None:
    historical = HistoricalOrder(
        order=Order(
            id=401,
            ticker="AAPL_US_EQ",
            quantity=Decimal("1"),
            side=OrderSide.BUY,
            status=remote_status,
            type=OrderType.MARKET,
        )
    )
    _session_factory, broker_service, pending_action_service, proposal_service, reconciliation_service = _build_services(
        tmp_path,
        api=FakeReconciliationApi(historical_orders=[historical]),
    )
    proposal_id, action_id = _prepare_submitted_submit_order(
        broker_service=broker_service,
        pending_action_service=pending_action_service,
        proposal_service=proposal_service,
    )

    reconciliation_service.reconcile_once()
    action = pending_action_service.get_action(action_id)
    detail = proposal_service.get_proposal(proposal_id)

    assert action is not None
    assert action.state == expected_action_state
    assert detail is not None
    assert detail.proposal.status == expected_proposal_status
    assert detail.latest_execution_attempt is not None
    assert detail.latest_execution_attempt.status == expected_attempt_status


def test_reconciliation_supports_alpaca_provider_refs(tmp_path) -> None:
    historical = {
        "id": "alpaca-401",
        "symbol": "AAPL",
        "qty": "1",
        "filled_qty": "1",
        "filled_avg_price": "180",
        "side": "buy",
        "status": "filled",
        "type": "market",
        "time_in_force": "day",
        "client_order_id": "t212ai-test",
        "created_at": "2026-04-28T12:00:00Z",
    }
    _session_factory, broker_service, pending_action_service, proposal_service, reconciliation_service = _build_alpaca_services(
        tmp_path,
        api=FakeAlpacaReconciliationApi(historical_orders=[historical]),
    )
    proposal = proposal_service.create_submit_order_proposal(
        chat_id="123",
        user_id=456,
        intent_kind="propose_trade",
        original_user_message="buy one share",
        action_summary="BUY AAPL via MARKET order",
        order_intent={"ticker": "AAPL", "side": "BUY", "quantity": "1"},
        thesis="User requested a direct market order.",
        risks=["Immediate execution risk"],
        confidence=0.7,
    )
    prepared_order = broker_service.prepare_order(
        order_type="MARKET",
        side="BUY",
        ticker="AAPL",
        quantity="1",
    )
    pending_action = pending_action_service.create_submit_action(
        chat_id="123",
        user_id=456,
        prepared_order=prepared_order,
        original_user_message="buy one share",
        summary_text="Prepared buy order.",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        broker_provider="alpaca",
    )
    proposal_service.attach_pending_action(
        proposal.proposal_id,
        pending_action_id=pending_action.action_id,
    )
    decision = pending_action_service.approve_and_execute(
        pending_action.action_id,
        chat_id="123",
        user_id=456,
    )
    updated_action = decision.action
    assert updated_action is not None
    proposal_service.record_execution_attempt(
        proposal_id=proposal.proposal_id,
        pending_action_id=updated_action.action_id,
        broker_provider=updated_action.broker_provider,
        action_kind=ProposalActionKind.SUBMIT_ORDER,
        status=ExecutionAttemptStatus.SUBMITTED,
        broker_order_ref="alpaca-401",
        broker_response=updated_action.broker_result,
    )
    proposal_service.mark_submitted(proposal.proposal_id)

    result = reconciliation_service.reconcile_once()
    action = pending_action_service.get_action(updated_action.action_id)
    detail = proposal_service.get_proposal(proposal.proposal_id)

    assert result.finalized_actions == 1
    assert action is not None
    assert action.state == PendingActionState.RECONCILED
    assert detail is not None
    assert detail.proposal.status == ProposalStatus.RECONCILED
    assert detail.latest_execution_attempt is not None
    assert detail.latest_execution_attempt.status == ExecutionAttemptStatus.FILLED
