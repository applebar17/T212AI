from __future__ import annotations

from dataclasses import dataclass
import os


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


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


def get_app_settings() -> AppSettings:
    return AppSettings(
        trading212_environment=os.getenv("T212_ENVIRONMENT", "demo"),
        trading212_demo_base_url=os.getenv(
            "T212_DEMO_BASE_URL", "https://demo.trading212.com/api/v0"
        ),
        trading212_live_base_url=os.getenv(
            "T212_LIVE_BASE_URL", "https://live.trading212.com/api/v0"
        ),
        trading212_api_key=os.getenv("T212_API_KEY"),
        trading212_api_secret=os.getenv("T212_API_SECRET"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        telegram_allowed_chat_id=os.getenv("TELEGRAM_ALLOWED_CHAT_ID"),
        alpha_vantage_api_key=os.getenv("ALPHA_VANTAGE_API_KEY"),
        alpha_vantage_base_url=os.getenv(
            "ALPHA_VANTAGE_BASE_URL",
            "https://www.alphavantage.co/query",
        ),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./data/t212ai.db"),
        searxng_base_url=os.getenv("SEARXNG_BASE_URL"),
        live_trading_enabled=_env_bool("T212_LIVE_TRADING_ENABLED", False),
    )
