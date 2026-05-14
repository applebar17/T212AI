from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping

from t212ai.alpaca.base import (
    ALPACA_LIVE_TRADING_BASE_URL,
    ALPACA_MARKET_DATA_BASE_URL,
    ALPACA_PAPER_TRADING_BASE_URL,
    ALPACA_STREAM_BASE_URL,
    ALPACA_STREAM_SANDBOX_BASE_URL,
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
    genai_context_tokens_default: str | None = None
    genai_context_tokens_smart: str | None = None
    genai_context_tokens_reasoning: str | None = None
    genai_context_tokens_by_model_json: str | None = None
    genai_context_fallback_tokens: str = "128000"
    genai_context_guard_ratio: str = "0.95"
    genai_output_reserve_tokens: str = "1024"
    genai_context_recent_messages: str = "12"
    genai_context_summary_max_tokens: str = "1024"
    azure_openai_enabled: bool = False
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_embed_deployment: str | None = None
    trading212_environment: str = "demo"
    trading212_demo_base_url: str = "https://demo.trading212.com/api/v0"
    trading212_live_base_url: str = "https://live.trading212.com/api/v0"
    trading212_demo_api_key: str | None = None
    trading212_demo_api_secret: str | None = None
    trading212_live_api_key: str | None = None
    trading212_live_api_secret: str | None = None
    trading212_legacy_api_key: str | None = None
    trading212_legacy_api_secret: str | None = None
    trading212_api_key: str | None = None
    trading212_api_secret: str | None = None
    telegram_bot_token: str | None = None
    telegram_allowed_chat_id: str | None = None
    telegram_allowed_user_id: str | None = None
    alpha_vantage_api_key: str | None = None
    alpha_vantage_base_url: str = "https://www.alphavantage.co/query"
    alpaca_paper_api_key: str | None = None
    alpaca_paper_api_secret: str | None = None
    alpaca_live_api_key: str | None = None
    alpaca_live_api_secret: str | None = None
    alpaca_legacy_api_key: str | None = None
    alpaca_legacy_api_secret: str | None = None
    alpaca_api_key: str | None = None
    alpaca_api_secret: str | None = None
    alpaca_environment: str = "paper"
    alpaca_market_data_base_url: str = ALPACA_MARKET_DATA_BASE_URL
    alpaca_stream_base_url: str = ALPACA_STREAM_BASE_URL
    alpaca_stream_sandbox_base_url: str = ALPACA_STREAM_SANDBOX_BASE_URL
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
    app_log_level: str = "INFO"
    app_log_file_path: str = "data/logs/t212ai.log"
    app_log_format: str = "json"
    app_log_retention_days: int = 3
    app_log_third_party_level: str = "WARNING"
    log_diagnostic_agent_enabled: bool = False
    log_diagnostic_max_tool_calls: int = 10
    log_diagnostic_max_records: int = 500
    log_diagnostic_max_bytes: int = 262_144
    guideline_memory_path: str = "data/guidelines/guidelines.json"
    database_url: str = "sqlite:///./data/t212ai.db"
    scheduler_default_timezone: str = "UTC"
    scheduler_default_poll_every_seconds: int = 300
    scheduler_worker_id: str | None = None
    scheduler_lease_seconds: int = 1800
    scheduler_stale_run_after_seconds: int = 3600
    scheduler_max_llm_runs_per_pass: int = 0
    scheduler_embedded_worker_enabled: bool = True
    scheduler_embedded_worker_poll_every_seconds: int = 60
    scheduler_embedded_worker_limit: int = 100
    alpaca_news_stream_supervisor_enabled: bool = True
    alpaca_news_stream_supervisor_poll_seconds: int = 30
    alpaca_news_stream_lease_seconds: int = 120
    alpaca_news_judge_max_tool_calls: int = 10
    searxng_base_url: str | None = None
    live_trading_enabled: bool = False

    @property
    def trading212_base_url(self) -> str:
        environment = self.trading212_environment.strip().lower()
        if environment == "live":
            return self.trading212_live_base_url
        return self.trading212_demo_base_url

    @property
    def trading212_active_credential_keys(self) -> tuple[str, str]:
        environment = self.trading212_environment.strip().lower()
        if environment == "live":
            return ("T212_LIVE_API_KEY", "T212_LIVE_API_SECRET")
        return ("T212_DEMO_API_KEY", "T212_DEMO_API_SECRET")

    @property
    def alpaca_active_credential_keys(self) -> tuple[str, str]:
        environment = self.alpaca_environment.strip().lower()
        if environment == "live":
            return ("ALPACA_LIVE_API_KEY", "ALPACA_LIVE_API_SECRET")
        return ("ALPACA_PAPER_API_KEY", "ALPACA_PAPER_API_SECRET")


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

    trading212_environment = source.get("T212_ENVIRONMENT", "demo")
    alpaca_environment = source.get("ALPACA_ENVIRONMENT", "paper")

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
        genai_context_tokens_default=source.get("GENAI_CONTEXT_TOKENS_DEFAULT"),
        genai_context_tokens_smart=source.get("GENAI_CONTEXT_TOKENS_SMART"),
        genai_context_tokens_reasoning=source.get("GENAI_CONTEXT_TOKENS_REASONING"),
        genai_context_tokens_by_model_json=source.get(
            "GENAI_CONTEXT_TOKENS_BY_MODEL_JSON"
        ),
        genai_context_fallback_tokens=source.get(
            "GENAI_CONTEXT_FALLBACK_TOKENS",
            "128000",
        ),
        genai_context_guard_ratio=source.get("GENAI_CONTEXT_GUARD_RATIO", "0.95"),
        genai_output_reserve_tokens=source.get("GENAI_OUTPUT_RESERVE_TOKENS", "1024"),
        genai_context_recent_messages=source.get(
            "GENAI_CONTEXT_RECENT_MESSAGES",
            "12",
        ),
        genai_context_summary_max_tokens=source.get(
            "GENAI_CONTEXT_SUMMARY_MAX_TOKENS",
            "1024",
        ),
        azure_openai_enabled=_env_bool_from_source(source, "AZURE_OPENAI_ENABLED", False),
        azure_openai_endpoint=source.get("AZURE_OPENAI_ENDPOINT"),
        azure_openai_api_key=source.get("AZURE_OPENAI_API_KEY"),
        azure_openai_api_version=source.get(
            "AZURE_OPENAI_API_VERSION",
            "2024-10-21",
        ),
        azure_openai_embed_deployment=source.get("AZURE_OPENAI_EMBED_DEPLOYMENT"),
        trading212_environment=trading212_environment,
        trading212_demo_base_url=source.get(
            "T212_DEMO_BASE_URL", "https://demo.trading212.com/api/v0"
        ),
        trading212_live_base_url=source.get(
            "T212_LIVE_BASE_URL", "https://live.trading212.com/api/v0"
        ),
        trading212_demo_api_key=source.get("T212_DEMO_API_KEY"),
        trading212_demo_api_secret=source.get("T212_DEMO_API_SECRET"),
        trading212_live_api_key=source.get("T212_LIVE_API_KEY"),
        trading212_live_api_secret=source.get("T212_LIVE_API_SECRET"),
        trading212_legacy_api_key=source.get("T212_API_KEY"),
        trading212_legacy_api_secret=source.get("T212_API_SECRET"),
        trading212_api_key=_resolve_trading212_credential(
            source,
            trading212_environment,
            "key",
        ),
        trading212_api_secret=_resolve_trading212_credential(
            source,
            trading212_environment,
            "secret",
        ),
        telegram_bot_token=source.get("TELEGRAM_BOT_TOKEN"),
        telegram_allowed_chat_id=source.get("TELEGRAM_ALLOWED_CHAT_ID"),
        telegram_allowed_user_id=source.get("TELEGRAM_ALLOWED_USER_ID"),
        alpha_vantage_api_key=source.get("ALPHA_VANTAGE_API_KEY"),
        alpha_vantage_base_url=source.get(
            "ALPHA_VANTAGE_BASE_URL",
            "https://www.alphavantage.co/query",
        ),
        alpaca_paper_api_key=source.get("ALPACA_PAPER_API_KEY"),
        alpaca_paper_api_secret=source.get("ALPACA_PAPER_API_SECRET"),
        alpaca_live_api_key=source.get("ALPACA_LIVE_API_KEY"),
        alpaca_live_api_secret=source.get("ALPACA_LIVE_API_SECRET"),
        alpaca_legacy_api_key=source.get("ALPACA_API_KEY"),
        alpaca_legacy_api_secret=source.get("ALPACA_API_SECRET"),
        alpaca_api_key=_resolve_alpaca_credential(source, alpaca_environment, "key"),
        alpaca_api_secret=_resolve_alpaca_credential(source, alpaca_environment, "secret"),
        alpaca_environment=alpaca_environment,
        alpaca_market_data_base_url=source.get(
            "ALPACA_MARKET_DATA_BASE_URL",
            ALPACA_MARKET_DATA_BASE_URL,
        ),
        alpaca_stream_base_url=source.get(
            "ALPACA_STREAM_BASE_URL",
            ALPACA_STREAM_BASE_URL,
        ),
        alpaca_stream_sandbox_base_url=source.get(
            "ALPACA_STREAM_SANDBOX_BASE_URL",
            ALPACA_STREAM_SANDBOX_BASE_URL,
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
        app_log_level=source.get("APP_LOG_LEVEL", "INFO"),
        app_log_file_path=source.get("APP_LOG_FILE_PATH", "data/logs/t212ai.log"),
        app_log_format=source.get("APP_LOG_FORMAT", "json"),
        app_log_retention_days=_env_int_from_source(source, "APP_LOG_RETENTION_DAYS", 3),
        app_log_third_party_level=source.get("APP_LOG_THIRD_PARTY_LEVEL", "WARNING"),
        log_diagnostic_agent_enabled=_env_bool_from_source(
            source,
            "LOG_DIAGNOSTIC_AGENT_ENABLED",
            False,
        ),
        log_diagnostic_max_tool_calls=_env_non_negative_int_from_source(
            source,
            "LOG_DIAGNOSTIC_MAX_TOOL_CALLS",
            10,
        ),
        log_diagnostic_max_records=_env_int_from_source(
            source,
            "LOG_DIAGNOSTIC_MAX_RECORDS",
            500,
        ),
        log_diagnostic_max_bytes=_env_int_from_source(
            source,
            "LOG_DIAGNOSTIC_MAX_BYTES",
            262_144,
        ),
        guideline_memory_path=source.get(
            "GUIDELINE_MEMORY_PATH",
            "data/guidelines/guidelines.json",
        ),
        database_url=source.get("DATABASE_URL", "sqlite:///./data/t212ai.db"),
        scheduler_default_timezone=source.get("SCHEDULER_DEFAULT_TIMEZONE", "UTC"),
        scheduler_default_poll_every_seconds=_env_int_from_source(
            source,
            "SCHEDULER_DEFAULT_POLL_EVERY_SECONDS",
            300,
        ),
        scheduler_worker_id=source.get("SCHEDULER_WORKER_ID"),
        scheduler_lease_seconds=_env_int_from_source(
            source,
            "SCHEDULER_LEASE_SECONDS",
            1800,
        ),
        scheduler_stale_run_after_seconds=_env_int_from_source(
            source,
            "SCHEDULER_STALE_RUN_AFTER_SECONDS",
            3600,
        ),
        scheduler_max_llm_runs_per_pass=_env_non_negative_int_from_source(
            source,
            "SCHEDULER_MAX_LLM_RUNS_PER_PASS",
            0,
        ),
        scheduler_embedded_worker_enabled=_env_bool_from_source(
            source,
            "SCHEDULER_EMBEDDED_WORKER_ENABLED",
            True,
        ),
        scheduler_embedded_worker_poll_every_seconds=_env_int_from_source(
            source,
            "SCHEDULER_EMBEDDED_WORKER_POLL_EVERY_SECONDS",
            60,
        ),
        scheduler_embedded_worker_limit=_env_int_from_source(
            source,
            "SCHEDULER_EMBEDDED_WORKER_LIMIT",
            100,
        ),
        alpaca_news_stream_supervisor_enabled=_env_bool_from_source(
            source,
            "ALPACA_NEWS_STREAM_SUPERVISOR_ENABLED",
            True,
        ),
        alpaca_news_stream_supervisor_poll_seconds=_env_int_from_source(
            source,
            "ALPACA_NEWS_STREAM_SUPERVISOR_POLL_SECONDS",
            30,
        ),
        alpaca_news_stream_lease_seconds=_env_int_from_source(
            source,
            "ALPACA_NEWS_STREAM_LEASE_SECONDS",
            120,
        ),
        alpaca_news_judge_max_tool_calls=_env_non_negative_int_from_source(
            source,
            "ALPACA_NEWS_JUDGE_MAX_TOOL_CALLS",
            10,
        ),
        searxng_base_url=source.get("SEARXNG_BASE_URL"),
        live_trading_enabled=_env_bool_from_source(
            source,
            "T212_LIVE_TRADING_ENABLED",
            False,
        ),
    )


def _env_int_from_source(
    source: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    value = source.get(name)
    if value is None or not str(value).strip():
        return default
    try:
        parsed = int(str(value).strip())
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _env_non_negative_int_from_source(
    source: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    value = source.get(name)
    if value is None or not str(value).strip():
        return default
    try:
        parsed = int(str(value).strip())
    except ValueError:
        return default
    return parsed if parsed >= 0 else default


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
        for key in (
            "T212_API_KEY",
            "T212_API_SECRET",
            "T212_DEMO_API_KEY",
            "T212_DEMO_API_SECRET",
            "T212_LIVE_API_KEY",
            "T212_LIVE_API_SECRET",
        )
    ):
        return "trading212"
    return "none"


def _resolve_trading212_credential(
    source: Mapping[str, str],
    environment: str,
    kind: str,
) -> str | None:
    normalized_environment = str(environment or "").strip().lower()
    suffix = "API_KEY" if kind == "key" else "API_SECRET"
    environment_prefix = "T212_LIVE" if normalized_environment == "live" else "T212_DEMO"
    return _first_non_empty(
        source.get(f"{environment_prefix}_{suffix}"),
        source.get(f"T212_{suffix}"),
    )


def _resolve_alpaca_credential(
    source: Mapping[str, str],
    environment: str,
    kind: str,
) -> str | None:
    normalized_environment = str(environment or "").strip().lower()
    suffix = "API_KEY" if kind == "key" else "API_SECRET"
    environment_prefix = "ALPACA_LIVE" if normalized_environment == "live" else "ALPACA_PAPER"
    return _first_non_empty(
        source.get(f"{environment_prefix}_{suffix}"),
        source.get(f"ALPACA_{suffix}"),
    )


def _first_non_empty(*values: str | None) -> str | None:
    for value in values:
        if str(value or "").strip():
            return value
    return None


def _resolve_market_data_provider(source: Mapping[str, str]) -> str:
    explicit = str(source.get("MARKET_DATA_PROVIDER", "")).strip().lower()
    if explicit:
        return explicit
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
