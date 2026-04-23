from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping


DEFAULT_ENV_FILE_NAME = ".env"


def load_env_file(
    path: str | Path | None = None,
    *,
    override: bool = False,
) -> dict[str, str]:
    """Load simple KEY=VALUE pairs from .env into os.environ.

    Existing process environment variables win by default. This keeps container,
    CI, and shell-provided values authoritative while making local development
    work from the repository .env file.
    """

    env_path = _resolve_env_file(path)
    if env_path is None or not env_path.exists():
        return {}

    parsed = parse_env_file(env_path)
    for key, value in parsed.items():
        if override or key not in os.environ:
            os.environ[key] = value
    return parsed


def parse_env_file(path: str | Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(raw_line)
        if parsed is None:
            continue
        key, value = parsed
        values[key] = value
    return values


def _resolve_env_file(path: str | Path | None) -> Path | None:
    if path is not None:
        return Path(path)

    current = Path.cwd()
    for candidate_root in [current, *current.parents]:
        candidate = candidate_root / DEFAULT_ENV_FILE_NAME
        if candidate.exists():
            return candidate
    return None


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped.removeprefix("export ").strip()
    if "=" not in stripped:
        return None

    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        return None

    return key, _clean_env_value(value)


def _clean_env_value(value: str) -> str:
    raw = value.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        return raw[1:-1]
    return _strip_inline_comment(raw).strip()


def _strip_inline_comment(value: str) -> str:
    in_single_quote = False
    in_double_quote = False
    for index, char in enumerate(value):
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
        elif char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
        elif char == "#" and not in_single_quote and not in_double_quote:
            if index == 0 or value[index - 1].isspace():
                return value[:index]
    return value


@dataclass(slots=True)
class AppSettings:
    trading212_environment: str = "demo"
    trading212_demo_base_url: str = "https://demo.trading212.com/api/v0"
    trading212_live_base_url: str = "https://live.trading212.com/api/v0"
    trading212_api_key: str | None = None
    trading212_api_secret: str | None = None
    telegram_bot_token: str | None = None
    telegram_allowed_chat_id: str | None = None
    alpha_vantage_api_key: str | None = None
    alpha_vantage_base_url: str = "https://www.alphavantage.co/query"
    database_url: str = "sqlite:///./data/t212ai.db"
    searxng_base_url: str | None = None
    live_trading_enabled: bool = False

    @property
    def trading212_base_url(self) -> str:
        environment = self.trading212_environment.strip().lower()
        if environment == "live":
            return self.trading212_live_base_url
        return self.trading212_demo_base_url


def get_app_settings(
    *,
    env_file: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> AppSettings:
    if env is None:
        load_env_file(env_file)
        source = os.environ
    else:
        source = env

    return AppSettings(
        trading212_environment=source.get("T212_ENVIRONMENT", "demo"),
        trading212_demo_base_url=source.get(
            "T212_DEMO_BASE_URL", "https://demo.trading212.com/api/v0"
        ),
        trading212_live_base_url=source.get(
            "T212_LIVE_BASE_URL", "https://live.trading212.com/api/v0"
        ),
        trading212_api_key=source.get("T212_API_KEY"),
        trading212_api_secret=source.get("T212_API_SECRET"),
        telegram_bot_token=source.get("TELEGRAM_BOT_TOKEN"),
        telegram_allowed_chat_id=source.get("TELEGRAM_ALLOWED_CHAT_ID"),
        alpha_vantage_api_key=source.get("ALPHA_VANTAGE_API_KEY"),
        alpha_vantage_base_url=source.get(
            "ALPHA_VANTAGE_BASE_URL",
            "https://www.alphavantage.co/query",
        ),
        database_url=source.get("DATABASE_URL", "sqlite:///./data/t212ai.db"),
        searxng_base_url=source.get("SEARXNG_BASE_URL"),
        live_trading_enabled=_env_bool_from_source(
            source,
            "T212_LIVE_TRADING_ENABLED",
            False,
        ),
    )


def _env_bool_from_source(
    source: Mapping[str, str],
    name: str,
    default: bool = False,
) -> bool:
    value = source.get(name)
    if value is None or not str(value).strip():
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}
