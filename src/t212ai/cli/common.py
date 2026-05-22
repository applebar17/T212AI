from __future__ import annotations

from pathlib import Path

from t212ai.app.config import AppSettings, get_app_settings, parse_env_file
from t212ai.app.logging import configure_logging

from .constants import SECRET_KEYS


def load_settings_from_cli(*, env_file: str | None) -> AppSettings:
    if env_file is None:
        return get_app_settings()
    env_path = Path(env_file)
    raw = parse_env_file(env_path) if env_path.exists() else {}
    return get_app_settings(env=raw)


def _configure_app_logging(settings: AppSettings) -> None:
    configure_logging(
        settings.app_log_level,
        file_path=settings.app_log_file_path,
        file_format=settings.app_log_format,
        retention_days=settings.app_log_retention_days,
        third_party_level=settings.app_log_third_party_level,
    )


def _display_env_value(key: str, value: str) -> str:
    if key in SECRET_KEYS and value:
        return _mask_secret(value)
    return value or "<empty>"


def _mask_secret(value: str) -> str:
    if len(value) <= 4:
        return "*" * len(value)
    return value[:2] + "*" * (len(value) - 4) + value[-2:]


def _bool_to_env(value: bool) -> str:
    return "true" if value else "false"


def _env_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _safe_choice(value: str, allowed: set[str], default: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else default


def parse_duration_to_seconds(raw: str) -> int:
    value = str(raw or "").strip().lower()
    if not value:
        raise ValueError("Duration is required.")
    unit = value[-1]
    if unit not in {"s", "m", "h", "d"}:
        raise ValueError("Duration must end with s, m, h, or d.")
    amount = value[:-1]
    if not amount.isdigit():
        raise ValueError("Duration must start with an integer amount.")
    quantity = int(amount)
    if quantity <= 0:
        raise ValueError("Duration must be greater than zero.")
    if unit == "s":
        return quantity
    if unit == "m":
        return quantity * 60
    if unit == "h":
        return quantity * 3600
    return quantity * 86400
