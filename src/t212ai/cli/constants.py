"""CLI option sets and managed environment sections."""

from __future__ import annotations

from t212ai.genai.context import ModelContextRegistry


LLM_PROVIDER_OPTIONS = (
    ("openai", "OpenAI"),
    ("azure_openai", "Azure OpenAI"),
    ("none", "Disabled"),
)
BROKER_PROVIDER_OPTIONS = (
    ("trading212", "Trading 212"),
    ("alpaca", "Alpaca"),
    ("none", "Disabled"),
)
MARKET_DATA_PROVIDER_OPTIONS = (
    ("yahoo", "Yahoo Finance"),
    ("alpaca", "Alpaca"),
    ("none", "Disabled"),
)
ENVIRONMENT_OPTIONS = (
    ("demo", "Demo"),
    ("live", "Live"),
)
ALPACA_ENVIRONMENT_OPTIONS = (
    ("paper", "Paper"),
    ("live", "Live"),
)
_MODEL_CONTEXT_REGISTRY = ModelContextRegistry()
OPENAI_DEFAULT_MODEL_OPTIONS = (
    ("gpt-4o-mini", "gpt-4o-mini - economical 4.x baseline"),
    ("gpt-4o", "gpt-4o - balanced 4.x baseline"),
    ("gpt-4.1-mini", "gpt-4.1-mini - efficient long-context 4.x baseline"),
    ("gpt-5-mini", "gpt-5-mini - efficient 5.x baseline"),
    ("gpt-5", "gpt-5 - stronger 5.x baseline"),
)
OPENAI_SMART_MODEL_OPTIONS = (
    ("gpt-4.1", "gpt-4.1 - long-context 4.x smart model"),
    ("gpt-4.1-mini", "gpt-4.1-mini - efficient 4.x smart model"),
    ("gpt-5", "gpt-5 - 5.x smart model"),
    ("gpt-5.2", "gpt-5.2 - newer 5.x smart model"),
    ("gpt-5.5", "gpt-5.5 - largest 5.x smart model"),
)
OPENAI_REASONING_MODEL_OPTIONS = (
    ("o4-mini", "o4-mini - efficient reasoning model"),
    ("o3-mini", "o3-mini - prior efficient reasoning model"),
    ("o3", "o3 - deeper reasoning model"),
    ("gpt-5", "gpt-5 - general 5.x reasoning model"),
    ("gpt-5.5", "gpt-5.5 - largest 5.x reasoning model"),
)
SECRET_KEYS = frozenset(
    {
        "OPENAI_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "LANGSMITH_API_KEY",
        "T212_DEMO_API_KEY",
        "T212_DEMO_API_SECRET",
        "T212_LIVE_API_KEY",
        "T212_LIVE_API_SECRET",
        "T212_API_KEY",
        "T212_API_SECRET",
        "ALPACA_PAPER_API_KEY",
        "ALPACA_PAPER_API_SECRET",
        "ALPACA_LIVE_API_KEY",
        "ALPACA_LIVE_API_SECRET",
        "ALPACA_API_KEY",
        "ALPACA_API_SECRET",
        "EODHD_API_TOKEN",
        "TELEGRAM_BOT_TOKEN",
    }
)
MANAGED_ENV_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Provider selection",
        (
            "LLM_PROVIDER",
            "BROKER_PROVIDER",
            "MARKET_DATA_PROVIDER",
            "MARKET_INTELLIGENCE_PROVIDER",
            "SYMBOL_REFERENCE_PROVIDER",
            "DISCLOSURE_PROVIDER",
            "COMMUNITY_PROVIDER",
            "SEARCH_PROVIDER",
            "YAHOO_ENABLED",
            "ALPHA_VANTAGE_ENABLED",
            "EODHD_ENABLED",
            "SEARXNG_ENABLED",
        ),
    ),
    (
        "OpenAI / Azure OpenAI",
        (
            "OPENAI_API_KEY",
            "OPENAI_CHAT_MODEL_DEFAULT",
            "OPENAI_CHAT_MODEL_SMART",
            "OPENAI_CHAT_MODEL_REASONING",
            "OPENAI_EMBED_MODEL",
            "OPENAI_EMBED_DIMENSIONS",
            "GENAI_CONTEXT_TOKENS_DEFAULT",
            "GENAI_CONTEXT_TOKENS_SMART",
            "GENAI_CONTEXT_TOKENS_REASONING",
            "GENAI_CONTEXT_TOKENS_BY_MODEL_JSON",
            "GENAI_CONTEXT_FALLBACK_TOKENS",
            "GENAI_CONTEXT_GUARD_RATIO",
            "GENAI_OUTPUT_RESERVE_TOKENS",
            "GENAI_CONTEXT_RECENT_MESSAGES",
            "GENAI_CONTEXT_SUMMARY_MAX_TOKENS",
            "AZURE_OPENAI_ENABLED",
            "AZURE_OPENAI_ENDPOINT",
            "AZURE_OPENAI_API_KEY",
            "AZURE_OPENAI_API_VERSION",
            "AZURE_OPENAI_EMBED_DEPLOYMENT",
        ),
    ),
    (
        "LangSmith observability",
        (
            "LANGSMITH_TRACING",
            "LANGSMITH_ENDPOINT",
            "LANGSMITH_API_KEY",
            "LANGSMITH_PROJECT",
        ),
    ),
    (
        "Broker providers",
        (
            "T212_ENVIRONMENT",
            "T212_DEMO_BASE_URL",
            "T212_LIVE_BASE_URL",
            "T212_DEMO_API_KEY",
            "T212_DEMO_API_SECRET",
            "T212_LIVE_API_KEY",
            "T212_LIVE_API_SECRET",
            "T212_API_KEY",
            "T212_API_SECRET",
            "T212_LIVE_TRADING_ENABLED",
            "ALPACA_ENVIRONMENT",
            "ALPACA_PAPER_API_KEY",
            "ALPACA_PAPER_API_SECRET",
            "ALPACA_LIVE_API_KEY",
            "ALPACA_LIVE_API_SECRET",
            "ALPACA_API_KEY",
            "ALPACA_API_SECRET",
            "ALPACA_MARKET_DATA_BASE_URL",
            "ALPACA_STREAM_BASE_URL",
            "ALPACA_STREAM_SANDBOX_BASE_URL",
            "ALPACA_PAPER_TRADING_BASE_URL",
            "ALPACA_LIVE_TRADING_BASE_URL",
            "ALPACA_DATA_FEED",
        ),
    ),
    (
        "Telegram",
        (
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_ALLOWED_CHAT_ID",
            "TELEGRAM_ALLOWED_USER_ID",
        ),
    ),
    (
        "Alpha Vantage",
        (
            "ALPHA_VANTAGE_API_KEY",
            "ALPHA_VANTAGE_BASE_URL",
        ),
    ),
    (
        "EODHD symbol reference",
        (
            "EODHD_API_TOKEN",
            "EODHD_BASE_URL",
        ),
    ),
    (
        "SEC EDGAR filing intelligence",
        (
            "SEC_EDGAR_USER_AGENT",
            "SEC_EDGAR_SUBMISSIONS_BASE_URL",
            "SEC_EDGAR_TICKERS_URL",
        ),
    ),
    (
        "Local persistence",
        (
            "APP_LOG_LEVEL",
            "APP_LOG_FILE_PATH",
            "APP_LOG_FORMAT",
            "APP_LOG_RETENTION_DAYS",
            "APP_LOG_THIRD_PARTY_LEVEL",
            "LOG_DIAGNOSTIC_AGENT_ENABLED",
            "LOG_DIAGNOSTIC_MAX_TOOL_CALLS",
            "LOG_DIAGNOSTIC_MAX_RECORDS",
            "LOG_DIAGNOSTIC_MAX_BYTES",
            "GUIDELINE_MEMORY_PATH",
            "DATABASE_URL",
        ),
    ),
    (
        "Scheduler defaults",
        (
            "SCHEDULER_DEFAULT_TIMEZONE",
            "SCHEDULER_DEFAULT_POLL_EVERY_SECONDS",
            "SCHEDULER_WORKER_ID",
            "SCHEDULER_LEASE_SECONDS",
            "SCHEDULER_STALE_RUN_AFTER_SECONDS",
            "SCHEDULER_MAX_LLM_RUNS_PER_PASS",
            "SCHEDULER_EMBEDDED_WORKER_ENABLED",
            "SCHEDULER_EMBEDDED_WORKER_POLL_EVERY_SECONDS",
            "SCHEDULER_EMBEDDED_WORKER_LIMIT",
            "ALPACA_NEWS_STREAM_SUPERVISOR_ENABLED",
            "ALPACA_NEWS_STREAM_SUPERVISOR_POLL_SECONDS",
            "ALPACA_NEWS_STREAM_LEASE_SECONDS",
            "ALPACA_NEWS_JUDGE_MAX_TOOL_CALLS",
        ),
    ),
    (
        "Research/search tools",
        ("SEARXNG_BASE_URL",),
    ),
)

LLM_SECTION_KEYS = (
    "LLM_PROVIDER",
    "OPENAI_API_KEY",
    "OPENAI_CHAT_MODEL_DEFAULT",
    "OPENAI_CHAT_MODEL_SMART",
    "OPENAI_CHAT_MODEL_REASONING",
    "OPENAI_EMBED_MODEL",
    "OPENAI_EMBED_DIMENSIONS",
    "GENAI_CONTEXT_TOKENS_DEFAULT",
    "GENAI_CONTEXT_TOKENS_SMART",
    "GENAI_CONTEXT_TOKENS_REASONING",
    "GENAI_CONTEXT_TOKENS_BY_MODEL_JSON",
    "GENAI_CONTEXT_FALLBACK_TOKENS",
    "GENAI_CONTEXT_GUARD_RATIO",
    "GENAI_OUTPUT_RESERVE_TOKENS",
    "GENAI_CONTEXT_RECENT_MESSAGES",
    "GENAI_CONTEXT_SUMMARY_MAX_TOKENS",
    "AZURE_OPENAI_ENABLED",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_API_VERSION",
    "AZURE_OPENAI_EMBED_DEPLOYMENT",
)

OBSERVABILITY_SECTION_KEYS = (
    "LANGSMITH_TRACING",
    "LANGSMITH_ENDPOINT",
    "LANGSMITH_API_KEY",
    "LANGSMITH_PROJECT",
)

BROKER_SECTION_KEYS = (
    "BROKER_PROVIDER",
    "T212_ENVIRONMENT",
    "T212_DEMO_API_KEY",
    "T212_DEMO_API_SECRET",
    "T212_LIVE_API_KEY",
    "T212_LIVE_API_SECRET",
    "T212_API_KEY",
    "T212_API_SECRET",
    "T212_LIVE_TRADING_ENABLED",
    "ALPACA_ENVIRONMENT",
    "ALPACA_PAPER_API_KEY",
    "ALPACA_PAPER_API_SECRET",
    "ALPACA_LIVE_API_KEY",
    "ALPACA_LIVE_API_SECRET",
    "ALPACA_API_KEY",
    "ALPACA_API_SECRET",
)

TELEGRAM_SECTION_KEYS = (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_CHAT_ID",
    "TELEGRAM_ALLOWED_USER_ID",
)

MARKET_DATA_SECTION_KEYS = (
    "MARKET_DATA_PROVIDER",
    "YAHOO_ENABLED",
    "ALPACA_ENVIRONMENT",
    "ALPACA_PAPER_API_KEY",
    "ALPACA_PAPER_API_SECRET",
    "ALPACA_LIVE_API_KEY",
    "ALPACA_LIVE_API_SECRET",
    "ALPACA_API_KEY",
    "ALPACA_API_SECRET",
)

ALPHA_VANTAGE_SECTION_KEYS = (
    "MARKET_INTELLIGENCE_PROVIDER",
    "ALPHA_VANTAGE_ENABLED",
    "ALPHA_VANTAGE_API_KEY",
)

SYMBOL_REFERENCE_SECTION_KEYS = (
    "SYMBOL_REFERENCE_PROVIDER",
    "EODHD_ENABLED",
    "EODHD_API_TOKEN",
    "EODHD_BASE_URL",
)

DISCLOSURE_SECTION_KEYS = (
    "DISCLOSURE_PROVIDER",
    "SEC_EDGAR_USER_AGENT",
)

SEARCH_SECTION_KEYS = (
    "SEARCH_PROVIDER",
    "SEARXNG_ENABLED",
    "SEARXNG_BASE_URL",
)

STORAGE_SECTION_KEYS = (
    "APP_LOG_LEVEL",
    "APP_LOG_FILE_PATH",
    "APP_LOG_FORMAT",
    "APP_LOG_RETENTION_DAYS",
    "APP_LOG_THIRD_PARTY_LEVEL",
    "LOG_DIAGNOSTIC_AGENT_ENABLED",
    "LOG_DIAGNOSTIC_MAX_TOOL_CALLS",
    "LOG_DIAGNOSTIC_MAX_RECORDS",
    "LOG_DIAGNOSTIC_MAX_BYTES",
    "DATABASE_URL",
    "GUIDELINE_MEMORY_PATH",
)

SCHEDULER_SECTION_KEYS = (
    "SCHEDULER_DEFAULT_TIMEZONE",
    "SCHEDULER_DEFAULT_POLL_EVERY_SECONDS",
    "SCHEDULER_WORKER_ID",
    "SCHEDULER_LEASE_SECONDS",
    "SCHEDULER_STALE_RUN_AFTER_SECONDS",
    "SCHEDULER_MAX_LLM_RUNS_PER_PASS",
    "SCHEDULER_EMBEDDED_WORKER_ENABLED",
    "SCHEDULER_EMBEDDED_WORKER_POLL_EVERY_SECONDS",
    "SCHEDULER_EMBEDDED_WORKER_LIMIT",
    "ALPACA_NEWS_STREAM_SUPERVISOR_ENABLED",
    "ALPACA_NEWS_STREAM_SUPERVISOR_POLL_SECONDS",
    "ALPACA_NEWS_STREAM_LEASE_SECONDS",
    "ALPACA_NEWS_JUDGE_MAX_TOOL_CALLS",
)
