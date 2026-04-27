"""Outbound Telegram messaging helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import TelegramApprovalRequest, TelegramOutboundMessage


@dataclass(slots=True)
class TelegramMessenger:
    """Small wrapper over the python-telegram-bot Bot object."""

    bot: Any

    async def send_message(
        self,
        chat_id: int,
        message: str | TelegramOutboundMessage,
    ) -> Any:
        outbound = (
            message
            if isinstance(message, TelegramOutboundMessage)
            else TelegramOutboundMessage(text=str(message))
        )
        return await self.bot.send_message(
            chat_id=chat_id,
            text=outbound.text,
            parse_mode=outbound.parse_mode,
            reply_to_message_id=outbound.reply_to_message_id,
            disable_web_page_preview=outbound.disable_web_page_preview,
        )

    async def send_error(
        self,
        chat_id: int,
        message: str,
        *,
        hint: str | None = None,
    ) -> Any:
        text = f"Error: {message}"
        if hint:
            text = f"{text}\n\nSuggested next step: {hint}"
        return await self.send_message(chat_id, text)

    async def send_approval_request(self, request: TelegramApprovalRequest) -> Any:
        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        except ImportError as exc:  # pragma: no cover - optional dependency path
            raise RuntimeError(
                "python-telegram-bot is required to send approval requests."
            ) from exc

        reply_markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Approve",
                        callback_data=request.approve_callback_data,
                    ),
                    InlineKeyboardButton(
                        "Reject",
                        callback_data=request.reject_callback_data,
                    ),
                ]
            ]
        )
        return await self.bot.send_message(
            chat_id=request.chat_id,
            text=request.text,
            parse_mode=request.parse_mode,
            reply_markup=reply_markup,
            reply_to_message_id=request.reply_to_message_id,
            disable_web_page_preview=True,
        )

    async def edit_message(
        self,
        *,
        chat_id: int,
        message_id: int,
        text: str,
        parse_mode: str | None = None,
    ) -> Any:
        return await self.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
            reply_markup=None,
        )
