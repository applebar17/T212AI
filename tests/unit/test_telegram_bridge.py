from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging
import sys
from types import ModuleType

from t212ai.brokers.trading212.models import (
    Order,
    OrderActionResult,
    OrderSide,
    OrderStatus,
    OrderType,
    PreparedOrder,
    TimeValidity,
)
from t212ai.pending_actions import PendingActionService
from t212ai.persistence.database import build_engine, build_session_factory, ensure_schema
from t212ai.proposals import ProposalActionKind, ProposalService, ProposalStatus

from t212ai.telegram import (
    TelegramAccessPolicy,
    TelegramApprovalRequest,
    TelegramBotService,
    TelegramInboundMessage,
    TelegramOutboundMessage,
    TelegramUpdateRouter,
    build_default_message_handler,
)
from t212ai.agent.history import ChatHistoryManager
from t212ai.telegram.formatting import normalize_telegram_text


@dataclass(slots=True)
class FakeChat:
    id: int


@dataclass(slots=True)
class FakeUser:
    id: int
    username: str = "tester"
    first_name: str = "Test"


@dataclass(slots=True)
class FakeMessage:
    text: str
    message_id: int = 99


@dataclass(slots=True)
class FakeUpdate:
    effective_chat: FakeChat
    effective_user: FakeUser
    effective_message: FakeMessage
    callback_query: object | None = None


@dataclass(slots=True)
class FakeCallbackQuery:
    data: str
    message: FakeMessage

    async def answer(self) -> None:
        return None


class FakeBot:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, object]] = []
        self.edited_messages: list[dict[str, object]] = []

    async def send_message(self, **kwargs: object) -> dict[str, object]:
        payload = dict(kwargs)
        payload.setdefault("message_id", len(self.sent_messages) + 1000)
        self.sent_messages.append(payload)
        return payload

    async def edit_message_text(self, **kwargs: object) -> dict[str, object]:
        payload = dict(kwargs)
        self.edited_messages.append(payload)
        return payload


@dataclass(slots=True)
class FakeContext:
    bot: FakeBot


class FakeExecutionBroker:
    def __init__(self) -> None:
        self.submitted_orders: list[PreparedOrder] = []
        self.cancelled_order_ids: list[int] = []

    def submit_prepared_order(self, prepared_order: PreparedOrder) -> OrderActionResult:
        self.submitted_orders.append(prepared_order)
        return OrderActionResult(
            action="submit_order",
            status="submitted",
            order_id=111,
            message="Submitted.",
        )

    def cancel_order(self, order_id: int) -> OrderActionResult:
        self.cancelled_order_ids.append(order_id)
        return OrderActionResult(
            action="cancel_order",
            status="submitted",
            order_id=order_id,
            message="Cancelled.",
        )


def _persistence_services(
    tmp_path,
) -> tuple[PendingActionService, ProposalService, FakeExecutionBroker]:
    engine = build_engine(f"sqlite:///{tmp_path / 'telegram-approvals.db'}")
    ensure_schema(engine)
    session_factory = build_session_factory(engine)
    broker = FakeExecutionBroker()
    return (
        PendingActionService(session_factory, broker_service=broker),
        ProposalService(session_factory),
        broker,
    )


def _pending_action_service(tmp_path) -> tuple[PendingActionService, FakeExecutionBroker]:
    pending_action_service, _proposal_service, broker = _persistence_services(tmp_path)
    return pending_action_service, broker


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


def test_access_policy_fails_closed_without_allowed_chat_id() -> None:
    try:
        TelegramAccessPolicy.from_allowed_chat_id(None)
    except RuntimeError as exc:
        assert "TELEGRAM_ALLOWED_CHAT_ID" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected RuntimeError")


def test_access_policy_accepts_comma_separated_chat_ids() -> None:
    policy = TelegramAccessPolicy.from_allowed_chat_id("123, 456")

    assert policy.is_allowed(123)
    assert policy.is_allowed("456")
    assert not policy.is_allowed(789)


def test_access_policy_can_enforce_optional_allowed_user_ids() -> None:
    policy = TelegramAccessPolicy.from_allowed_ids("123", "456, 789")

    assert policy.is_allowed(123, 456)
    assert not policy.is_allowed(123, 999)


def test_default_handler_renders_help_for_help_command() -> None:
    handler = build_default_message_handler()
    response = handler(
        TelegramInboundMessage(
            chat_id=123,
            text="/help",
        )
    )

    assert isinstance(response, TelegramOutboundMessage)
    assert "/summary" in response.text


def test_router_sends_response_for_authorized_chat() -> None:
    async def message_handler(_message: object) -> str:
        return "bridge response"

    bot = FakeBot()
    router = TelegramUpdateRouter(
        access_policy=TelegramAccessPolicy.from_allowed_chat_id(123),
        message_handler=message_handler,  # type: ignore[arg-type]
    )
    update = FakeUpdate(
        effective_chat=FakeChat(123),
        effective_user=FakeUser(1),
        effective_message=FakeMessage("hello"),
    )

    asyncio.run(router.handle_update(update, FakeContext(bot=bot)))

    assert len(bot.sent_messages) == 1
    assert bot.sent_messages[0]["chat_id"] == 123
    assert bot.sent_messages[0]["text"] == "bridge response"
    assert bot.sent_messages[0]["reply_to_message_id"] == 99


def test_router_sends_concise_content_filter_error(caplog) -> None:
    class ContentFilterError(Exception):
        code = "content_filter"

        def __str__(self) -> str:
            return "ResponsibleAIPolicyViolation contentfilter"

    async def message_handler(_message: object) -> str:
        raise ContentFilterError()

    bot = FakeBot()
    router = TelegramUpdateRouter(
        access_policy=TelegramAccessPolicy.from_allowed_chat_id(123),
        message_handler=message_handler,  # type: ignore[arg-type]
    )
    update = FakeUpdate(
        effective_chat=FakeChat(123),
        effective_user=FakeUser(1),
        effective_message=FakeMessage("market scan"),
    )

    with caplog.at_level(logging.INFO, logger="t212ai.telegram.bridge"):
        asyncio.run(router.handle_update(update, FakeContext(bot=bot)))

    assert len(bot.sent_messages) == 1
    text = str(bot.sent_messages[0]["text"])
    assert "LLM provider blocked this request" in text
    assert "ResponsibleAIPolicyViolation" not in text
    error_events = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "telegram.request.error"
    ]
    assert error_events
    assert error_events[-1].event_fields["error_code"] == "content_filter"
    assert error_events[-1].event_fields["status"] == "error"
    assert "market scan" not in str(error_events[-1].event_fields)


def test_normalize_telegram_text_removes_common_markdown() -> None:
    text = """### General Help

- **Portfolio analysis**
- _Market context_
- `Calculations`
"""

    assert normalize_telegram_text(text) == (
        "General Help\n\n"
        "- Portfolio analysis\n"
        "- Market context\n"
        "- Calculations"
    )


def test_router_normalizes_markdownish_response_before_sending() -> None:
    async def message_handler(_message: object) -> str:
        return "### General Help\n\n- **Portfolio analysis**"

    bot = FakeBot()
    router = TelegramUpdateRouter(
        access_policy=TelegramAccessPolicy.from_allowed_chat_id(123),
        message_handler=message_handler,  # type: ignore[arg-type]
    )
    update = FakeUpdate(
        effective_chat=FakeChat(123),
        effective_user=FakeUser(1),
        effective_message=FakeMessage("hello"),
    )

    asyncio.run(router.handle_update(update, FakeContext(bot=bot)))

    assert bot.sent_messages[0]["text"] == "General Help\n\n- Portfolio analysis"


def test_router_ignores_unauthorized_chat_by_default() -> None:
    bot = FakeBot()
    router = TelegramUpdateRouter(
        access_policy=TelegramAccessPolicy.from_allowed_chat_id(123),
        message_handler=lambda _message: "should not send",
    )
    update = FakeUpdate(
        effective_chat=FakeChat(999),
        effective_user=FakeUser(1),
        effective_message=FakeMessage("hello"),
    )

    asyncio.run(router.handle_update(update, FakeContext(bot=bot)))

    assert bot.sent_messages == []


def test_bot_service_can_be_configured_without_importing_telegram_package() -> None:
    service = TelegramBotService(
        token="token",
        access_policy=TelegramAccessPolicy.from_allowed_chat_id(123),
        message_handler=lambda _message: "ok",
    )

    assert service.token == "token"
    assert service.access_policy.is_allowed(123)


def test_router_sends_approval_request_and_attaches_message_id(tmp_path, monkeypatch) -> None:
    pending_action_service, _broker = _pending_action_service(tmp_path)
    fake_telegram = ModuleType("telegram")

    class InlineKeyboardButton:
        def __init__(self, text: str, callback_data: str) -> None:
            self.text = text
            self.callback_data = callback_data

    class InlineKeyboardMarkup:
        def __init__(self, buttons) -> None:
            self.buttons = buttons

    fake_telegram.InlineKeyboardButton = InlineKeyboardButton
    fake_telegram.InlineKeyboardMarkup = InlineKeyboardMarkup
    monkeypatch.setitem(sys.modules, "telegram", fake_telegram)
    action = pending_action_service.create_submit_action(
        chat_id="123",
        user_id=1,
        prepared_order=_prepared_order(),
        original_user_message="buy tesla",
        summary_text="Prepared TSLA order.",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    bot = FakeBot()
    router = TelegramUpdateRouter(
        access_policy=TelegramAccessPolicy.from_allowed_chat_id(123),
        message_handler=lambda _message: TelegramApprovalRequest(
            chat_id=123,
            text="Approve this prepared order.",
            action_id=action.action_id,
            approve_callback_data=f"pa:approve:{action.action_id}",
            reject_callback_data=f"pa:reject:{action.action_id}",
        ),
        pending_action_service=pending_action_service,
    )
    update = FakeUpdate(
        effective_chat=FakeChat(123),
        effective_user=FakeUser(1),
        effective_message=FakeMessage("buy tsla"),
    )

    asyncio.run(router.handle_update(update, FakeContext(bot=bot)))
    stored = pending_action_service.get_action(action.action_id)

    assert stored is not None
    assert stored.approval_message_id == 1000


def test_router_callback_approve_executes_exact_stored_action_and_projects_history(tmp_path) -> None:
    pending_action_service, broker = _pending_action_service(tmp_path)
    history = ChatHistoryManager()
    action = pending_action_service.create_submit_action(
        chat_id="123",
        user_id=1,
        prepared_order=_prepared_order(),
        original_user_message="buy tesla",
        summary_text="Prepared TSLA order.",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    pending_action_service.attach_approval_message_id(action.action_id, 501)
    bot = FakeBot()
    router = TelegramUpdateRouter(
        access_policy=TelegramAccessPolicy.from_allowed_chat_id(123),
        message_handler=lambda _message: None,
        history_manager=history,
        pending_action_service=pending_action_service,
    )
    update = FakeUpdate(
        effective_chat=FakeChat(123),
        effective_user=FakeUser(1),
        effective_message=FakeMessage("prepared order", message_id=501),
        callback_query=FakeCallbackQuery(
            data=f"pa:approve:{action.action_id}",
            message=FakeMessage("prepared order", message_id=501),
        ),
    )

    asyncio.run(router.handle_update(update, FakeContext(bot=bot)))
    window = history.get_context_window(123)
    stored = pending_action_service.get_action(action.action_id)

    assert len(broker.submitted_orders) == 1
    assert stored is not None
    assert stored.state.value == "submitted"
    assert [message.content for message in window.messages] == [
        "telegram button: approve",
        "The prepared order was approved and submitted to Trading 212.",
    ]
    assert bot.edited_messages[0]["message_id"] == 501
    assert bot.sent_messages[-1]["text"] == "The prepared order was approved and submitted to Trading 212."


def test_router_natural_language_does_not_reject_pending_action(tmp_path) -> None:
    pending_action_service, broker = _pending_action_service(tmp_path)
    history = ChatHistoryManager()
    action = pending_action_service.create_cancel_action(
        chat_id="123",
        user_id=1,
        target_order=Order(
            id=77,
            ticker="MSFT_US_EQ",
            side=OrderSide.BUY,
            status=OrderStatus.NEW,
            type=OrderType.LIMIT,
            quantity=Decimal("2"),
            time_in_force=TimeValidity.DAY,
        ),
        original_user_message="cancel it",
        summary_text="Prepared cancellation.",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    pending_action_service.attach_approval_message_id(action.action_id, 601)
    bot = FakeBot()
    router = TelegramUpdateRouter(
        access_policy=TelegramAccessPolicy.from_allowed_chat_id(123),
        message_handler=lambda _message: "agent response",
        history_manager=history,
        pending_action_service=pending_action_service,
    )
    update = FakeUpdate(
        effective_chat=FakeChat(123),
        effective_user=FakeUser(1),
        effective_message=FakeMessage("no", message_id=700),
    )

    asyncio.run(router.handle_update(update, FakeContext(bot=bot)))
    stored = pending_action_service.get_action(action.action_id)

    assert broker.cancelled_order_ids == []
    assert stored is not None
    assert stored.state.value == "awaiting_approval"
    assert history.get_context_window(123).messages == []
    assert bot.sent_messages[-1]["text"] == "agent response"
    assert bot.sent_messages[-1]["reply_to_message_id"] == 700


def test_router_natural_language_does_not_approve_pending_action(tmp_path) -> None:
    pending_action_service, broker = _pending_action_service(tmp_path)
    history = ChatHistoryManager()
    action = pending_action_service.create_submit_action(
        chat_id="123",
        user_id=1,
        prepared_order=_prepared_order(),
        original_user_message="sell lvmh at market",
        summary_text="Prepared LVMH sell order.",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    pending_action_service.attach_approval_message_id(action.action_id, 701)
    bot = FakeBot()
    router = TelegramUpdateRouter(
        access_policy=TelegramAccessPolicy.from_allowed_chat_id(123),
        message_handler=lambda _message: "agent response",
        history_manager=history,
        pending_action_service=pending_action_service,
    )
    update = FakeUpdate(
        effective_chat=FakeChat(123),
        effective_user=FakeUser(1),
        effective_message=FakeMessage("CONFIRM SELL LVMH AT MARKET", message_id=702),
    )

    asyncio.run(router.handle_update(update, FakeContext(bot=bot)))
    stored = pending_action_service.get_action(action.action_id)

    assert broker.submitted_orders == []
    assert stored is not None
    assert stored.state.value == "awaiting_approval"
    assert history.get_context_window(123).messages == []
    assert bot.sent_messages[-1]["text"] == "agent response"
    assert bot.sent_messages[-1]["reply_to_message_id"] == 702


def test_router_natural_language_routes_to_agent_with_multiple_pending_actions(tmp_path) -> None:
    pending_action_service, broker = _pending_action_service(tmp_path)
    for _ in range(2):
        pending_action_service.create_submit_action(
            chat_id="123",
            user_id=1,
            prepared_order=_prepared_order(),
            original_user_message="buy tesla",
            summary_text="Prepared TSLA order.",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
    bot = FakeBot()
    router = TelegramUpdateRouter(
        access_policy=TelegramAccessPolicy.from_allowed_chat_id(123),
        message_handler=lambda _message: "agent response",
        pending_action_service=pending_action_service,
    )
    update = FakeUpdate(
        effective_chat=FakeChat(123),
        effective_user=FakeUser(1),
        effective_message=FakeMessage("yes", message_id=701),
    )

    asyncio.run(router.handle_update(update, FakeContext(bot=bot)))

    assert broker.submitted_orders == []
    assert bot.sent_messages[-1]["text"] == "agent response"
    assert bot.sent_messages[-1]["reply_to_message_id"] == 701


def test_router_yes_without_pending_action_routes_to_message_handler(tmp_path) -> None:
    pending_action_service, _broker = _pending_action_service(tmp_path)
    bot = FakeBot()
    router = TelegramUpdateRouter(
        access_policy=TelegramAccessPolicy.from_allowed_chat_id(123),
        message_handler=lambda _message: "agent response",
        pending_action_service=pending_action_service,
    )
    update = FakeUpdate(
        effective_chat=FakeChat(123),
        effective_user=FakeUser(1),
        effective_message=FakeMessage("Yes i’m comfortable", message_id=701),
    )

    asyncio.run(router.handle_update(update, FakeContext(bot=bot)))

    assert bot.sent_messages[-1]["text"] == "agent response"
    assert bot.sent_messages[-1]["reply_to_message_id"] == 701


def test_router_blocks_unauthorized_user_when_allowed_user_id_is_configured(tmp_path) -> None:
    pending_action_service, _broker = _pending_action_service(tmp_path)
    bot = FakeBot()
    router = TelegramUpdateRouter(
        access_policy=TelegramAccessPolicy.from_allowed_ids(
            "123",
            "1",
            silent_unauthorized=False,
        ),
        message_handler=lambda _message: "should not send",
        pending_action_service=pending_action_service,
    )
    update = FakeUpdate(
        effective_chat=FakeChat(123),
        effective_user=FakeUser(999),
        effective_message=FakeMessage("hello"),
    )

    asyncio.run(router.handle_update(update, FakeContext(bot=bot)))

    assert "not authorized" in str(bot.sent_messages[-1]["text"]).lower()


def test_router_approve_updates_linked_proposal_and_execution_journal(tmp_path) -> None:
    pending_action_service, proposal_service, broker = _persistence_services(tmp_path)
    history = ChatHistoryManager()
    proposal = proposal_service.create_submit_order_proposal(
        chat_id="123",
        user_id=1,
        intent_kind="propose_trade",
        original_user_message="buy tesla",
        action_summary="BUY TSLA_US_EQ via MARKET order",
        order_intent={"ticker": "TSLA_US_EQ", "side": "BUY", "quantity": "1"},
        thesis="User asked to enter Tesla.",
        risks=["Market volatility"],
        confidence=0.7,
    )
    action = pending_action_service.create_submit_action(
        chat_id="123",
        user_id=1,
        prepared_order=_prepared_order(),
        original_user_message="buy tesla",
        summary_text="Prepared TSLA order.",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    proposal_service.attach_pending_action(proposal.proposal_id, pending_action_id=action.action_id)
    pending_action_service.attach_approval_message_id(action.action_id, 501)
    bot = FakeBot()
    router = TelegramUpdateRouter(
        access_policy=TelegramAccessPolicy.from_allowed_chat_id(123),
        message_handler=lambda _message: None,
        history_manager=history,
        pending_action_service=pending_action_service,
        proposal_service=proposal_service,
    )
    update = FakeUpdate(
        effective_chat=FakeChat(123),
        effective_user=FakeUser(1),
        effective_message=FakeMessage("prepared order", message_id=501),
        callback_query=FakeCallbackQuery(
            data=f"pa:approve:{action.action_id}",
            message=FakeMessage("prepared order", message_id=501),
        ),
    )

    asyncio.run(router.handle_update(update, FakeContext(bot=bot)))
    detail = proposal_service.get_proposal(proposal.proposal_id)

    assert len(broker.submitted_orders) == 1
    assert detail is not None
    assert detail.proposal.status == ProposalStatus.SUBMITTED
    assert detail.latest_approval_event is not None
    assert detail.latest_approval_event.decision.value == "approve"
    assert detail.latest_execution_attempt is not None
    assert detail.latest_execution_attempt.action_kind == ProposalActionKind.SUBMIT_ORDER


def test_router_reject_updates_linked_proposal_and_allows_proposal_commands(tmp_path) -> None:
    pending_action_service, proposal_service, _broker = _persistence_services(tmp_path)
    history = ChatHistoryManager()
    proposal = proposal_service.create_submit_order_proposal(
        chat_id="123",
        user_id=1,
        intent_kind="propose_trade",
        original_user_message="buy tesla",
        action_summary="BUY TSLA_US_EQ via MARKET order",
        order_intent={"ticker": "TSLA_US_EQ", "side": "BUY", "quantity": "1"},
        thesis="User asked to enter Tesla.",
        risks=["Market volatility"],
        confidence=0.7,
    )
    action = pending_action_service.create_submit_action(
        chat_id="123",
        user_id=1,
        prepared_order=_prepared_order(),
        original_user_message="buy tesla",
        summary_text="Prepared TSLA order.",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    proposal_service.attach_pending_action(proposal.proposal_id, pending_action_id=action.action_id)
    pending_action_service.attach_approval_message_id(action.action_id, 601)

    router = TelegramUpdateRouter(
        access_policy=TelegramAccessPolicy.from_allowed_chat_id(123),
        message_handler=lambda _message: None,
        history_manager=history,
        pending_action_service=pending_action_service,
        proposal_service=proposal_service,
    )
    bot = FakeBot()
    reject_update = FakeUpdate(
        effective_chat=FakeChat(123),
        effective_user=FakeUser(1),
        effective_message=FakeMessage("prepared order", message_id=601),
        callback_query=FakeCallbackQuery(
            data=f"pa:reject:{action.action_id}",
            message=FakeMessage("prepared order", message_id=601),
        ),
    )

    asyncio.run(router.handle_update(reject_update, FakeContext(bot=bot)))
    detail = proposal_service.get_proposal(proposal.proposal_id)

    assert detail is not None
    assert detail.proposal.status == ProposalStatus.REJECTED
    assert detail.latest_approval_event is not None
    assert detail.latest_approval_event.decision.value == "reject"

    handler = build_default_message_handler(
        main_agent=object(),  # type: ignore[arg-type]
        history_manager=history,
        proposal_service=proposal_service,
    )
    recent_response = handler(
        TelegramInboundMessage(
            chat_id=123,
            user_id=1,
            text="/proposals",
            message_id=701,
        )
    )
    detail_response = handler(
        TelegramInboundMessage(
            chat_id=123,
            user_id=1,
            text=f"/proposal {proposal.proposal_id}",
            message_id=702,
        )
    )

    assert isinstance(recent_response, TelegramOutboundMessage)
    assert proposal.proposal_id in recent_response.text
    assert isinstance(detail_response, TelegramOutboundMessage)
    assert "Status: rejected" in detail_response.text
