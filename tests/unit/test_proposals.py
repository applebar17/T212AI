from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from t212ai.agent import AgentReasoner, OrderAgent
from t212ai.agent.intents import AgentIntent, IntentKind
from t212ai.agent.planner import AgentPlan
from t212ai.agent.schemas import AgentRequest
from t212ai.brokers.trading212.models import (
    AccountSummary,
    Cash,
    Investments,
    LimitRequest,
    MarketRequest,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)
from t212ai.brokers.trading212.service import Trading212BrokerService
from t212ai.pending_actions import PendingActionService, Trading212OrderActionRequest
from t212ai.persistence.database import build_engine, build_session_factory, ensure_schema
from t212ai.proposals import (
    ApprovalDecision,
    ApprovalSource,
    ExecutionAttemptStatus,
    ProposalActionKind,
    ProposalService,
    ProposalStatus,
)


class FakeTrading212Api:
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
        return []

    def get_order(self, order_id: int) -> Order:
        return Order(id=order_id, ticker="AAPL_US_EQ", status=OrderStatus.NEW)

    def place_market_order(self, request: MarketRequest) -> Order:
        return Order(
            id=123,
            ticker=request.ticker,
            quantity=request.quantity,
            status=OrderStatus.NEW,
            type=OrderType.MARKET,
        )

    def place_limit_order(self, request: LimitRequest) -> Order:
        return Order(
            id=124,
            ticker=request.ticker,
            quantity=request.quantity,
            status=OrderStatus.NEW,
            type=OrderType.LIMIT,
            limit_price=request.limit_price,
        )

    def place_stop_order(self, request) -> Order:
        raise NotImplementedError

    def place_stop_limit_order(self, request) -> Order:
        raise NotImplementedError

    def cancel_order(self, order_id: int) -> None:
        del order_id


class ProposalGenAIClient:
    def __init__(self, *, valid_submit: bool = True) -> None:
        self.valid_submit = valid_submit

    def chat_model_for(self, purpose: str | None = None) -> str:
        return f"{purpose or 'default'}-model"

    def generate_structured(
        self,
        schema: type,
        system_prompt: str,
        chat_message: object,
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> object:
        del system_prompt, chat_message, model, temperature, max_tokens
        if schema is AgentPlan:
            return AgentPlan(
                intent=AgentIntent(kind=IntentKind.PROPOSE_TRADE),
                summary="Prepare a submit-order proposal.",
                required_context=["broker validation"],
                assumptions=["The user wants a direct submit-order proposal."],
                risks=["Execution requires approval."],
            )
        if schema is Trading212OrderActionRequest:
            if self.valid_submit:
                return Trading212OrderActionRequest(
                    action="prepare_submit_order",
                    order_type="MARKET",
                    side="BUY",
                    ticker="AAPL_US_EQ",
                    quantity="1",
                    time_validity="DAY",
                    extended_hours=False,
                    thesis="Short-term entry requested by the user.",
                    risks=["Market volatility", "Immediate execution risk"],
                    confidence=0.72,
                )
            return Trading212OrderActionRequest(
                action="prepare_submit_order",
                order_type="MARKET",
                side="BUY",
                ticker="AAPL_US_EQ",
                quantity="0",
                time_validity="DAY",
                extended_hours=False,
                thesis="Invalid proposal for test coverage.",
                risks=["Invalid quantity"],
                confidence=0.4,
            )
        raise AssertionError(f"Unexpected schema: {schema}")


def _services(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'proposals.db'}")
    ensure_schema(engine)
    session_factory = build_session_factory(engine)
    return (
        ProposalService(session_factory),
        PendingActionService(
            session_factory,
            broker_service=Trading212BrokerService(FakeTrading212Api()),
        ),
        Trading212BrokerService(FakeTrading212Api()),
    )


def test_proposal_service_persists_and_retrieves_lifecycle(tmp_path) -> None:
    proposal_service, _pending_action_service, _broker_service = _services(tmp_path)

    proposal = proposal_service.create_submit_order_proposal(
        chat_id="123",
        user_id=456,
        intent_kind=IntentKind.PROPOSE_TRADE.value,
        original_user_message="buy one apple share",
        action_summary="BUY AAPL_US_EQ via MARKET order",
        order_intent={"ticker": "AAPL_US_EQ", "side": "BUY", "quantity": "1"},
        thesis="Short thesis",
        risks=["Risk one"],
        confidence=0.6,
    )
    linked = proposal_service.attach_pending_action(
        proposal.proposal_id,
        pending_action_id="pa_123",
    )
    approval = proposal_service.record_approval_event(
        proposal_id=proposal.proposal_id,
        pending_action_id="pa_123",
        decision=ApprovalDecision.APPROVE,
        source=ApprovalSource.BUTTON,
        chat_id="123",
        user_id=456,
    )
    execution = proposal_service.record_execution_attempt(
        proposal_id=proposal.proposal_id,
        pending_action_id="pa_123",
        broker_provider="trading212",
        action_kind=ProposalActionKind.SUBMIT_ORDER,
        status=ExecutionAttemptStatus.SUBMITTED,
        broker_order_id=999,
        broker_response={"orderId": 999, "status": "submitted"},
    )
    submitted = proposal_service.mark_submitted(proposal.proposal_id)
    detail = proposal_service.get_proposal(proposal.proposal_id)
    recent = proposal_service.list_recent_proposals(chat_id="123", user_id=456)

    assert linked is not None
    assert linked.status == ProposalStatus.AWAITING_APPROVAL
    assert approval.decision == ApprovalDecision.APPROVE
    assert execution.status == ExecutionAttemptStatus.SUBMITTED
    assert submitted is not None
    assert submitted.status == ProposalStatus.SUBMITTED
    assert detail is not None
    assert detail.proposal.pending_action_id == "pa_123"
    assert detail.latest_execution_attempt is not None
    assert detail.latest_execution_attempt.broker_order_id == 999
    assert [item.proposal_id for item in recent] == [proposal.proposal_id]


def test_order_agent_submit_order_creates_proposal_and_links_pending_action(tmp_path) -> None:
    proposal_service, pending_action_service, broker_service = _services(tmp_path)
    reasoner = AgentReasoner(ProposalGenAIClient())  # type: ignore[arg-type]
    agent = OrderAgent(
        reasoner,
        broker_service=broker_service,
        pending_action_service=pending_action_service,
        proposal_service=proposal_service,
    )

    response = agent.handle(
        AgentRequest(
            user_message="buy one apple share",
            chat_id="123",
            metadata={"telegram_user_id": "456"},
        ),
        intent=AgentIntent(kind=IntentKind.PROPOSE_TRADE),
    )
    proposal_id = response.artifacts["proposal_id"]
    detail = proposal_service.get_proposal(proposal_id)

    assert response.metadata["workflow_status"] == "ok"
    assert "Proposal ref:" in response.final_answer
    assert detail is not None
    assert detail.proposal.status == ProposalStatus.AWAITING_APPROVAL
    assert detail.proposal.pending_action_id is not None
    assert detail.proposal.thesis == "Short-term entry requested by the user."


def test_order_agent_marks_preparation_failed_when_order_validation_fails(tmp_path) -> None:
    proposal_service, pending_action_service, broker_service = _services(tmp_path)
    reasoner = AgentReasoner(ProposalGenAIClient(valid_submit=False))  # type: ignore[arg-type]
    agent = OrderAgent(
        reasoner,
        broker_service=broker_service,
        pending_action_service=pending_action_service,
        proposal_service=proposal_service,
    )

    response = agent.handle(
        AgentRequest(
            user_message="buy zero apple shares",
            chat_id="123",
            metadata={"telegram_user_id": "456"},
        ),
        intent=AgentIntent(kind=IntentKind.PROPOSE_TRADE),
    )
    proposal_id = response.metadata["proposal_id"]
    detail = proposal_service.get_proposal(proposal_id)

    assert response.metadata["workflow_status"] == "error"
    assert detail is not None
    assert detail.proposal.status == ProposalStatus.PREPARATION_FAILED
    assert detail.proposal.pending_action_id is None
