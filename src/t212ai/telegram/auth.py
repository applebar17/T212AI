"""Telegram access control for the personal bot."""

from __future__ import annotations

from dataclasses import dataclass

from t212ai.app.config import AppSettings


@dataclass(frozen=True, slots=True)
class TelegramAccessPolicy:
    allowed_chat_ids: frozenset[int]
    allowed_user_ids: frozenset[int] = frozenset()
    silent_unauthorized: bool = True

    @classmethod
    def from_settings(cls, settings: AppSettings) -> "TelegramAccessPolicy":
        return cls.from_allowed_ids(
            settings.telegram_allowed_chat_id,
            settings.telegram_allowed_user_id,
        )

    @classmethod
    def from_allowed_ids(
        cls,
        chat_value: str | int | None,
        user_value: str | int | None = None,
        *,
        silent_unauthorized: bool = True,
    ) -> "TelegramAccessPolicy":
        if chat_value is None or str(chat_value).strip() == "":
            raise RuntimeError(
                "TELEGRAM_ALLOWED_CHAT_ID is required. The bot fails closed by default."
            )
        chat_ids = _parse_id_list(
            chat_value,
            env_name="TELEGRAM_ALLOWED_CHAT_ID",
        )
        if not chat_ids:
            raise RuntimeError("TELEGRAM_ALLOWED_CHAT_ID does not contain any chat id.")
        user_ids = _parse_id_list(
            user_value,
            env_name="TELEGRAM_ALLOWED_USER_ID",
            required=False,
        )
        return cls(
            allowed_chat_ids=frozenset(chat_ids),
            allowed_user_ids=frozenset(user_ids),
            silent_unauthorized=silent_unauthorized,
        )

    @classmethod
    def from_allowed_chat_id(
        cls,
        value: str | int | None,
        *,
        silent_unauthorized: bool = True,
    ) -> "TelegramAccessPolicy":
        return cls.from_allowed_ids(
            value,
            None,
            silent_unauthorized=silent_unauthorized,
        )

    def is_allowed(self, chat_id: int | str | None, user_id: int | str | None = None) -> bool:
        if chat_id is None:
            return False
        try:
            resolved_chat = int(chat_id)
        except (TypeError, ValueError):
            return False
        if resolved_chat not in self.allowed_chat_ids:
            return False
        if not self.allowed_user_ids:
            return True
        if user_id is None:
            return False
        try:
            resolved_user = int(user_id)
        except (TypeError, ValueError):
            return False
        return resolved_user in self.allowed_user_ids


def _parse_id_list(
    value: str | int | None,
    *,
    env_name: str,
    required: bool = True,
) -> set[int]:
    if value is None or str(value).strip() == "":
        if required:
            raise RuntimeError(f"{env_name} is required.")
        return set()
    ids: set[int] = set()
    for item in str(value).split(","):
        raw = item.strip()
        if not raw:
            continue
        try:
            ids.add(int(raw))
        except ValueError as exc:
            raise RuntimeError(f"Invalid {env_name} value: {raw!r}.") from exc
    return ids
