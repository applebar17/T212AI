from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping

from t212ai.alpaca.base import (
    ALPACA_LIVE_TRADING_BASE_URL,
    ALPACA_MARKET_DATA_BASE_URL,
    ALPACA_PAPER_TRADING_BASE_URL,
)


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
    llm_provider: str = "none"
    broker_provider: str = "none"
    market_data_provider: str = "yahoo"
    market_intelligence_provider: str = "none"
    disclosure_provider: str = "sec_edgar"
    community_provider: str = "none"
    search_provider: str = "none"
    openai_api_key: str | None = None
    openai_chat_model_default: str = "gpt-4o-mini"
    openai_chat_model_smart: str = "gpt-4.1"
    openai_chat_model_reasoning: str = "o4-mini"
    openai_embed_model: str = "text-embedding-3-small"
    openai_embed_dimensions: str | None = None
    azure_openai_enabled: bool = False
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_embed_deployment: str | None = None
    trading212_environment: str = "demo"
    trading212_demo_base_url: str = "https://demo.trading212.com/api/v0"
    trading212_live_base_url: str = "https://live.trading212.com/api/v0"
    trading212_api_key: str | None = None
    trading212_api_secret: str | None = None
    telegram_bot_token: str | None = None
    telegram_allowed_chat_id: str | None = None
    telegram_allowed_user_id: str | None = None
    alpha_vantage_api_key: str | None = None
    alpha_vantage_base_url: str = "https://www.alphavantage.co/query"
    alpaca_api_key: str | None = None
    alpaca_api_secret: str | None = None
    alpaca_environment: str = "paper"
    alpaca_market_data_base_url: str = ALPACA_MARKET_DATA_BASE_URL
    alpaca_paper_trading_base_url: str = ALPACA_PAPER_TRADING_BASE_URL
    alpaca_live_trading_base_url: str = ALPACA_LIVE_TRADING_BASE_URL
    alpaca_data_feed: str = "iex"
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_username: str | None = None
    reddit_password: str | None = None
    reddit_refresh_token: str | None = None
    reddit_user_agent: str | None = None
    reddit_base_url: str = "https://oauth.reddit.com"
    reddit_auth_url: str = "https://www.reddit.com/api/v1/access_token"
    sec_edgar_user_agent: str | None = None
    sec_edgar_submissions_base_url: str = "https://data.sec.gov/submissions"
    sec_edgar_tickers_url: str = "https://www.sec.gov/files/company_tickers.json"
    yahoo_enabled: bool = False
    alpha_vantage_enabled: bool = False
    reddit_enabled: bool = False
    searxng_enabled: bool = False
    guideline_memory_path: str = "data/guidelines/guidelines.json"
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
        llm_provider=_resolve_llm_provider(source),
        broker_provider=_resolve_broker_provider(source),
        market_data_provider=_resolve_market_data_provider(source),
        market_intelligence_provider=_resolve_market_intelligence_provider(source),
        disclosure_provider=_resolve_disclosure_provider(source),
        community_provider=_resolve_community_provider(source),
        search_provider=_resolve_search_provider(source),
        openai_api_key=source.get("OPENAI_API_KEY"),
        openai_chat_model_default=source.get(
            "OPENAI_CHAT_MODEL_DEFAULT",
            "gpt-4o-mini",
        ),
        openai_chat_model_smart=source.get(
            "OPENAI_CHAT_MODEL_SMART",
            "gpt-4.1",
        ),
        openai_chat_model_reasoning=source.get(
            "OPENAI_CHAT_MODEL_REASONING",
            "o4-mini",
        ),
        openai_embed_model=source.get(
            "OPENAI_EMBED_MODEL",
            "text-embedding-3-small",
        ),
        openai_embed_dimensions=source.get("OPENAI_EMBED_DIMENSIONS"),
        azure_openai_enabled=_env_bool_from_source(source, "AZURE_OPENAI_ENABLED", False),
        azure_openai_endpoint=source.get("AZURE_OPENAI_ENDPOINT"),
        azure_openai_api_key=source.get("AZURE_OPENAI_API_KEY"),
        azure_openai_api_version=source.get(
            "AZURE_OPENAI_API_VERSION",
            "2024-10-21",
        ),
        azure_openai_embed_deployment=source.get("AZURE_OPENAI_EMBED_DEPLOYMENT"),
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
        telegram_allowed_user_id=source.get("TELEGRAM_ALLOWED_USER_ID"),
        alpha_vantage_api_key=source.get("ALPHA_VANTAGE_API_KEY"),
        alpha_vantage_base_url=source.get(
            "ALPHA_VANTAGE_BASE_URL",
            "https://www.alphavantage.co/query",
        ),
        alpaca_api_key=source.get("ALPACA_API_KEY"),
        alpaca_api_secret=source.get("ALPACA_API_SECRET"),
        alpaca_environment=source.get("ALPACA_ENVIRONMENT", "paper"),
        alpaca_market_data_base_url=source.get(
            "ALPACA_MARKET_DATA_BASE_URL",
            ALPACA_MARKET_DATA_BASE_URL,
        ),
        alpaca_paper_trading_base_url=source.get(
            "ALPACA_PAPER_TRADING_BASE_URL",
            ALPACA_PAPER_TRADING_BASE_URL,
        ),
        alpaca_live_trading_base_url=source.get(
            "ALPACA_LIVE_TRADING_BASE_URL",
            ALPACA_LIVE_TRADING_BASE_URL,
        ),
        alpaca_data_feed=source.get("ALPACA_DATA_FEED", "iex"),
        reddit_client_id=source.get("REDDIT_CLIENT_ID"),
        reddit_client_secret=source.get("REDDIT_CLIENT_SECRET"),
        reddit_username=source.get("REDDIT_USERNAME"),
        reddit_password=source.get("REDDIT_PASSWORD"),
        reddit_refresh_token=source.get("REDDIT_REFRESH_TOKEN"),
        reddit_user_agent=source.get("REDDIT_USER_AGENT"),
        reddit_base_url=source.get(
            "REDDIT_BASE_URL",
            "https://oauth.reddit.com",
        ),
        reddit_auth_url=source.get(
            "REDDIT_AUTH_URL",
            "https://www.reddit.com/api/v1/access_token",
        ),
        sec_edgar_user_agent=source.get("SEC_EDGAR_USER_AGENT"),
        sec_edgar_submissions_base_url=source.get(
            "SEC_EDGAR_SUBMISSIONS_BASE_URL",
            "https://data.sec.gov/submissions",
        ),
        sec_edgar_tickers_url=source.get(
            "SEC_EDGAR_TICKERS_URL",
            "https://www.sec.gov/files/company_tickers.json",
        ),
        yahoo_enabled=_resolve_market_data_provider(source) == "yahoo",
        alpha_vantage_enabled=_resolve_market_intelligence_provider(source)
        == "alpha_vantage",
        reddit_enabled=_resolve_community_provider(source) == "reddit",
        searxng_enabled=_resolve_search_provider(source) == "searxng",
        guideline_memory_path=source.get(
            "GUIDELINE_MEMORY_PATH",
            "data/guidelines/guidelines.json",
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


def _env_bool_or_fallback(
    source: Mapping[str, str],
    name: str,
    default: bool,
    *,
    fallback_keys: tuple[str, ...] = (),
) -> bool:
    if name in source:
        return _env_bool_from_source(source, name, default)
    return default or any(bool(str(source.get(key, "")).strip()) for key in fallback_keys)


def _resolve_llm_provider(source: Mapping[str, str]) -> str:
    explicit = str(source.get("LLM_PROVIDER", "")).strip().lower()
    if explicit:
        return explicit
    if _env_bool_from_source(source, "AZURE_OPENAI_ENABLED", False) or any(
        bool(str(source.get(key, "")).strip())
        for key in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY")
    ):
        return "azure_openai"
    if str(source.get("OPENAI_API_KEY", "")).strip():
        return "openai"
    return "none"


def _resolve_broker_provider(source: Mapping[str, str]) -> str:
    explicit = str(source.get("BROKER_PROVIDER", "")).strip().lower()
    if explicit:
        return explicit
    if any(
        bool(str(source.get(key, "")).strip())
        for key in ("T212_API_KEY", "T212_API_SECRET")
    ):
        return "trading212"
    return "none"


def _resolve_market_data_provider(source: Mapping[str, str]) -> str:
    explicit = str(source.get("MARKET_DATA_PROVIDER", "")).strip().lower()
    if explicit:
        return explicit
    has_alpaca = any(
        bool(str(source.get(key, "")).strip())
        for key in ("ALPACA_API_KEY", "ALPACA_API_SECRET")
    )
    if has_alpaca and "YAHOO_ENABLED" not in source:
        return "alpaca"
    if "YAHOO_ENABLED" in source:
        return "yahoo" if _env_bool_from_source(source, "YAHOO_ENABLED", False) else "none"
    return "yahoo"


def _resolve_market_intelligence_provider(source: Mapping[str, str]) -> str:
    explicit = str(source.get("MARKET_INTELLIGENCE_PROVIDER", "")).strip().lower()
    if explicit:
        return explicit
    if _env_bool_or_fallback(
        source,
        "ALPHA_VANTAGE_ENABLED",
        False,
        fallback_keys=("ALPHA_VANTAGE_API_KEY",),
    ):
        return "alpha_vantage"
    return "none"


def _resolve_disclosure_provider(source: Mapping[str, str]) -> str:
    explicit = str(source.get("DISCLOSURE_PROVIDER", "")).strip().lower()
    if explicit:
        return explicit
    return "sec_edgar"


def _resolve_community_provider(source: Mapping[str, str]) -> str:
    explicit = str(source.get("COMMUNITY_PROVIDER", "")).strip().lower()
    if explicit:
        return explicit
    if _env_bool_or_fallback(
        source,
        "REDDIT_ENABLED",
        False,
        fallback_keys=(
            "REDDIT_CLIENT_ID",
            "REDDIT_CLIENT_SECRET",
            "REDDIT_REFRESH_TOKEN",
            "REDDIT_USERNAME",
            "REDDIT_PASSWORD",
        ),
    ):
        return "reddit"
    return "none"


def _resolve_search_provider(source: Mapping[str, str]) -> str:
    explicit = str(source.get("SEARCH_PROVIDER", "")).strip().lower()
    if explicit:
        return explicit
    if _env_bool_or_fallback(
        source,
        "SEARXNG_ENABLED",
        False,
        fallback_keys=("SEARXNG_BASE_URL",),
    ):
        return "searxng"
    return "none"
