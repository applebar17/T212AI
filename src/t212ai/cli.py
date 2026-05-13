from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, TextIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .app.bootstrap import (
    ConfigAssessment,
    ProviderAssessment,
    assess_settings,
    ensure_runtime_directories,
    preflight_reconcile,
    preflight_run_bot,
    preflight_scheduler,
    run_provider_smoke_tests,
)
from .app.config import (
    DEFAULT_ENV_FILE_NAME,
    AppSettings,
    get_app_settings,
    load_env_file,
    parse_env_file,
)
from .app.logging import configure_logging
from .app.runtime import build_runtime
from .app.scheduler_worker import run_scheduler_once as run_runtime_scheduler_once
from .genai.context import (
    DEFAULT_CONTEXT_FALLBACK_TOKENS,
    MIN_CONFIGURABLE_CONTEXT_TOKENS,
    ModelContextRegistry,
    parse_context_token_value,
)


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
REDDIT_AUTH_OPTIONS = (
    ("refresh_token", "Refresh token"),
    ("username_password", "Username and password"),
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
        "OPENFIGI_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "REDDIT_CLIENT_SECRET",
        "REDDIT_PASSWORD",
        "REDDIT_REFRESH_TOKEN",
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
            "DISCLOSURE_PROVIDER",
            "COMMUNITY_PROVIDER",
            "SEARCH_PROVIDER",
            "YAHOO_ENABLED",
            "ALPHA_VANTAGE_ENABLED",
            "REDDIT_ENABLED",
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
        "Reddit Data API",
        (
            "REDDIT_CLIENT_ID",
            "REDDIT_CLIENT_SECRET",
            "REDDIT_USERNAME",
            "REDDIT_PASSWORD",
            "REDDIT_REFRESH_TOKEN",
            "REDDIT_USER_AGENT",
            "REDDIT_BASE_URL",
            "REDDIT_AUTH_URL",
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
        "Reference data",
        (
            "REFERENCE_DATA_PROVIDER",
            "OPENFIGI_API_KEY",
            "OPENFIGI_BASE_URL",
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

DISCLOSURE_SECTION_KEYS = (
    "DISCLOSURE_PROVIDER",
    "SEC_EDGAR_USER_AGENT",
)

REDDIT_SECTION_KEYS = (
    "COMMUNITY_PROVIDER",
    "REDDIT_ENABLED",
    "REDDIT_CLIENT_ID",
    "REDDIT_CLIENT_SECRET",
    "REDDIT_USERNAME",
    "REDDIT_PASSWORD",
    "REDDIT_REFRESH_TOKEN",
    "REDDIT_USER_AGENT",
)

SEARCH_SECTION_KEYS = (
    "SEARCH_PROVIDER",
    "SEARXNG_ENABLED",
    "SEARXNG_BASE_URL",
)

REFERENCE_DATA_SECTION_KEYS = (
    "REFERENCE_DATA_PROVIDER",
    "OPENFIGI_API_KEY",
    "OPENFIGI_BASE_URL",
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


@dataclass(slots=True)
class TerminalIO:
    input_fn: Callable[[str], str] = input
    output: TextIO | None = None

    def __post_init__(self) -> None:
        if self.output is None:
            self.output = sys.stdout

    def write(self, text: str = "") -> None:
        print(text, file=self.output)

    def prompt(self, label: str, *, default: str | None = None) -> str:
        suffix = f" [{default}]" if default not in {None, ""} else ""
        value = self.input_fn(f"{label}{suffix}: ").strip()
        if value:
            return value
        return default or ""

    def confirm(self, label: str, *, default: bool = True) -> bool:
        suffix = "Y/n" if default else "y/N"
        while True:
            raw = self.input_fn(f"{label} [{suffix}]: ").strip().lower()
            if not raw:
                return default
            if raw in {"y", "yes"}:
                return True
            if raw in {"n", "no"}:
                return False
            self.write("Please answer yes or no.")

    def choose(
        self,
        label: str,
        *,
        options: tuple[tuple[str, str], ...],
        default: str,
    ) -> str:
        self.write(label)
        index_by_value = {value: idx for idx, (value, _) in enumerate(options, start=1)}
        for index, (value, description) in enumerate(options, start=1):
            marker = " (default)" if value == default else ""
            self.write(f"  {index}. {description}{marker}")
        default_index = index_by_value.get(default, 1)
        while True:
            raw = self.prompt("Select option", default=str(default_index)).strip().lower()
            if raw.isdigit():
                selected_index = int(raw)
                if 1 <= selected_index <= len(options):
                    return options[selected_index - 1][0]
            for value, description in options:
                if raw in {value.lower(), description.lower()}:
                    return value
            self.write("Please choose one of the listed options.")


def build_parser(prog: str | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog or _default_prog_name(),
        description="brokerai bootstrap CLI for configuring and running the Telegram agent.",
    )
    subparsers = parser.add_subparsers(dest="command")

    configure_parser = subparsers.add_parser(
        "configure",
        help="Run the interactive configuration wizard.",
    )
    configure_parser.add_argument(
        "--env-file",
        default=DEFAULT_ENV_FILE_NAME,
        help="Path to the .env file to create or update.",
    )
    configure_parser.set_defaults(handler=command_configure)

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Inspect configuration, enabled providers, and run-bot readiness.",
    )
    doctor_parser.add_argument(
        "--env-file",
        default=None,
        help="Optional path to inspect instead of the active process environment.",
    )
    doctor_parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run optional live smoke probes for enabled providers.",
    )
    doctor_parser.set_defaults(handler=command_doctor)

    scheduler_parser = subparsers.add_parser(
        "scheduler",
        help="Inspect and maintain scheduled processes.",
    )
    scheduler_subparsers = scheduler_parser.add_subparsers(dest="scheduler_target")
    scheduler_status_parser = scheduler_subparsers.add_parser(
        "status",
        help="Show scheduler operational status.",
    )
    scheduler_status_parser.add_argument("--env-file", default=None)
    scheduler_status_parser.set_defaults(handler=command_scheduler_status)

    scheduler_list_parser = scheduler_subparsers.add_parser(
        "list",
        help="List scheduled processes.",
    )
    scheduler_list_parser.add_argument("--env-file", default=None)
    scheduler_list_parser.add_argument("--status", action="append", dest="statuses")
    scheduler_list_parser.add_argument("--kind", action="append", dest="kinds")
    scheduler_list_parser.add_argument("--limit", type=int, default=50)
    scheduler_list_parser.set_defaults(handler=command_scheduler_list)

    scheduler_show_parser = scheduler_subparsers.add_parser(
        "show",
        help="Show one scheduled process with recent runs/events.",
    )
    scheduler_show_parser.add_argument("process_id")
    scheduler_show_parser.add_argument("--env-file", default=None)
    scheduler_show_parser.add_argument("--runs", type=int, default=10)
    scheduler_show_parser.add_argument("--events", type=int, default=20)
    scheduler_show_parser.set_defaults(handler=command_scheduler_show)

    scheduler_recover_parser = scheduler_subparsers.add_parser(
        "recover-stale",
        help="Recover stale started scheduler runs.",
    )
    scheduler_recover_parser.add_argument("--env-file", default=None)
    scheduler_recover_parser.add_argument("--older-than", default="1h")
    scheduler_recover_parser.add_argument("--dry-run", action="store_true")
    scheduler_recover_parser.add_argument("--apply", action="store_true")
    scheduler_recover_parser.set_defaults(handler=command_scheduler_recover_stale)

    scheduler_cleanup_parser = scheduler_subparsers.add_parser(
        "cleanup",
        help="Delete archived scheduler records older than a cutoff.",
    )
    scheduler_cleanup_parser.add_argument("--env-file", default=None)
    scheduler_cleanup_parser.add_argument("--archived-before", default="30d")
    scheduler_cleanup_parser.add_argument("--dry-run", action="store_true")
    scheduler_cleanup_parser.add_argument("--apply", action="store_true")
    scheduler_cleanup_parser.set_defaults(handler=command_scheduler_cleanup)

    scheduler_export_parser = scheduler_subparsers.add_parser(
        "export",
        help="Export scheduler process definitions and optional audit rows as JSON.",
    )
    scheduler_export_parser.add_argument("--env-file", default=None)
    scheduler_export_parser.add_argument("--output", default=None)
    scheduler_export_parser.add_argument("--status", action="append", dest="statuses")
    scheduler_export_parser.add_argument("--kind", action="append", dest="kinds")
    scheduler_export_parser.add_argument("--include-runs", action="store_true")
    scheduler_export_parser.add_argument("--include-events", action="store_true")
    scheduler_export_parser.add_argument("--limit", type=int, default=500)
    scheduler_export_parser.set_defaults(handler=command_scheduler_export)

    run_parser = subparsers.add_parser(
        "run",
        help="Run operational entrypoints.",
    )
    run_subparsers = run_parser.add_subparsers(dest="run_target")
    run_bot_parser = run_subparsers.add_parser(
        "bot",
        help="Start the Telegram bot in polling mode.",
    )
    run_bot_parser.add_argument(
        "--env-file",
        default=None,
        help="Optional .env file to load before starting the bot.",
    )
    run_bot_parser.set_defaults(handler=command_run_bot)
    run_reconcile_parser = run_subparsers.add_parser(
        "reconcile-once",
        help="Run one broker reconciliation pass.",
    )
    run_reconcile_parser.add_argument(
        "--env-file",
        default=None,
        help="Optional .env file to load before running reconciliation.",
    )
    run_reconcile_parser.set_defaults(handler=command_run_reconcile_once)
    run_scheduler_once_parser = run_subparsers.add_parser(
        "scheduler-once",
        help="Run one scheduler worker pass.",
    )
    run_scheduler_once_parser.add_argument(
        "--env-file",
        default=None,
        help="Optional .env file to load before running the scheduler.",
    )
    run_scheduler_once_parser.add_argument("--limit", type=int, default=100)
    run_scheduler_once_parser.add_argument("--lease-seconds", type=int, default=None)
    run_scheduler_once_parser.add_argument("--stale-run-after", default=None)
    run_scheduler_once_parser.add_argument("--max-llm-runs-per-pass", type=int, default=None)
    run_scheduler_once_parser.set_defaults(handler=command_run_scheduler_once)

    run_scheduler_parser = run_subparsers.add_parser(
        "scheduler",
        help="Run the scheduler worker loop.",
    )
    run_scheduler_parser.add_argument(
        "--env-file",
        default=None,
        help="Optional .env file to load before running the scheduler.",
    )
    run_scheduler_parser.add_argument(
        "--poll-every",
        default="1m",
        help="Scheduler polling interval such as 30s, 1m, 15m, or 1h.",
    )
    run_scheduler_parser.add_argument("--limit", type=int, default=100)
    run_scheduler_parser.add_argument("--lease-seconds", type=int, default=None)
    run_scheduler_parser.add_argument("--stale-run-after", default=None)
    run_scheduler_parser.add_argument("--max-llm-runs-per-pass", type=int, default=None)
    run_scheduler_parser.set_defaults(handler=command_run_scheduler_worker)

    run_alpaca_news_stream_parser = run_subparsers.add_parser(
        "alpaca-news-stream",
        help="Capture Alpaca real-time news websocket events to a JSONL file.",
    )
    run_alpaca_news_stream_parser.add_argument(
        "--env-file",
        default=None,
        help="Optional .env file to load before connecting to Alpaca.",
    )
    run_alpaca_news_stream_parser.add_argument(
        "--symbols",
        action="append",
        default=None,
        help="Optional local symbol filter. Can be passed multiple times.",
    )
    run_alpaca_news_stream_parser.add_argument(
        "--output",
        default="data/alpaca_stream/news_stream.jsonl",
        help="JSONL output file path.",
    )
    run_alpaca_news_stream_parser.add_argument(
        "--max-events",
        type=int,
        default=None,
        help="Stop after writing this many matching news events.",
    )
    run_alpaca_news_stream_parser.add_argument(
        "--seconds",
        type=float,
        default=None,
        help="Stop after this many seconds if no max-events limit is reached.",
    )
    run_alpaca_news_stream_parser.add_argument(
        "--sandbox",
        action="store_true",
        help="Use Alpaca's sandbox stream host.",
    )
    run_alpaca_news_stream_parser.set_defaults(handler=command_run_alpaca_news_stream)

    run_worker_parser = run_subparsers.add_parser(
        "worker",
        help="Run the broker reconciliation worker loop.",
    )
    run_worker_parser.add_argument(
        "--env-file",
        default=None,
        help="Optional .env file to load before running the worker.",
    )
    run_worker_parser.add_argument(
        "--reconcile-every",
        default="1h",
        help="Reconciliation interval such as 5m, 15m, or 1h.",
    )
    run_worker_parser.set_defaults(handler=command_run_worker)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return int(handler(args))


def command_configure(args: argparse.Namespace) -> int:
    env_path = Path(args.env_file)
    existing_raw = parse_env_file(env_path) if env_path.exists() else {}
    io_runtime = TerminalIO()
    io_runtime.write("brokerai configuration wizard")
    io_runtime.write(f"Target env file: {env_path}")
    if existing_raw:
        io_runtime.write(
            "Existing configuration detected. Sections with current values can be "
            "skipped to keep them unchanged."
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


def command_doctor(args: argparse.Namespace) -> int:
    settings = load_settings_from_cli(env_file=args.env_file)
    _configure_app_logging(settings)
    assessment = assess_settings(settings)
    preflight = preflight_run_bot(assessment)
    smoke_results = run_provider_smoke_tests(settings, assessment) if args.smoke else None
    print(render_doctor_report(settings, assessment, preflight, smoke_results=smoke_results))
    return 0 if assessment.is_valid else 1


def command_scheduler_status(args: argparse.Namespace) -> int:
    runtime = _build_scheduler_runtime_for_command(args, "scheduler status")
    if runtime is None:
        return 1
    status = runtime.scheduled_process_service.scheduler_status()
    print(render_scheduler_status(status, runtime.settings))
    return 0


def command_scheduler_list(args: argparse.Namespace) -> int:
    runtime = _build_scheduler_runtime_for_command(args, "scheduler list")
    if runtime is None:
        return 1
    try:
        processes = runtime.scheduled_process_service.list_processes(
            statuses=args.statuses,
            kinds=args.kinds,
            limit=args.limit,
        )
    except Exception as exc:
        print(f"brokerai scheduler list failed: {exc}")
        return 1
    print(render_scheduler_process_list(processes))
    return 0


def command_scheduler_show(args: argparse.Namespace) -> int:
    runtime = _build_scheduler_runtime_for_command(args, "scheduler show")
    if runtime is None:
        return 1
    process = runtime.scheduled_process_service.get_process(args.process_id)
    if process is None:
        print(f"brokerai scheduler show failed: process {args.process_id} was not found.")
        return 1
    runs = runtime.scheduled_process_service.list_runs(process.process_id, limit=args.runs)
    events = runtime.scheduled_process_service.list_events(process.process_id, limit=args.events)
    print(render_scheduler_process_detail(process, runs, events))
    return 0


def command_scheduler_recover_stale(args: argparse.Namespace) -> int:
    runtime = _build_scheduler_runtime_for_command(args, "scheduler recover-stale")
    if runtime is None:
        return 1
    try:
        older_than_seconds = parse_duration_to_seconds(args.older_than)
        result = runtime.scheduled_process_service.recover_stale_runs(
            stale_after_seconds=older_than_seconds,
            dry_run=not bool(args.apply),
        )
    except Exception as exc:
        print(f"brokerai scheduler recover-stale failed: {exc}")
        return 1
    print(render_scheduler_maintenance_result("recover-stale", result))
    return 0


def command_scheduler_cleanup(args: argparse.Namespace) -> int:
    runtime = _build_scheduler_runtime_for_command(args, "scheduler cleanup")
    if runtime is None:
        return 1
    try:
        cutoff = _cutoff_from_duration_or_iso(args.archived_before)
        result = runtime.scheduled_process_service.delete_archived_before(
            cutoff,
            dry_run=not bool(args.apply),
        )
    except Exception as exc:
        print(f"brokerai scheduler cleanup failed: {exc}")
        return 1
    print(render_scheduler_maintenance_result("cleanup", result))
    return 0


def command_scheduler_export(args: argparse.Namespace) -> int:
    runtime = _build_scheduler_runtime_for_command(args, "scheduler export")
    if runtime is None:
        return 1
    try:
        payload = runtime.scheduled_process_service.export_processes(
            statuses=args.statuses,
            kinds=args.kinds,
            include_runs=bool(args.include_runs),
            include_events=bool(args.include_events),
            limit=args.limit,
        )
    except Exception as exc:
        print(f"brokerai scheduler export failed: {exc}")
        return 1
    rendered = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        print(f"Exported {payload['processCount']} scheduled process(es) to {args.output}.")
    else:
        print(rendered)
    return 0


def command_run_bot(args: argparse.Namespace) -> int:
    settings = load_settings_from_cli(env_file=args.env_file)
    _configure_app_logging(settings)
    logger = logging.getLogger(__name__)
    assessment = assess_settings(settings)
    preflight = preflight_run_bot(assessment)
    if not preflight.ok:
        print(render_run_bot_failure(preflight))
        return 1

    if args.env_file is not None:
        load_env_file(args.env_file, override=True)
    ensure_runtime_directories(settings)
    runtime = build_runtime(settings)
    logger.info(
        "Starting Telegram bot broker_provider=%s llm_provider=%s log_file=%s",
        settings.broker_provider,
        settings.llm_provider,
        settings.app_log_file_path,
    )

    try:
        from .telegram import TelegramBotService

        TelegramBotService.from_settings(settings, runtime=runtime).run_polling()
    except Exception as exc:  # pragma: no cover - startup safety net
        print(f"brokerai run bot failed: {exc}")
        return 1
    return 0


def command_run_reconcile_once(args: argparse.Namespace) -> int:
    settings = load_settings_from_cli(env_file=args.env_file)
    _configure_app_logging(settings)
    assessment = assess_settings(settings)
    preflight = preflight_reconcile(assessment, settings)
    if not preflight.ok:
        print(render_reconcile_failure(preflight))
        return 1
    if args.env_file is not None:
        load_env_file(args.env_file, override=True)
    ensure_runtime_directories(settings)
    runtime = build_runtime(settings)
    if runtime.reconciliation_service is None:
        print("brokerai run reconcile-once failed: reconciliation runtime is not available.")
        return 1
    try:
        result = run_reconcile_once(runtime)
    except Exception as exc:  # pragma: no cover - startup safety net
        print(f"brokerai run reconcile-once failed: {exc}")
        return 1
    print(result.render_text())
    return 0


def command_run_worker(args: argparse.Namespace) -> int:
    settings = load_settings_from_cli(env_file=args.env_file)
    _configure_app_logging(settings)
    assessment = assess_settings(settings)
    preflight = preflight_reconcile(assessment, settings)
    if not preflight.ok:
        print(render_reconcile_failure(preflight))
        return 1
    try:
        interval_seconds = parse_duration_to_seconds(args.reconcile_every)
    except ValueError as exc:
        print(f"brokerai run worker failed: {exc}")
        return 1
    if args.env_file is not None:
        load_env_file(args.env_file, override=True)
    ensure_runtime_directories(settings)
    runtime = build_runtime(settings)
    if runtime.reconciliation_service is None:
        print("brokerai run worker failed: reconciliation runtime is not available.")
        return 1
    try:
        return run_reconcile_worker(runtime, interval_seconds=interval_seconds)
    except KeyboardInterrupt:
        print("brokerai worker stopped.")
        return 0
    except Exception as exc:  # pragma: no cover - startup safety net
        print(f"brokerai run worker failed: {exc}")
        return 1


def command_run_scheduler_once(args: argparse.Namespace) -> int:
    settings = load_settings_from_cli(env_file=args.env_file)
    _configure_app_logging(settings)
    assessment = assess_settings(settings)
    preflight = preflight_scheduler(assessment, settings)
    if not preflight.ok:
        print(render_scheduler_failure(preflight))
        return 1
    if args.env_file is not None:
        load_env_file(args.env_file, override=True)
    ensure_runtime_directories(settings)
    runtime = build_runtime(settings)
    if runtime.scheduled_process_service is None:
        print("brokerai run scheduler-once failed: scheduler runtime is not available.")
        return 1
    try:
        result = run_scheduler_once(
            runtime,
            limit=args.limit,
            lease_seconds=args.lease_seconds,
            stale_run_after_seconds=(
                parse_duration_to_seconds(args.stale_run_after)
                if args.stale_run_after
                else None
            ),
            max_llm_runs_per_pass=args.max_llm_runs_per_pass,
        )
    except Exception as exc:  # pragma: no cover - startup safety net
        print(f"brokerai run scheduler-once failed: {exc}")
        return 1
    print(result.render_text())
    return 0


def command_run_scheduler_worker(args: argparse.Namespace) -> int:
    settings = load_settings_from_cli(env_file=args.env_file)
    _configure_app_logging(settings)
    assessment = assess_settings(settings)
    preflight = preflight_scheduler(assessment, settings)
    if not preflight.ok:
        print(render_scheduler_failure(preflight))
        return 1
    try:
        poll_every_seconds = parse_duration_to_seconds(args.poll_every)
    except ValueError as exc:
        print(f"brokerai run scheduler failed: {exc}")
        return 1
    if args.env_file is not None:
        load_env_file(args.env_file, override=True)
    ensure_runtime_directories(settings)
    runtime = build_runtime(settings)
    if runtime.scheduled_process_service is None:
        print("brokerai run scheduler failed: scheduler runtime is not available.")
        return 1
    try:
        return run_scheduler_worker(
            runtime,
            poll_every_seconds=poll_every_seconds,
            limit=args.limit,
            lease_seconds=args.lease_seconds,
            stale_run_after_seconds=(
                parse_duration_to_seconds(args.stale_run_after)
                if args.stale_run_after
                else None
            ),
            max_llm_runs_per_pass=args.max_llm_runs_per_pass,
        )
    except KeyboardInterrupt:
        print("brokerai scheduler stopped.")
        return 0
    except Exception as exc:  # pragma: no cover - startup safety net
        print(f"brokerai run scheduler failed: {exc}")
        return 1


def command_run_alpaca_news_stream(args: argparse.Namespace) -> int:
    settings = load_settings_from_cli(env_file=args.env_file)
    _configure_app_logging(settings)
    if not settings.alpaca_api_key or not settings.alpaca_api_secret:
        print(
            "brokerai run alpaca-news-stream failed: Alpaca API credentials are missing."
        )
        return 1
    try:
        from .alpaca import AlpacaStreamClient, capture_alpaca_news_stream

        client = AlpacaStreamClient.from_settings(settings)
        result = asyncio.run(
            capture_alpaca_news_stream(
                client,
                args.output,
                symbols=args.symbols or [],
                max_events=args.max_events,
                seconds=args.seconds,
                sandbox=bool(args.sandbox),
            )
        )
    except KeyboardInterrupt:
        print("brokerai alpaca news stream stopped.")
        return 0
    except Exception as exc:  # pragma: no cover - live stream safety net
        print(f"brokerai run alpaca-news-stream failed: {exc}")
        return 1
    print(result.render_text())
    return 0


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
        "REFERENCE_DATA_PROVIDER": settings.reference_data_provider,
        "YAHOO_ENABLED": _bool_to_env(settings.yahoo_enabled),
        "ALPHA_VANTAGE_ENABLED": _bool_to_env(settings.alpha_vantage_enabled),
        "REDDIT_ENABLED": _bool_to_env(settings.reddit_enabled),
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
        "REDDIT_CLIENT_ID": existing_raw.get(
            "REDDIT_CLIENT_ID",
            settings.reddit_client_id or "",
        ),
        "REDDIT_CLIENT_SECRET": existing_raw.get(
            "REDDIT_CLIENT_SECRET",
            settings.reddit_client_secret or "",
        ),
        "REDDIT_USERNAME": existing_raw.get(
            "REDDIT_USERNAME",
            settings.reddit_username or "",
        ),
        "REDDIT_PASSWORD": existing_raw.get(
            "REDDIT_PASSWORD",
            settings.reddit_password or "",
        ),
        "REDDIT_REFRESH_TOKEN": existing_raw.get(
            "REDDIT_REFRESH_TOKEN",
            settings.reddit_refresh_token or "",
        ),
        "REDDIT_USER_AGENT": existing_raw.get(
            "REDDIT_USER_AGENT",
            settings.reddit_user_agent or "server:t212ai:v0.1.0 (by /u/your_reddit_username)",
        ),
        "REDDIT_BASE_URL": existing_raw.get(
            "REDDIT_BASE_URL",
            settings.reddit_base_url,
        ),
        "REDDIT_AUTH_URL": existing_raw.get(
            "REDDIT_AUTH_URL",
            settings.reddit_auth_url,
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
        "OPENFIGI_API_KEY": existing_raw.get(
            "OPENFIGI_API_KEY",
            settings.openfigi_api_key or "",
        ),
        "OPENFIGI_BASE_URL": existing_raw.get(
            "OPENFIGI_BASE_URL",
            settings.openfigi_base_url,
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
        "Community research",
        "Optional Reddit research context. You can skip it now and come back later.",
    )
    if _should_update_section(io_runtime, existing, REDDIT_SECTION_KEYS):
        reddit_enabled = io_runtime.confirm(
            "Enable Reddit research integration?",
            default=_env_truthy(updates["REDDIT_ENABLED"]),
        )
        updates["COMMUNITY_PROVIDER"] = "reddit" if reddit_enabled else "none"
        updates["REDDIT_ENABLED"] = _bool_to_env(reddit_enabled)
        if reddit_enabled:
            updates["REDDIT_CLIENT_ID"] = io_runtime.prompt(
                "REDDIT_CLIENT_ID",
                default=updates["REDDIT_CLIENT_ID"],
            )
            updates["REDDIT_CLIENT_SECRET"] = io_runtime.prompt(
                "REDDIT_CLIENT_SECRET",
                default=updates["REDDIT_CLIENT_SECRET"],
            )
            updates["REDDIT_USER_AGENT"] = io_runtime.prompt(
                "REDDIT_USER_AGENT",
                default=updates["REDDIT_USER_AGENT"],
            )
            reddit_auth_mode = io_runtime.choose(
                "Reddit auth mode",
                options=REDDIT_AUTH_OPTIONS,
                default="refresh_token" if updates["REDDIT_REFRESH_TOKEN"] else "username_password",
            )
            if reddit_auth_mode == "refresh_token":
                updates["REDDIT_REFRESH_TOKEN"] = io_runtime.prompt(
                    "REDDIT_REFRESH_TOKEN",
                    default=updates["REDDIT_REFRESH_TOKEN"],
                )
                _clear_env_keys(updates, "REDDIT_USERNAME", "REDDIT_PASSWORD")
            else:
                updates["REDDIT_USERNAME"] = io_runtime.prompt(
                    "REDDIT_USERNAME",
                    default=updates["REDDIT_USERNAME"],
                )
                updates["REDDIT_PASSWORD"] = io_runtime.prompt(
                    "REDDIT_PASSWORD",
                    default=updates["REDDIT_PASSWORD"],
                )
                _clear_env_keys(updates, "REDDIT_REFRESH_TOKEN")

    _write_step_intro(
        io_runtime,
        "Search integration",
        "SearXNG is expected to be compose-managed, so this wizard does not prompt for it. "
        "Keep the current search settings as they are, or edit SEARCH_PROVIDER and "
        "SEARXNG_BASE_URL later.",
    )

    _write_step_intro(
        io_runtime,
        "Reference data",
        "OpenFIGI is optional broker-agnostic security reference data. It works "
        "without an API key, and an optional key raises OpenFIGI rate limits.",
    )
    if _should_update_section(io_runtime, existing, REFERENCE_DATA_SECTION_KEYS):
        openfigi_enabled = io_runtime.confirm(
            "Enable OpenFIGI reference-data lookup?",
            default=updates["REFERENCE_DATA_PROVIDER"].strip().lower() == "openfigi",
        )
        updates["REFERENCE_DATA_PROVIDER"] = "openfigi" if openfigi_enabled else "none"
        if openfigi_enabled:
            updates["OPENFIGI_API_KEY"] = io_runtime.prompt(
                "OPENFIGI_API_KEY (optional)",
                default=updates["OPENFIGI_API_KEY"],
            )
        updates["OPENFIGI_BASE_URL"] = updates["OPENFIGI_BASE_URL"] or "https://api.openfigi.com"

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
    io_runtime.write(title)
    io_runtime.write(description)


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


def render_configuration_review(updates: Mapping[str, str]) -> str:
    lines = ["Configuration review"]
    for section_name, keys in MANAGED_ENV_SECTIONS:
        relevant = [key for key in keys if key in updates]
        if not relevant:
            continue
        lines.append("")
        lines.append(f"{section_name}:")
        for key in relevant:
            lines.append(f"- {key}={_display_env_value(key, updates[key])}")
    return "\n".join(lines)


def render_doctor_report(
    settings: AppSettings,
    assessment: ConfigAssessment,
    preflight,
    *,
    smoke_results: Mapping[str, object] | None = None,
) -> str:
    lines = [
        "brokerai doctor",
        "",
        f"Configuration status: {'valid' if assessment.is_valid else 'invalid'}",
        f"Run bot preflight: {'ready' if preflight.ok else 'blocked'}",
        "",
        "Providers:",
    ]
    for key in (
        "llm",
        "broker",
        "telegram",
        "yahoo",
        "alpaca",
        "alpha_vantage",
        "reddit",
        "searxng",
        "sec_edgar",
        "openfigi",
    ):
        provider = assessment.providers[key]
        lines.extend(_render_provider(provider))

    lines.append("")
    lines.append("Capabilities:")
    for key in (
        "llm_reasoning",
        "telegram_bridge",
        "broker_read",
        "broker_execution_eligibility",
        "market_data",
        "market_intelligence",
        "disclosure",
        "research_community_context",
        "search",
        "reference_data",
        "persistent_guideline_memory",
        "market_signal_memory",
        "scheduled_processes",
        "scheduler_notifications",
        "scheduler_instrument_monitor",
        "scheduler_delegate",
        "scheduler_company_event_analyst",
        "scheduler_market_regime_monitor",
        "scheduler_market_signal_capture",
        "scheduler_trade_setup_monitor",
    ):
        capability = assessment.capabilities[key]
        lines.append(
            f"- {capability.label}: {'available' if capability.available else 'unavailable'}"
        )
        if capability.selected_provider:
            lines.append(f"  provider: {capability.selected_provider}")
        for reason in capability.reasons:
            lines.append(f"  reason: {reason}")

    if assessment.configuration_errors:
        lines.append("")
        lines.append("Configuration errors:")
        for error in assessment.configuration_errors:
            lines.append(f"- {error}")

    if preflight.blocking_errors:
        lines.append("")
        lines.append("Run bot blockers:")
        for error in preflight.blocking_errors:
            lines.append(f"- {error}")

    if assessment.warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in assessment.warnings:
            lines.append(f"- {warning}")

    if smoke_results:
        lines.append("")
        lines.append("Provider smoke checks:")
        lines.append(render_provider_smoke_report(smoke_results))

    lines.append("")
    lines.append(f"LLM provider selection: {settings.llm_provider}")
    lines.append(f"GenAI context fallback tokens: {settings.genai_context_fallback_tokens}")
    lines.append(f"Broker provider selection: {settings.broker_provider}")
    lines.append(f"Market data provider selection: {settings.market_data_provider}")
    lines.append(
        f"Market intelligence provider selection: {settings.market_intelligence_provider}"
    )
    lines.append(f"Disclosure provider selection: {settings.disclosure_provider}")
    lines.append(f"Community provider selection: {settings.community_provider}")
    lines.append(f"Search provider selection: {settings.search_provider}")
    lines.append(f"Reference data provider selection: {settings.reference_data_provider}")
    lines.append(f"Scheduler worker id: {settings.scheduler_worker_id or 'auto'}")
    lines.append(f"App log format: {settings.app_log_format}")
    lines.append(f"App log retention days: {settings.app_log_retention_days}")
    lines.append(f"Third-party log level: {settings.app_log_third_party_level}")
    lines.append(f"Scheduler lease seconds: {settings.scheduler_lease_seconds}")
    lines.append(
        f"Scheduler stale run after seconds: {settings.scheduler_stale_run_after_seconds}"
    )
    lines.append(
        "Scheduler max LLM runs per pass: "
        f"{settings.scheduler_max_llm_runs_per_pass or 'unlimited'}"
    )
    return "\n".join(lines)


def render_run_bot_failure(preflight) -> str:
    lines = ["brokerai run bot cannot start.", ""]
    lines.append("Blocking issues:")
    for error in preflight.blocking_errors:
        lines.append(f"- {error}")
    if preflight.warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in preflight.warnings:
            lines.append(f"- {warning}")
    return "\n".join(lines)


def render_reconcile_failure(preflight) -> str:
    lines = ["brokerai reconciliation cannot start.", ""]
    lines.append("Blocking issues:")
    for error in preflight.blocking_errors:
        lines.append(f"- {error}")
    if preflight.warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in preflight.warnings:
            lines.append(f"- {warning}")
    return "\n".join(lines)


def render_scheduler_failure(preflight) -> str:
    lines = ["brokerai scheduler cannot start.", ""]
    lines.append("Blocking issues:")
    for error in preflight.blocking_errors:
        lines.append(f"- {error}")
    if preflight.warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in preflight.warnings:
            lines.append(f"- {warning}")
    return "\n".join(lines)


def render_scheduler_status(status: Mapping[str, object], settings: AppSettings) -> str:
    lines = [
        "brokerai scheduler status",
        f"asOf: {status.get('asOf')}",
        f"processes: {status.get('processCount', 0)}",
        f"due: {status.get('dueCount', 0)}",
        f"startedRuns: {status.get('startedRunCount', 0)}",
        f"activeLeases: {status.get('activeLeaseCount', 0)}",
        f"nextRunAt: {status.get('nextRunAt') or 'none'}",
        f"oldestStartedRunAt: {status.get('oldestStartedRunAt') or 'none'}",
        "",
        "operational defaults:",
        f"- workerId: {settings.scheduler_worker_id or 'auto'}",
        f"- leaseSeconds: {settings.scheduler_lease_seconds}",
        f"- staleRunAfterSeconds: {settings.scheduler_stale_run_after_seconds}",
        f"- maxLlmRunsPerPass: {settings.scheduler_max_llm_runs_per_pass or 'unlimited'}",
    ]
    by_status = status.get("processesByStatus") or {}
    if isinstance(by_status, Mapping) and by_status:
        lines.append("")
        lines.append("by status:")
        for key, value in by_status.items():
            lines.append(f"- {key}: {value}")
    by_kind = status.get("processesByKind") or {}
    if isinstance(by_kind, Mapping) and by_kind:
        lines.append("")
        lines.append("by kind:")
        for key, value in by_kind.items():
            lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def render_scheduler_process_list(processes) -> str:
    if not processes:
        return "No scheduled processes matched the provided filters."
    lines = [f"Found {len(processes)} scheduled process(es)."]
    for process in processes:
        lines.append(
            "- "
            + " | ".join(
                [
                    process.process_id,
                    process.kind.value,
                    process.status.value,
                    f"title={process.title}",
                    f"nextRunAt={process.next_run_at}",
                    f"lastStatus={process.last_status.value if process.last_status else None}",
                ]
            )
        )
    return "\n".join(lines)


def render_scheduler_process_detail(process, runs, events) -> str:
    lines = [
        f"Scheduled process {process.process_id}",
        f"title: {process.title}",
        f"kind: {process.kind.value}",
        f"status: {process.status.value}",
        f"executionMode: {process.execution_mode.value}",
        f"nextRunAt: {process.next_run_at}",
        f"lastStatus: {process.last_status.value if process.last_status else None}",
        f"failureCount: {process.failure_count}",
        f"schedule: {json.dumps(process.schedule.model_dump(by_alias=True, exclude_none=True, mode='json'), sort_keys=True)}",
        f"trigger: {json.dumps(process.trigger, sort_keys=True)}",
        f"lifecycle: {json.dumps(process.lifecycle.model_dump(by_alias=True, exclude_none=True, mode='json'), sort_keys=True)}",
        "",
        f"Runs ({len(runs)}):",
    ]
    for run in runs:
        code = run.error_code or "none"
        lines.append(
            f"- {run.run_id} {run.status.value} matched={run.matched} code={code} startedAt={run.started_at}"
        )
    lines.append("")
    lines.append(f"Events ({len(events)}):")
    for event in events:
        lines.append(
            f"- {event.created_at} {event.event_type.value}: {event.message}"
        )
    return "\n".join(lines)


def render_scheduler_maintenance_result(operation: str, result) -> str:
    mode = "dry-run" if result.dry_run else "applied"
    lines = [
        f"brokerai scheduler {operation}: {mode}",
        f"matched={result.matched_count} changed={result.changed_count}",
    ]
    if result.run_count:
        lines.append(f"runs={result.run_count}")
    if result.event_count:
        lines.append(f"events={result.event_count}")
    if result.process_ids:
        lines.append("processes: " + ", ".join(result.process_ids))
    if result.run_ids:
        lines.append("runs: " + ", ".join(result.run_ids))
    return "\n".join(lines)


def _build_scheduler_runtime_for_command(args: argparse.Namespace, command_name: str):
    settings = load_settings_from_cli(env_file=args.env_file)
    _configure_app_logging(settings)
    assessment = assess_settings(settings)
    preflight = preflight_scheduler(assessment, settings)
    if not preflight.ok:
        print(render_scheduler_failure(preflight))
        return None
    if args.env_file is not None:
        load_env_file(args.env_file, override=True)
    ensure_runtime_directories(settings)
    runtime = build_runtime(settings)
    if runtime.scheduled_process_service is None:
        print(f"brokerai {command_name} failed: scheduler runtime is not available.")
        return None
    return runtime


def _cutoff_from_duration_or_iso(raw: str) -> datetime:
    value = str(raw or "").strip()
    if not value:
        raise ValueError("Cutoff is required.")
    try:
        seconds = parse_duration_to_seconds(value)
    except ValueError:
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError(
                "Cutoff must be a duration such as 30d or an ISO-8601 datetime."
            ) from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


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


def _render_provider(provider: ProviderAssessment) -> list[str]:
    if provider.ready:
        status = "ready"
    elif provider.enabled:
        status = "misconfigured"
    elif provider.configured:
        status = "configured"
    else:
        status = "disabled"
    lines = [f"- {provider.label}: {status}"]
    if provider.missing_keys:
        lines.append("  missing: " + ", ".join(provider.missing_keys))
    for note in provider.notes:
        lines.append(f"  note: {note}")
    return lines


def render_provider_smoke_report(smoke_results: Mapping[str, object]) -> str:
    lines: list[str] = []
    for result in smoke_results.values():
        status = str(getattr(result, "status", "unknown"))
        label = str(getattr(result, "label", "provider"))
        message = str(getattr(result, "message", "")).strip()
        lines.append(f"- {label}: {status}")
        if message:
            lines.append(f"  note: {message}")
        for warning in getattr(result, "warnings", ()) or ():
            lines.append(f"  warning: {warning}")
    return "\n".join(lines)


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


def _default_prog_name() -> str:
    argv0 = Path(sys.argv[0]).name if sys.argv else ""
    return argv0 or "brokerai"


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


def run_reconcile_once(runtime) -> object:
    if runtime.reconciliation_service is None:
        raise RuntimeError("Reconciliation service is not configured.")
    return runtime.reconciliation_service.reconcile_once()


def run_reconcile_worker(runtime, *, interval_seconds: int) -> int:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than zero.")
    while True:
        result = run_reconcile_once(runtime)
        print(result.render_text())
        time.sleep(interval_seconds)


def run_scheduler_once(
    runtime,
    *,
    limit: int = 100,
    lease_seconds: int | None = None,
    stale_run_after_seconds: int | None = None,
    max_llm_runs_per_pass: int | None = None,
) -> object:
    return run_runtime_scheduler_once(
        runtime,
        limit=limit,
        lease_seconds=lease_seconds,
        stale_run_after_seconds=stale_run_after_seconds,
        max_llm_runs_per_pass=max_llm_runs_per_pass,
    )


def run_scheduler_worker(
    runtime,
    *,
    poll_every_seconds: int,
    limit: int = 100,
    lease_seconds: int | None = None,
    stale_run_after_seconds: int | None = None,
    max_llm_runs_per_pass: int | None = None,
) -> int:
    if poll_every_seconds <= 0:
        raise ValueError("poll_every_seconds must be greater than zero.")
    while True:
        result = run_scheduler_once(
            runtime,
            limit=limit,
            lease_seconds=lease_seconds,
            stale_run_after_seconds=stale_run_after_seconds,
            max_llm_runs_per_pass=max_llm_runs_per_pass,
        )
        print(result.render_text())
        time.sleep(poll_every_seconds)
