"""Telegram bot service."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from t212ai.app.config import AppSettings, get_app_settings

from .auth import TelegramAccessPolicy
from .bridge import (
    TelegramMessageHandler,
    TelegramUpdateRouter,
    build_default_message_handler,
)


@dataclass(slots=True)
class TelegramBotService:
    token: str
    access_policy: TelegramAccessPolicy
    message_handler: TelegramMessageHandler = field(default_factory=build_default_message_handler)

    @classmethod
    def from_settings(
        cls,
        settings: AppSettings | None = None,
        *,
        message_handler: TelegramMessageHandler | None = None,
    ) -> "TelegramBotService":
        resolved = settings or get_app_settings()
        if not resolved.telegram_bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required to start the Telegram bot.")
        return cls(
            token=resolved.telegram_bot_token,
            access_policy=TelegramAccessPolicy.from_settings(resolved),
            message_handler=message_handler or build_default_message_handler(),
        )

    def build_application(self) -> Any:
        try:
            from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters
        except ImportError as exc:  # pragma: no cover - optional dependency path
            raise RuntimeError(
                "python-telegram-bot is required. Install the telegram optional extra."
            ) from exc

        router = TelegramUpdateRouter(
            access_policy=self.access_policy,
            message_handler=self.message_handler,
        )
        application = Application.builder().token(self.token).build()
        application.add_handler(CallbackQueryHandler(router.handle_update))
        application.add_handler(MessageHandler(filters.TEXT, router.handle_update))
        return application

    def run_polling(self) -> None:
        application = self.build_application()
        application.run_polling()
