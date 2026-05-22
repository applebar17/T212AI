from __future__ import annotations

import argparse
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from t212ai.app.bootstrap import (
    assess_settings,
    ensure_runtime_directories,
    run_provider_smoke_tests,
)
from t212ai.app.config import get_app_settings, parse_env_file
from t212ai.genai.context import (
    DEFAULT_CONTEXT_FALLBACK_TOKENS,
    MIN_CONFIGURABLE_CONTEXT_TOKENS,
    parse_context_token_value,
)

from .common import _bool_to_env, _env_truthy, _safe_choice
from .constants import (
    ALPHA_VANTAGE_SECTION_KEYS,
    ALPACA_ENVIRONMENT_OPTIONS,
    BROKER_PROVIDER_OPTIONS,
    BROKER_SECTION_KEYS,
    DISCLOSURE_SECTION_KEYS,
    ENVIRONMENT_OPTIONS,
    LLM_PROVIDER_OPTIONS,
    LLM_SECTION_KEYS,
    MANAGED_ENV_SECTIONS,
    MARKET_DATA_PROVIDER_OPTIONS,
    MARKET_DATA_SECTION_KEYS,
    OBSERVABILITY_SECTION_KEYS,
    OPENAI_DEFAULT_MODEL_OPTIONS,
    OPENAI_REASONING_MODEL_OPTIONS,
    OPENAI_SMART_MODEL_OPTIONS,
    SCHEDULER_SECTION_KEYS,
    STORAGE_SECTION_KEYS,
    TELEGRAM_SECTION_KEYS,
    _MODEL_CONTEXT_REGISTRY,
)
from .io import TerminalIO
from .reports import render_configuration_review, render_provider_smoke_report
from .style import render_banner, render_box, render_step_intro


def command_configure(args: argparse.Namespace) -> int:
    env_path = Path(args.env_file)
    existing_raw = parse_env_file(env_path) if env_path.exists() else {}
    io_runtime = TerminalIO()
    io_runtime.write(render_banner("T212AI"))
    io_runtime.write("brokerai configuration wizard")
    io_runtime.write(f"Target env file: {env_path}")
    if existing_raw:
        io_runtime.write(
            render_box(
                "Existing configuration detected. Sections with current values can be "
                "skipped to keep them unchanged.",
                title="Existing config",
            )
        )
    io_runtime.write("")

    updates = build_managed_env_values(existing_raw)
    apply_configuration_wizard(io_runtime, updates, existing_raw=existing_raw)
    _drop_new_empty_inactive_broker_credentials(updates, existing_raw=existing_raw)

    io_runtime.write("")
    io_runtime.write(render_configuration_review(updates))
    io_runtime.write("")
    if not io_runtime.confirm("Write these settings to disk?", default=True):
        io_runtime.write("Configuration aborted. No changes were written.")
        return 1

    update_env_file(env_path, updates)
    settings = get_app_settings(env=updates)
    directories = ensure_runtime_directories(settings)
    assessment = assess_settings(settings)
    smoke_results = run_provider_smoke_tests(settings, assessment)
    io_runtime.write(f"Saved configuration to {env_path}.")
    io_runtime.write("Ensured local directories:")
    for directory in directories:
        io_runtime.write(f"- {directory}")
    io_runtime.write("")
    io_runtime.write("Provider readiness:")
    io_runtime.write(render_provider_smoke_report(smoke_results))
    return 0


def build_managed_env_values(existing_raw: Mapping[str, str]) -> dict[str, str]:
    settings = get_app_settings(env=existing_raw)
    t212_environment = _safe_choice(settings.trading212_environment, {"demo", "live"}, "demo")
    alpaca_environment = _safe_choice(settings.alpaca_environment, {"paper", "live"}, "paper")
    values = {
        "LLM_PROVIDER": settings.llm_provider,
        "BROKER_PROVIDER": settings.broker_provider,
        "MARKET_DATA_PROVIDER": settings.market_data_provider,
        "MARKET_INTELLIGENCE_PROVIDER": settings.market_intelligence_provider,
        "DISCLOSURE_PROVIDER": settings.disclosure_provider,
        "COMMUNITY_PROVIDER": settings.community_provider,
        "SEARCH_PROVIDER": settings.search_provider,
        "YAHOO_ENABLED": _bool_to_env(settings.yahoo_enabled),
        "ALPHA_VANTAGE_ENABLED": _bool_to_env(settings.alpha_vantage_enabled),
        "SEARXNG_ENABLED": _bool_to_env(settings.searxng_enabled),
        "OPENAI_API_KEY": existing_raw.get("OPENAI_API_KEY", settings.openai_api_key or ""),
        "OPENAI_CHAT_MODEL_DEFAULT": existing_raw.get(
            "OPENAI_CHAT_MODEL_DEFAULT",
            "gpt-4o-mini",
        ),
        "OPENAI_CHAT_MODEL_SMART": existing_raw.get("OPENAI_CHAT_MODEL_SMART", "gpt-4.1"),
        "OPENAI_CHAT_MODEL_REASONING": existing_raw.get(
            "OPENAI_CHAT_MODEL_REASONING",
            "o4-mini",
        ),
        "OPENAI_EMBED_MODEL": existing_raw.get(
            "OPENAI_EMBED_MODEL",
            "text-embedding-3-small",
        ),
        "OPENAI_EMBED_DIMENSIONS": existing_raw.get(
            "OPENAI_EMBED_DIMENSIONS",
            "",
        ),
        "GENAI_CONTEXT_TOKENS_DEFAULT": existing_raw.get(
            "GENAI_CONTEXT_TOKENS_DEFAULT",
            settings.genai_context_tokens_default or "",
        ),
        "GENAI_CONTEXT_TOKENS_SMART": existing_raw.get(
            "GENAI_CONTEXT_TOKENS_SMART",
            settings.genai_context_tokens_smart or "",
        ),
        "GENAI_CONTEXT_TOKENS_REASONING": existing_raw.get(
            "GENAI_CONTEXT_TOKENS_REASONING",
            settings.genai_context_tokens_reasoning or "",
        ),
        "GENAI_CONTEXT_TOKENS_BY_MODEL_JSON": existing_raw.get(
            "GENAI_CONTEXT_TOKENS_BY_MODEL_JSON",
            settings.genai_context_tokens_by_model_json or "",
        ),
        "GENAI_CONTEXT_FALLBACK_TOKENS": existing_raw.get(
            "GENAI_CONTEXT_FALLBACK_TOKENS",
            settings.genai_context_fallback_tokens,
        ),
        "GENAI_CONTEXT_GUARD_RATIO": existing_raw.get(
            "GENAI_CONTEXT_GUARD_RATIO",
            settings.genai_context_guard_ratio,
        ),
        "GENAI_OUTPUT_RESERVE_TOKENS": existing_raw.get(
            "GENAI_OUTPUT_RESERVE_TOKENS",
            settings.genai_output_reserve_tokens,
        ),
        "GENAI_CONTEXT_RECENT_MESSAGES": existing_raw.get(
            "GENAI_CONTEXT_RECENT_MESSAGES",
            settings.genai_context_recent_messages,
        ),
        "GENAI_CONTEXT_SUMMARY_MAX_TOKENS": existing_raw.get(
            "GENAI_CONTEXT_SUMMARY_MAX_TOKENS",
            settings.genai_context_summary_max_tokens,
        ),
        "AZURE_OPENAI_ENABLED": existing_raw.get(
            "AZURE_OPENAI_ENABLED",
            _bool_to_env(settings.llm_provider == "azure_openai"),
        ),
        "AZURE_OPENAI_ENDPOINT": existing_raw.get(
            "AZURE_OPENAI_ENDPOINT",
            settings.azure_openai_endpoint or "",
        ),
        "AZURE_OPENAI_API_KEY": existing_raw.get(
            "AZURE_OPENAI_API_KEY",
            settings.azure_openai_api_key or "",
        ),
        "AZURE_OPENAI_API_VERSION": existing_raw.get(
            "AZURE_OPENAI_API_VERSION",
            settings.azure_openai_api_version,
        ),
        "AZURE_OPENAI_EMBED_DEPLOYMENT": existing_raw.get(
            "AZURE_OPENAI_EMBED_DEPLOYMENT",
            settings.azure_openai_embed_deployment or "",
        ),
        "LANGSMITH_TRACING": existing_raw.get("LANGSMITH_TRACING", "false"),
        "LANGSMITH_ENDPOINT": existing_raw.get(
            "LANGSMITH_ENDPOINT",
            "https://eu.api.smith.langchain.com",
        ),
        "LANGSMITH_API_KEY": existing_raw.get("LANGSMITH_API_KEY", ""),
        "LANGSMITH_PROJECT": existing_raw.get("LANGSMITH_PROJECT", "T212AI"),
        "T212_ENVIRONMENT": existing_raw.get("T212_ENVIRONMENT", t212_environment),
        "T212_DEMO_BASE_URL": existing_raw.get(
            "T212_DEMO_BASE_URL",
            settings.trading212_demo_base_url,
        ),
        "T212_LIVE_BASE_URL": existing_raw.get(
            "T212_LIVE_BASE_URL",
            settings.trading212_live_base_url,
        ),
        "T212_DEMO_API_KEY": existing_raw.get(
            "T212_DEMO_API_KEY",
            existing_raw.get("T212_API_KEY", "") if t212_environment == "demo" else "",
        ),
        "T212_DEMO_API_SECRET": existing_raw.get(
            "T212_DEMO_API_SECRET",
            existing_raw.get("T212_API_SECRET", "") if t212_environment == "demo" else "",
        ),
        "T212_LIVE_API_KEY": existing_raw.get(
            "T212_LIVE_API_KEY",
            existing_raw.get("T212_API_KEY", "") if t212_environment == "live" else "",
        ),
        "T212_LIVE_API_SECRET": existing_raw.get(
            "T212_LIVE_API_SECRET",
            existing_raw.get("T212_API_SECRET", "") if t212_environment == "live" else "",
        ),
        "T212_LIVE_TRADING_ENABLED": existing_raw.get(
            "T212_LIVE_TRADING_ENABLED",
            _bool_to_env(settings.live_trading_enabled),
        ),
        "TELEGRAM_BOT_TOKEN": existing_raw.get(
            "TELEGRAM_BOT_TOKEN",
            settings.telegram_bot_token or "",
        ),
        "TELEGRAM_ALLOWED_CHAT_ID": existing_raw.get(
            "TELEGRAM_ALLOWED_CHAT_ID",
            settings.telegram_allowed_chat_id or "",
        ),
        "TELEGRAM_ALLOWED_USER_ID": existing_raw.get(
            "TELEGRAM_ALLOWED_USER_ID",
            settings.telegram_allowed_user_id or "",
        ),
        "ALPHA_VANTAGE_API_KEY": existing_raw.get(
            "ALPHA_VANTAGE_API_KEY",
            settings.alpha_vantage_api_key or "",
        ),
        "ALPHA_VANTAGE_BASE_URL": existing_raw.get(
            "ALPHA_VANTAGE_BASE_URL",
            settings.alpha_vantage_base_url,
        ),
        "ALPACA_ENVIRONMENT": existing_raw.get("ALPACA_ENVIRONMENT", alpaca_environment),
        "ALPACA_PAPER_API_KEY": existing_raw.get(
            "ALPACA_PAPER_API_KEY",
            existing_raw.get("ALPACA_API_KEY", "") if alpaca_environment == "paper" else "",
        ),
        "ALPACA_PAPER_API_SECRET": existing_raw.get(
            "ALPACA_PAPER_API_SECRET",
            existing_raw.get("ALPACA_API_SECRET", "") if alpaca_environment == "paper" else "",
        ),
        "ALPACA_LIVE_API_KEY": existing_raw.get(
            "ALPACA_LIVE_API_KEY",
            existing_raw.get("ALPACA_API_KEY", "") if alpaca_environment == "live" else "",
        ),
        "ALPACA_LIVE_API_SECRET": existing_raw.get(
            "ALPACA_LIVE_API_SECRET",
            existing_raw.get("ALPACA_API_SECRET", "") if alpaca_environment == "live" else "",
        ),
        "ALPACA_MARKET_DATA_BASE_URL": existing_raw.get(
            "ALPACA_MARKET_DATA_BASE_URL",
            settings.alpaca_market_data_base_url,
        ),
        "ALPACA_STREAM_BASE_URL": existing_raw.get(
            "ALPACA_STREAM_BASE_URL",
            settings.alpaca_stream_base_url,
        ),
        "ALPACA_STREAM_SANDBOX_BASE_URL": existing_raw.get(
            "ALPACA_STREAM_SANDBOX_BASE_URL",
            settings.alpaca_stream_sandbox_base_url,
        ),
        "ALPACA_PAPER_TRADING_BASE_URL": existing_raw.get(
            "ALPACA_PAPER_TRADING_BASE_URL",
            settings.alpaca_paper_trading_base_url,
        ),
        "ALPACA_LIVE_TRADING_BASE_URL": existing_raw.get(
            "ALPACA_LIVE_TRADING_BASE_URL",
            settings.alpaca_live_trading_base_url,
        ),
        "ALPACA_DATA_FEED": existing_raw.get(
            "ALPACA_DATA_FEED",
            settings.alpaca_data_feed,
        ),
        "SEC_EDGAR_USER_AGENT": existing_raw.get(
            "SEC_EDGAR_USER_AGENT",
            settings.sec_edgar_user_agent or "",
        ),
        "SEC_EDGAR_SUBMISSIONS_BASE_URL": existing_raw.get(
            "SEC_EDGAR_SUBMISSIONS_BASE_URL",
            settings.sec_edgar_submissions_base_url,
        ),
        "SEC_EDGAR_TICKERS_URL": existing_raw.get(
            "SEC_EDGAR_TICKERS_URL",
            settings.sec_edgar_tickers_url,
        ),
        "GUIDELINE_MEMORY_PATH": existing_raw.get(
            "GUIDELINE_MEMORY_PATH",
            settings.guideline_memory_path,
        ),
        "DATABASE_URL": existing_raw.get("DATABASE_URL", settings.database_url),
        "SCHEDULER_DEFAULT_TIMEZONE": existing_raw.get(
            "SCHEDULER_DEFAULT_TIMEZONE",
            settings.scheduler_default_timezone,
        ),
        "SCHEDULER_DEFAULT_POLL_EVERY_SECONDS": existing_raw.get(
            "SCHEDULER_DEFAULT_POLL_EVERY_SECONDS",
            str(settings.scheduler_default_poll_every_seconds),
        ),
        "SCHEDULER_WORKER_ID": existing_raw.get(
            "SCHEDULER_WORKER_ID",
            settings.scheduler_worker_id or "",
        ),
        "SCHEDULER_LEASE_SECONDS": existing_raw.get(
            "SCHEDULER_LEASE_SECONDS",
            str(settings.scheduler_lease_seconds),
        ),
        "SCHEDULER_STALE_RUN_AFTER_SECONDS": existing_raw.get(
            "SCHEDULER_STALE_RUN_AFTER_SECONDS",
            str(settings.scheduler_stale_run_after_seconds),
        ),
        "SCHEDULER_MAX_LLM_RUNS_PER_PASS": existing_raw.get(
            "SCHEDULER_MAX_LLM_RUNS_PER_PASS",
            str(settings.scheduler_max_llm_runs_per_pass),
        ),
        "SCHEDULER_EMBEDDED_WORKER_ENABLED": existing_raw.get(
            "SCHEDULER_EMBEDDED_WORKER_ENABLED",
            _bool_to_env(settings.scheduler_embedded_worker_enabled),
        ),
        "SCHEDULER_EMBEDDED_WORKER_POLL_EVERY_SECONDS": existing_raw.get(
            "SCHEDULER_EMBEDDED_WORKER_POLL_EVERY_SECONDS",
            str(settings.scheduler_embedded_worker_poll_every_seconds),
        ),
        "SCHEDULER_EMBEDDED_WORKER_LIMIT": existing_raw.get(
            "SCHEDULER_EMBEDDED_WORKER_LIMIT",
            str(settings.scheduler_embedded_worker_limit),
        ),
        "ALPACA_NEWS_STREAM_SUPERVISOR_ENABLED": existing_raw.get(
            "ALPACA_NEWS_STREAM_SUPERVISOR_ENABLED",
            _bool_to_env(settings.alpaca_news_stream_supervisor_enabled),
        ),
        "ALPACA_NEWS_STREAM_SUPERVISOR_POLL_SECONDS": existing_raw.get(
            "ALPACA_NEWS_STREAM_SUPERVISOR_POLL_SECONDS",
            str(settings.alpaca_news_stream_supervisor_poll_seconds),
        ),
        "ALPACA_NEWS_STREAM_LEASE_SECONDS": existing_raw.get(
            "ALPACA_NEWS_STREAM_LEASE_SECONDS",
            str(settings.alpaca_news_stream_lease_seconds),
        ),
        "ALPACA_NEWS_JUDGE_MAX_TOOL_CALLS": existing_raw.get(
            "ALPACA_NEWS_JUDGE_MAX_TOOL_CALLS",
            str(settings.alpaca_news_judge_max_tool_calls),
        ),
        "SEARXNG_BASE_URL": existing_raw.get(
            "SEARXNG_BASE_URL",
            settings.searxng_base_url or "",
        ),
        "APP_LOG_LEVEL": existing_raw.get(
            "APP_LOG_LEVEL",
            settings.app_log_level,
        ),
        "APP_LOG_FILE_PATH": existing_raw.get(
            "APP_LOG_FILE_PATH",
            settings.app_log_file_path,
        ),
        "APP_LOG_FORMAT": existing_raw.get(
            "APP_LOG_FORMAT",
            settings.app_log_format,
        ),
        "APP_LOG_RETENTION_DAYS": existing_raw.get(
            "APP_LOG_RETENTION_DAYS",
            str(settings.app_log_retention_days),
        ),
        "APP_LOG_THIRD_PARTY_LEVEL": existing_raw.get(
            "APP_LOG_THIRD_PARTY_LEVEL",
            settings.app_log_third_party_level,
        ),
        "LOG_DIAGNOSTIC_AGENT_ENABLED": existing_raw.get(
            "LOG_DIAGNOSTIC_AGENT_ENABLED",
            _bool_to_env(settings.log_diagnostic_agent_enabled),
        ),
        "LOG_DIAGNOSTIC_MAX_TOOL_CALLS": existing_raw.get(
            "LOG_DIAGNOSTIC_MAX_TOOL_CALLS",
            str(settings.log_diagnostic_max_tool_calls),
        ),
        "LOG_DIAGNOSTIC_MAX_RECORDS": existing_raw.get(
            "LOG_DIAGNOSTIC_MAX_RECORDS",
            str(settings.log_diagnostic_max_records),
        ),
        "LOG_DIAGNOSTIC_MAX_BYTES": existing_raw.get(
            "LOG_DIAGNOSTIC_MAX_BYTES",
            str(settings.log_diagnostic_max_bytes),
        ),
    }
    for legacy_key in (
        "T212_API_KEY",
        "T212_API_SECRET",
        "ALPACA_API_KEY",
        "ALPACA_API_SECRET",
    ):
        if legacy_key in existing_raw:
            values[legacy_key] = existing_raw.get(legacy_key, "")
    return values


def apply_configuration_wizard(
    io_runtime: TerminalIO,
    updates: dict[str, str],
    *,
    existing_raw: Mapping[str, str] | None = None,
) -> None:
    existing = existing_raw or {}

    _write_step_intro(
        io_runtime,
        "LLM configuration",
        "Choose the main reasoning provider and its credentials. "
        "If you use Azure OpenAI, the chat model fields below are deployment names.",
    )
    if _should_update_section(io_runtime, existing, LLM_SECTION_KEYS):
        llm_provider = io_runtime.choose(
            "LLM provider",
            options=LLM_PROVIDER_OPTIONS,
            default=_safe_choice(
                updates["LLM_PROVIDER"],
                {"openai", "azure_openai", "none"},
                "none",
            ),
        )
        updates["LLM_PROVIDER"] = llm_provider
        if llm_provider == "openai":
            updates["AZURE_OPENAI_ENABLED"] = "false"
            updates["OPENAI_API_KEY"] = io_runtime.prompt(
                "OPENAI_API_KEY",
                default=updates["OPENAI_API_KEY"],
            )
            updates["OPENAI_CHAT_MODEL_DEFAULT"] = _prompt_openai_model(
                io_runtime,
                "OpenAI chat model for default/baseline tasks",
                options=OPENAI_DEFAULT_MODEL_OPTIONS,
                default=updates["OPENAI_CHAT_MODEL_DEFAULT"] or "gpt-4o-mini",
            )
            updates["GENAI_CONTEXT_TOKENS_DEFAULT"] = _prompt_model_context_limit(
                io_runtime,
                model=updates["OPENAI_CHAT_MODEL_DEFAULT"],
                existing=updates["GENAI_CONTEXT_TOKENS_DEFAULT"],
                label="default/baseline model",
            )
            if io_runtime.confirm(
                "Configure a dedicated smart model for delicate/critical tasks? Recommended.",
                default=bool(updates["OPENAI_CHAT_MODEL_SMART"]),
            ):
                updates["OPENAI_CHAT_MODEL_SMART"] = _prompt_openai_model(
                    io_runtime,
                    "OpenAI chat model for smart/critical tasks",
                    options=OPENAI_SMART_MODEL_OPTIONS,
                    default=updates["OPENAI_CHAT_MODEL_SMART"] or "gpt-4.1",
                )
                updates["GENAI_CONTEXT_TOKENS_SMART"] = _prompt_model_context_limit(
                    io_runtime,
                    model=updates["OPENAI_CHAT_MODEL_SMART"],
                    existing=updates["GENAI_CONTEXT_TOKENS_SMART"],
                    label="smart/critical model",
                )
            else:
                _clear_env_keys(
                    updates,
                    "OPENAI_CHAT_MODEL_SMART",
                    "GENAI_CONTEXT_TOKENS_SMART",
                )
            if io_runtime.confirm(
                "Configure a dedicated reasoning model for deeper reasoning tasks? Recommended.",
                default=bool(updates["OPENAI_CHAT_MODEL_REASONING"]),
            ):
                updates["OPENAI_CHAT_MODEL_REASONING"] = _prompt_openai_model(
                    io_runtime,
                    "OpenAI chat model for reasoning tasks",
                    options=OPENAI_REASONING_MODEL_OPTIONS,
                    default=updates["OPENAI_CHAT_MODEL_REASONING"] or "o4-mini",
                )
                updates["GENAI_CONTEXT_TOKENS_REASONING"] = _prompt_model_context_limit(
                    io_runtime,
                    model=updates["OPENAI_CHAT_MODEL_REASONING"],
                    existing=updates["GENAI_CONTEXT_TOKENS_REASONING"],
                    label="reasoning model",
                )
            else:
                _clear_env_keys(
                    updates,
                    "OPENAI_CHAT_MODEL_REASONING",
                    "GENAI_CONTEXT_TOKENS_REASONING",
                )
            updates["OPENAI_EMBED_MODEL"] = io_runtime.prompt(
                "OpenAI embedding model",
                default=updates["OPENAI_EMBED_MODEL"],
            )
            updates["OPENAI_EMBED_DIMENSIONS"] = io_runtime.prompt(
                "OPENAI_EMBED_DIMENSIONS (optional)",
                default=updates["OPENAI_EMBED_DIMENSIONS"],
            )
        elif llm_provider == "azure_openai":
            updates["AZURE_OPENAI_ENABLED"] = "true"
            updates["AZURE_OPENAI_ENDPOINT"] = io_runtime.prompt(
                "AZURE_OPENAI_ENDPOINT",
                default=updates["AZURE_OPENAI_ENDPOINT"],
            )
            updates["AZURE_OPENAI_API_KEY"] = io_runtime.prompt(
                "AZURE_OPENAI_API_KEY",
                default=updates["AZURE_OPENAI_API_KEY"],
            )
            updates["AZURE_OPENAI_API_VERSION"] = io_runtime.prompt(
                "AZURE_OPENAI_API_VERSION",
                default=updates["AZURE_OPENAI_API_VERSION"],
            )
            azure_existing_models = (
                str(existing.get("LLM_PROVIDER", "")).strip().lower() == "azure_openai"
                or bool(str(existing.get("AZURE_OPENAI_ENDPOINT", "")).strip())
                or bool(str(existing.get("AZURE_OPENAI_API_KEY", "")).strip())
            )
            updates["OPENAI_CHAT_MODEL_DEFAULT"] = _prompt_required(
                io_runtime,
                "Azure chat deployment for default/baseline tasks",
                default=(
                    updates["OPENAI_CHAT_MODEL_DEFAULT"] if azure_existing_models else ""
                ),
            )
            updates["GENAI_CONTEXT_TOKENS_DEFAULT"] = _prompt_model_context_limit(
                io_runtime,
                model=updates["OPENAI_CHAT_MODEL_DEFAULT"],
                existing=updates["GENAI_CONTEXT_TOKENS_DEFAULT"],
                label="default/baseline deployment",
            )
            if io_runtime.confirm(
                "Configure a dedicated Azure deployment for smart/delicate tasks? Recommended.",
                default=bool(updates["OPENAI_CHAT_MODEL_SMART"]) and azure_existing_models,
            ):
                updates["OPENAI_CHAT_MODEL_SMART"] = io_runtime.prompt(
                    "Azure chat deployment for smart/critical tasks",
                    default=updates["OPENAI_CHAT_MODEL_SMART"],
                )
                updates["GENAI_CONTEXT_TOKENS_SMART"] = _prompt_model_context_limit(
                    io_runtime,
                    model=updates["OPENAI_CHAT_MODEL_SMART"],
                    existing=updates["GENAI_CONTEXT_TOKENS_SMART"],
                    label="smart/critical deployment",
                )
            else:
                _clear_env_keys(
                    updates,
                    "OPENAI_CHAT_MODEL_SMART",
                    "GENAI_CONTEXT_TOKENS_SMART",
                )
            if io_runtime.confirm(
                "Configure a dedicated Azure deployment for reasoning tasks? Recommended.",
                default=bool(updates["OPENAI_CHAT_MODEL_REASONING"]) and azure_existing_models,
            ):
                updates["OPENAI_CHAT_MODEL_REASONING"] = io_runtime.prompt(
                    "Azure chat deployment for reasoning tasks",
                    default=updates["OPENAI_CHAT_MODEL_REASONING"],
                )
                updates["GENAI_CONTEXT_TOKENS_REASONING"] = _prompt_model_context_limit(
                    io_runtime,
                    model=updates["OPENAI_CHAT_MODEL_REASONING"],
                    existing=updates["GENAI_CONTEXT_TOKENS_REASONING"],
                    label="reasoning deployment",
                )
            else:
                _clear_env_keys(
                    updates,
                    "OPENAI_CHAT_MODEL_REASONING",
                    "GENAI_CONTEXT_TOKENS_REASONING",
                )
            updates["AZURE_OPENAI_EMBED_DEPLOYMENT"] = io_runtime.prompt(
                "Azure embedding deployment (optional)",
                default=updates["AZURE_OPENAI_EMBED_DEPLOYMENT"],
            )
        else:
            updates["AZURE_OPENAI_ENABLED"] = "false"

    _write_step_intro(
        io_runtime,
        "Observability",
        "LangSmith tracing is optional. Enable it if you want execution traces, "
        "provider-level runs, and tool traces while testing or operating the app.",
    )
    if _should_update_section(io_runtime, existing, OBSERVABILITY_SECTION_KEYS):
        tracing_enabled = io_runtime.confirm(
            "Enable LangSmith tracing?",
            default=_env_truthy(updates["LANGSMITH_TRACING"]),
        )
        updates["LANGSMITH_TRACING"] = _bool_to_env(tracing_enabled)
        if tracing_enabled:
            updates["LANGSMITH_ENDPOINT"] = io_runtime.prompt(
                "LANGSMITH_ENDPOINT",
                default=updates["LANGSMITH_ENDPOINT"],
            )
            updates["LANGSMITH_API_KEY"] = io_runtime.prompt(
                "LANGSMITH_API_KEY",
                default=updates["LANGSMITH_API_KEY"],
            )
            updates["LANGSMITH_PROJECT"] = io_runtime.prompt(
                "LANGSMITH_PROJECT",
                default=updates["LANGSMITH_PROJECT"],
            )

    _write_step_intro(
        io_runtime,
        "Broker configuration",
        "Pick the broker used for account-authoritative reads and order execution.",
    )
    if _should_update_section(io_runtime, existing, BROKER_SECTION_KEYS):
        broker_provider = io_runtime.choose(
            "Broker provider",
            options=BROKER_PROVIDER_OPTIONS,
            default=_safe_choice(
                updates["BROKER_PROVIDER"],
                {"trading212", "alpaca", "none"},
                "none",
            ),
        )
        updates["BROKER_PROVIDER"] = broker_provider
        if broker_provider == "trading212":
            updates["T212_ENVIRONMENT"] = io_runtime.choose(
                "Trading 212 environment",
                options=ENVIRONMENT_OPTIONS,
                default=_safe_choice(updates["T212_ENVIRONMENT"], {"demo", "live"}, "demo"),
            )
            _prompt_trading212_credentials(io_runtime, updates)
            if updates["T212_ENVIRONMENT"] == "live":
                allow_live = io_runtime.confirm(
                    "Allow live order execution when running in live environment?",
                    default=_env_truthy(updates["T212_LIVE_TRADING_ENABLED"]),
                )
                updates["T212_LIVE_TRADING_ENABLED"] = _bool_to_env(allow_live)
            else:
                updates["T212_LIVE_TRADING_ENABLED"] = "false"
        elif broker_provider == "alpaca":
            updates["ALPACA_ENVIRONMENT"] = io_runtime.choose(
                "Alpaca environment",
                options=ALPACA_ENVIRONMENT_OPTIONS,
                default=_safe_choice(updates["ALPACA_ENVIRONMENT"], {"paper", "live"}, "paper"),
            )
            _prompt_alpaca_credentials(io_runtime, updates)

    _write_step_intro(
        io_runtime,
        "Telegram configuration",
        "Set the bot token and the allowed chat ids if you want Telegram access now.",
    )
    if _should_update_section(io_runtime, existing, TELEGRAM_SECTION_KEYS):
        if io_runtime.confirm(
            "Configure Telegram bot now?",
            default=bool(updates["TELEGRAM_BOT_TOKEN"] or updates["TELEGRAM_ALLOWED_CHAT_ID"]),
        ):
            updates["TELEGRAM_BOT_TOKEN"] = io_runtime.prompt(
                "TELEGRAM_BOT_TOKEN",
                default=updates["TELEGRAM_BOT_TOKEN"],
            )
            updates["TELEGRAM_ALLOWED_CHAT_ID"] = io_runtime.prompt(
                "TELEGRAM_ALLOWED_CHAT_ID",
                default=updates["TELEGRAM_ALLOWED_CHAT_ID"],
            )
            updates["TELEGRAM_ALLOWED_USER_ID"] = io_runtime.prompt(
                "TELEGRAM_ALLOWED_USER_ID (optional)",
                default=updates["TELEGRAM_ALLOWED_USER_ID"],
            )

    broker_provider = updates["BROKER_PROVIDER"]
    _write_step_intro(
        io_runtime,
        "Market data configuration",
        "Choose the market-data source used for quotes, bars, and chart context. "
        "Yahoo is the default baseline; Alpaca is optional if you prefer it.",
    )
    if _should_update_section(io_runtime, existing, MARKET_DATA_SECTION_KEYS):
        market_data_provider: str
        if broker_provider == "alpaca" and updates["MARKET_DATA_PROVIDER"] != "alpaca":
            reuse_alpaca = io_runtime.confirm(
                "Reuse Alpaca for market data too?",
                default=True,
            )
            if reuse_alpaca:
                market_data_provider = "alpaca"
            else:
                market_data_provider = io_runtime.choose(
                    "Market data provider",
                    options=MARKET_DATA_PROVIDER_OPTIONS,
                    default=_safe_choice(
                        updates["MARKET_DATA_PROVIDER"],
                        {"yahoo", "alpaca", "none"},
                        "yahoo",
                    ),
                )
        else:
            market_data_provider = io_runtime.choose(
                "Market data provider",
                options=MARKET_DATA_PROVIDER_OPTIONS,
                default=_safe_choice(
                    updates["MARKET_DATA_PROVIDER"],
                    {"yahoo", "alpaca", "none"},
                    "yahoo",
                ),
            )
        updates["MARKET_DATA_PROVIDER"] = market_data_provider
        updates["YAHOO_ENABLED"] = _bool_to_env(market_data_provider == "yahoo")
        if market_data_provider == "alpaca" and broker_provider != "alpaca":
            updates["ALPACA_ENVIRONMENT"] = io_runtime.choose(
                "Alpaca environment",
                options=ALPACA_ENVIRONMENT_OPTIONS,
                default=_safe_choice(updates["ALPACA_ENVIRONMENT"], {"paper", "live"}, "paper"),
            )
            _prompt_alpaca_credentials(io_runtime, updates)

    _write_step_intro(
        io_runtime,
        "Market intelligence",
        "Optional active-movers and intelligence enrichment. Skip this if you only "
        "need the baseline market-data provider.",
    )
    if _should_update_section(io_runtime, existing, ALPHA_VANTAGE_SECTION_KEYS):
        alpha_enabled = io_runtime.confirm(
            "Enable Alpha Vantage?",
            default=_env_truthy(updates["ALPHA_VANTAGE_ENABLED"]),
        )
        updates["MARKET_INTELLIGENCE_PROVIDER"] = (
            "alpha_vantage" if alpha_enabled else "none"
        )
        updates["ALPHA_VANTAGE_ENABLED"] = _bool_to_env(alpha_enabled)
        if alpha_enabled:
            updates["ALPHA_VANTAGE_API_KEY"] = io_runtime.prompt(
                "ALPHA_VANTAGE_API_KEY",
                default=updates["ALPHA_VANTAGE_API_KEY"],
            )

    _write_step_intro(
        io_runtime,
        "Disclosure intelligence",
        "Optional SEC EDGAR context for official filing, insider, and stake activity.",
    )
    if _should_update_section(io_runtime, existing, DISCLOSURE_SECTION_KEYS):
        disclosure_enabled = io_runtime.confirm(
            "Enable SEC EDGAR filing intelligence?",
            default=updates["DISCLOSURE_PROVIDER"].strip().lower() == "sec_edgar",
        )
        updates["DISCLOSURE_PROVIDER"] = "sec_edgar" if disclosure_enabled else "none"
        if disclosure_enabled:
            updates["SEC_EDGAR_USER_AGENT"] = io_runtime.prompt(
                "SEC_EDGAR_USER_AGENT (optional)",
                default=updates["SEC_EDGAR_USER_AGENT"],
            )

    _write_step_intro(
        io_runtime,
        "Search integration",
        "SearXNG is expected to be compose-managed, so this wizard does not prompt for it. "
        "Keep the current search settings as they are, or edit SEARCH_PROVIDER and "
        "SEARXNG_BASE_URL later.",
    )

    _write_step_intro(
        io_runtime,
        "Local storage",
        "Optionally override the default SQLite database path and guideline memory file path.",
    )
    if _should_update_section(io_runtime, existing, STORAGE_SECTION_KEYS):
        if io_runtime.confirm(
            "Customize storage paths?",
            default=False,
        ):
            updates["APP_LOG_LEVEL"] = io_runtime.prompt(
                "APP_LOG_LEVEL",
                default=updates["APP_LOG_LEVEL"],
            )
            updates["APP_LOG_FILE_PATH"] = io_runtime.prompt(
                "APP_LOG_FILE_PATH",
                default=updates["APP_LOG_FILE_PATH"],
            )
            updates["APP_LOG_FORMAT"] = io_runtime.prompt(
                "APP_LOG_FORMAT",
                default=updates["APP_LOG_FORMAT"],
            )
            updates["APP_LOG_RETENTION_DAYS"] = io_runtime.prompt(
                "APP_LOG_RETENTION_DAYS",
                default=updates["APP_LOG_RETENTION_DAYS"],
            )
            updates["APP_LOG_THIRD_PARTY_LEVEL"] = io_runtime.prompt(
                "APP_LOG_THIRD_PARTY_LEVEL",
                default=updates["APP_LOG_THIRD_PARTY_LEVEL"],
            )
            updates["DATABASE_URL"] = io_runtime.prompt(
                "DATABASE_URL",
                default=updates["DATABASE_URL"],
            )
            updates["GUIDELINE_MEMORY_PATH"] = io_runtime.prompt(
                "GUIDELINE_MEMORY_PATH",
                default=updates["GUIDELINE_MEMORY_PATH"],
            )

    _write_step_intro(
        io_runtime,
        "Scheduler defaults",
        "Set the user's default timezone for local schedule requests. Scheduler "
        "workers store and execute times in UTC after conversion.",
    )
    if _should_update_section(io_runtime, existing, SCHEDULER_SECTION_KEYS):
        if io_runtime.confirm(
            "Customize scheduler defaults?",
            default=False,
        ):
            updates["SCHEDULER_DEFAULT_TIMEZONE"] = _prompt_iana_timezone(
                io_runtime,
                "SCHEDULER_DEFAULT_TIMEZONE",
                default=updates["SCHEDULER_DEFAULT_TIMEZONE"],
            )
            updates["SCHEDULER_DEFAULT_POLL_EVERY_SECONDS"] = io_runtime.prompt(
                "SCHEDULER_DEFAULT_POLL_EVERY_SECONDS",
                default=updates["SCHEDULER_DEFAULT_POLL_EVERY_SECONDS"],
            )
            updates["SCHEDULER_WORKER_ID"] = io_runtime.prompt(
                "SCHEDULER_WORKER_ID",
                default=updates["SCHEDULER_WORKER_ID"],
            )
            updates["SCHEDULER_LEASE_SECONDS"] = io_runtime.prompt(
                "SCHEDULER_LEASE_SECONDS",
                default=updates["SCHEDULER_LEASE_SECONDS"],
            )
            updates["SCHEDULER_STALE_RUN_AFTER_SECONDS"] = io_runtime.prompt(
                "SCHEDULER_STALE_RUN_AFTER_SECONDS",
                default=updates["SCHEDULER_STALE_RUN_AFTER_SECONDS"],
            )
            updates["SCHEDULER_MAX_LLM_RUNS_PER_PASS"] = io_runtime.prompt(
                "SCHEDULER_MAX_LLM_RUNS_PER_PASS",
                default=updates["SCHEDULER_MAX_LLM_RUNS_PER_PASS"],
            )
            updates["SCHEDULER_EMBEDDED_WORKER_ENABLED"] = _bool_to_env(
                io_runtime.confirm(
                    "Run the scheduler worker inside the Telegram bot process?",
                    default=updates["SCHEDULER_EMBEDDED_WORKER_ENABLED"].lower()
                    in {"1", "true", "yes", "y", "on"},
                )
            )
            updates["SCHEDULER_EMBEDDED_WORKER_POLL_EVERY_SECONDS"] = io_runtime.prompt(
                "SCHEDULER_EMBEDDED_WORKER_POLL_EVERY_SECONDS",
                default=updates["SCHEDULER_EMBEDDED_WORKER_POLL_EVERY_SECONDS"],
            )
            updates["SCHEDULER_EMBEDDED_WORKER_LIMIT"] = io_runtime.prompt(
                "SCHEDULER_EMBEDDED_WORKER_LIMIT",
                default=updates["SCHEDULER_EMBEDDED_WORKER_LIMIT"],
            )
            updates["ALPACA_NEWS_STREAM_SUPERVISOR_ENABLED"] = _bool_to_env(
                io_runtime.confirm(
                    "Run Alpaca news stream monitors inside the Telegram bot process?",
                    default=updates["ALPACA_NEWS_STREAM_SUPERVISOR_ENABLED"].lower()
                    in {"1", "true", "yes", "y", "on"},
                )
            )
            updates["ALPACA_NEWS_STREAM_SUPERVISOR_POLL_SECONDS"] = io_runtime.prompt(
                "ALPACA_NEWS_STREAM_SUPERVISOR_POLL_SECONDS",
                default=updates["ALPACA_NEWS_STREAM_SUPERVISOR_POLL_SECONDS"],
            )
            updates["ALPACA_NEWS_STREAM_LEASE_SECONDS"] = io_runtime.prompt(
                "ALPACA_NEWS_STREAM_LEASE_SECONDS",
                default=updates["ALPACA_NEWS_STREAM_LEASE_SECONDS"],
            )
            updates["ALPACA_NEWS_JUDGE_MAX_TOOL_CALLS"] = io_runtime.prompt(
                "ALPACA_NEWS_JUDGE_MAX_TOOL_CALLS",
                default=updates["ALPACA_NEWS_JUDGE_MAX_TOOL_CALLS"],
            )


def _prompt_trading212_credentials(
    io_runtime: TerminalIO,
    updates: dict[str, str],
) -> None:
    environment = _safe_choice(updates["T212_ENVIRONMENT"], {"demo", "live"}, "demo")
    if environment == "live":
        key_name = "T212_LIVE_API_KEY"
        secret_name = "T212_LIVE_API_SECRET"
        label = "live"
    else:
        key_name = "T212_DEMO_API_KEY"
        secret_name = "T212_DEMO_API_SECRET"
        label = "demo"
    io_runtime.write(
        f"Configure Trading 212 {label} credentials. "
        "Credentials for the other environment are kept unchanged if already present."
    )
    updates[key_name] = io_runtime.prompt(
        key_name,
        default=updates[key_name],
    )
    updates[secret_name] = io_runtime.prompt(
        secret_name,
        default=updates[secret_name],
    )


def _prompt_alpaca_credentials(
    io_runtime: TerminalIO,
    updates: dict[str, str],
) -> None:
    environment = _safe_choice(updates["ALPACA_ENVIRONMENT"], {"paper", "live"}, "paper")
    if environment == "live":
        key_name = "ALPACA_LIVE_API_KEY"
        secret_name = "ALPACA_LIVE_API_SECRET"
        label = "live"
    else:
        key_name = "ALPACA_PAPER_API_KEY"
        secret_name = "ALPACA_PAPER_API_SECRET"
        label = "paper"
    io_runtime.write(
        f"Configure Alpaca {label} credentials. "
        "Credentials for the other environment are kept unchanged if already present."
    )
    updates[key_name] = io_runtime.prompt(
        key_name,
        default=updates[key_name],
    )
    updates[secret_name] = io_runtime.prompt(
        secret_name,
        default=updates[secret_name],
    )


def _drop_new_empty_inactive_broker_credentials(
    updates: dict[str, str],
    *,
    existing_raw: Mapping[str, str],
) -> None:
    active_keys = set(_active_broker_credential_keys(updates))
    for key in _BROKER_ENVIRONMENT_CREDENTIAL_KEYS:
        if key in active_keys:
            continue
        if str(existing_raw.get(key, "")).strip():
            continue
        if not str(updates.get(key, "")).strip():
            updates.pop(key, None)


def _active_broker_credential_keys(updates: Mapping[str, str]) -> tuple[str, ...]:
    keys: list[str] = []
    broker_provider = str(updates.get("BROKER_PROVIDER", "")).strip().lower()
    market_data_provider = str(updates.get("MARKET_DATA_PROVIDER", "")).strip().lower()
    if broker_provider == "trading212":
        if (
            _safe_choice(updates.get("T212_ENVIRONMENT", "demo"), {"demo", "live"}, "demo")
            == "live"
        ):
            keys.extend(("T212_LIVE_API_KEY", "T212_LIVE_API_SECRET"))
        else:
            keys.extend(("T212_DEMO_API_KEY", "T212_DEMO_API_SECRET"))
    if broker_provider == "alpaca" or market_data_provider == "alpaca":
        if (
            _safe_choice(updates.get("ALPACA_ENVIRONMENT", "paper"), {"paper", "live"}, "paper")
            == "live"
        ):
            keys.extend(("ALPACA_LIVE_API_KEY", "ALPACA_LIVE_API_SECRET"))
        else:
            keys.extend(("ALPACA_PAPER_API_KEY", "ALPACA_PAPER_API_SECRET"))
    return tuple(keys)

_BROKER_ENVIRONMENT_CREDENTIAL_KEYS = (
    "T212_DEMO_API_KEY",
    "T212_DEMO_API_SECRET",
    "T212_LIVE_API_KEY",
    "T212_LIVE_API_SECRET",
    "ALPACA_PAPER_API_KEY",
    "ALPACA_PAPER_API_SECRET",
    "ALPACA_LIVE_API_KEY",
    "ALPACA_LIVE_API_SECRET",
)


def _write_step_intro(
    io_runtime: TerminalIO,
    title: str,
    description: str,
) -> None:
    io_runtime.write("")
    io_runtime.write(render_step_intro(title, description))


def _section_has_existing_values(
    existing_raw: Mapping[str, str],
    keys: tuple[str, ...],
) -> bool:
    return any(key in existing_raw for key in keys)


def _should_update_section(
    io_runtime: TerminalIO,
    existing_raw: Mapping[str, str],
    keys: tuple[str, ...],
) -> bool:
    if not _section_has_existing_values(existing_raw, keys):
        return True
    return io_runtime.confirm("Update this section now?", default=False)


def _clear_env_keys(updates: dict[str, str], *keys: str) -> None:
    for key in keys:
        updates[key] = ""


def _prompt_required(
    io_runtime: TerminalIO,
    label: str,
    *,
    default: str = "",
) -> str:
    while True:
        value = io_runtime.prompt(label, default=default)
        if str(value).strip():
            return value.strip()
        io_runtime.write("This value is required.")


def _prompt_iana_timezone(
    io_runtime: TerminalIO,
    label: str,
    *,
    default: str = "UTC",
) -> str:
    while True:
        value = io_runtime.prompt(label, default=default).strip() or "UTC"
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            io_runtime.write(
                "Enter a valid IANA timezone such as Europe/Rome, America/New_York, or UTC."
            )
            continue
        return value


def _prompt_openai_model(
    io_runtime: TerminalIO,
    label: str,
    *,
    options: tuple[tuple[str, str], ...],
    default: str,
) -> str:
    normalized_default = str(default or "").strip()
    option_values = {value for value, _ in options}
    prompt_options = (*options, ("custom", "Other known OpenAI model id"))
    if normalized_default in option_values:
        selected_default = normalized_default
        custom_default = ""
    elif _MODEL_CONTEXT_REGISTRY.lookup(normalized_default) is not None:
        selected_default = "custom"
        custom_default = normalized_default
    else:
        selected_default = options[0][0]
        custom_default = ""

    selected = io_runtime.choose(
        label,
        options=prompt_options,
        default=selected_default,
    )
    if selected != "custom":
        return selected

    while True:
        model = io_runtime.prompt(
            "OpenAI model id",
            default=custom_default,
        ).strip()
        if _MODEL_CONTEXT_REGISTRY.lookup(model) is not None:
            return model
        io_runtime.write(
            "Model is not in the internal OpenAI context registry. "
            "Choose a listed model or update the registry first."
        )


def _prompt_model_context_limit(
    io_runtime: TerminalIO,
    *,
    model: str,
    existing: str,
    label: str,
) -> str:
    known_limit = _MODEL_CONTEXT_REGISTRY.lookup(model)
    if known_limit is not None:
        return str(known_limit)

    existing_limit = parse_context_token_value(existing)
    fallback = str(DEFAULT_CONTEXT_FALLBACK_TOKENS)
    options: list[tuple[str, str]] = []
    options.append((fallback, f"Safe default: {fallback} tokens"))
    options.append(("custom", f"Custom integer > {MIN_CONFIGURABLE_CONTEXT_TOKENS}"))

    if existing_limit is not None and str(existing_limit) in {value for value, _ in options}:
        default = str(existing_limit)
    elif existing_limit is not None:
        default = "custom"
    else:
        default = fallback

    selected = io_runtime.choose(
        f"Context token limit for {label}",
        options=tuple(options),
        default=default,
    )
    if selected != "custom":
        return selected

    while True:
        raw = io_runtime.prompt(
            f"Custom context token limit for {label}",
            default=str(existing_limit or ""),
        )
        parsed = parse_context_token_value(raw)
        if parsed is not None:
            return str(parsed)
        io_runtime.write(
            f"Enter an integer greater than {MIN_CONFIGURABLE_CONTEXT_TOKENS}."
        )


def update_env_file(path: Path, updates: Mapping[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = set(updates.keys())
    seen_managed: set[str] = set()
    rendered_lines: list[str] = []

    for line in existing_lines:
        key = _extract_env_key(line)
        if key is None or key not in updates:
            rendered_lines.append(line)
            continue
        if key in seen_managed:
            continue
        rendered_lines.append(_format_env_assignment(key, updates[key]))
        seen_managed.add(key)
        remaining.discard(key)

    for section_name, keys in MANAGED_ENV_SECTIONS:
        missing_keys = [key for key in keys if key in remaining]
        if not missing_keys:
            continue
        if rendered_lines and rendered_lines[-1].strip():
            rendered_lines.append("")
        rendered_lines.append(f"# {section_name}")
        for key in missing_keys:
            rendered_lines.append(_format_env_assignment(key, updates[key]))
            remaining.discard(key)

    path.write_text("\n".join(rendered_lines).rstrip() + "\n", encoding="utf-8")


def _extract_env_key(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped.removeprefix("export ").strip()
    if "=" not in stripped:
        return None
    key, _value = stripped.split("=", 1)
    key = key.strip()
    return key or None


def _format_env_assignment(key: str, value: str) -> str:
    return f"{key}={_format_env_value(value)}"


def _format_env_value(value: str) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    if any(char.isspace() for char in raw) or "#" in raw:
        escaped = raw.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return raw
