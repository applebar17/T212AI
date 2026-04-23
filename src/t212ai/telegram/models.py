"""Telegram adapter data models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TelegramInboundMessage:
    chat_id: int
    text: str
    message_id: int | None = None
    user_id: int | None = None
    username: str | None = None
    first_name: str | None = None
    callback_data: str | None = None

    @property
    def is_command(self) -> bool:
        return self.text.strip().startswith("/")


@dataclass(frozen=True, slots=True)
class TelegramOutboundMessage:
    text: str
    parse_mode: str | None = None
    reply_to_message_id: int | None = None
    disable_web_page_preview: bool = True


@dataclass(frozen=True, slots=True)
class TelegramApprovalRequest:
    chat_id: int
    text: str
    approve_callback_data: str
    reject_callback_data: str
    parse_mode: str | None = None


def inbound_from_update(update: Any) -> TelegramInboundMessage | None:
    chat = getattr(update, "effective_chat", None)
    if chat is None or getattr(chat, "id", None) is None:
        return None

    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    callback_query = getattr(update, "callback_query", None)
    callback_data = getattr(callback_query, "data", None) if callback_query else None
    text = callback_data or getattr(message, "text", None) or ""
    if not str(text).strip():
        return None

    return TelegramInboundMessage(
        chat_id=int(chat.id),
        text=str(text).strip(),
        message_id=getattr(message, "message_id", None),
        user_id=getattr(user, "id", None),
        username=getattr(user, "username", None),
        first_name=getattr(user, "first_name", None),
        callback_data=callback_data,
    )
