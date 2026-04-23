"""Telegram access control for the personal bot."""

from __future__ import annotations

from dataclasses import dataclass

from t212ai.app.config import AppSettings


@dataclass(frozen=True, slots=True)
class TelegramAccessPolicy:
    allowed_chat_ids: frozenset[int]
    silent_unauthorized: bool = True

    @classmethod
    def from_settings(cls, settings: AppSettings) -> "TelegramAccessPolicy":
        return cls.from_allowed_chat_id(settings.telegram_allowed_chat_id)

    @classmethod
    def from_allowed_chat_id(
        cls,
        value: str | int | None,
        *,
        silent_unauthorized: bool = True,
    ) -> "TelegramAccessPolicy":
        if value is None or str(value).strip() == "":
            raise RuntimeError(
                "TELEGRAM_ALLOWED_CHAT_ID is required. The bot fails closed by default."
            )
        chat_ids: set[int] = set()
        for item in str(value).split(","):
            raw = item.strip()
            if not raw:
                continue
            try:
                chat_ids.add(int(raw))
            except ValueError as exc:
                raise RuntimeError(
                    f"Invalid TELEGRAM_ALLOWED_CHAT_ID value: {raw!r}."
                ) from exc
        if not chat_ids:
            raise RuntimeError("TELEGRAM_ALLOWED_CHAT_ID does not contain any chat id.")
        return cls(
            allowed_chat_ids=frozenset(chat_ids),
            silent_unauthorized=silent_unauthorized,
        )

    def is_allowed(self, chat_id: int | str | None) -> bool:
        if chat_id is None:
            return False
        try:
            resolved = int(chat_id)
        except (TypeError, ValueError):
            return False
        return resolved in self.allowed_chat_ids
