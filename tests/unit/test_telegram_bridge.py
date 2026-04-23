from __future__ import annotations

import asyncio
from dataclasses import dataclass

from t212ai.telegram import (
    TelegramAccessPolicy,
    TelegramBotService,
    TelegramInboundMessage,
    TelegramOutboundMessage,
    TelegramUpdateRouter,
    build_default_message_handler,
)


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


class FakeBot:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, object]] = []

    async def send_message(self, **kwargs: object) -> dict[str, object]:
        self.sent_messages.append(kwargs)
        return kwargs


@dataclass(slots=True)
class FakeContext:
    bot: FakeBot


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
