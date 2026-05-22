"""Configuration help and sample environment profiles."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from typing import Iterable

from .config_wizard import build_managed_env_values
from .constants import MANAGED_ENV_SECTIONS, SECRET_KEYS
from .style import render_banner, render_box


@dataclass(frozen=True, slots=True)
class ConfigKey:
    name: str
    section: str
    purpose: str
    default: str = ""
    example: str = ""
    scenario: str = ""
    required_when: str = ""
    secret: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


_CONFIG_NOTES: dict[str, dict[str, str]] = {
    "LLM_PROVIDER": {
        "purpose": "Selects the reasoning provider used by the Telegram agent and specialists.",
        "example": "openai",
        "scenario": (
            "Set to none for storage/scheduler-only local work; set to openai "
            "or azure_openai for chat and analysis."
        ),
        "required_when": "Required for brokerai run bot.",
    },
    "OPENAI_CHAT_MODEL_DEFAULT": {
        "purpose": "Baseline chat model or Azure deployment for routine orchestration tasks.",
        "example": "gpt-4o-mini",
        "scenario": (
            "Use a cheaper model here and reserve smart/reasoning models for "
            "harder tasks."
        ),
    },
    "OPENAI_CHAT_MODEL_SMART": {
        "purpose": "Optional stronger model for delicate analysis and higher-value decisions.",
        "example": "gpt-4.1",
        "scenario": (
            "Useful when portfolio, company, or order analysis needs better "
            "judgment than the default model."
        ),
    },
    "OPENAI_CHAT_MODEL_REASONING": {
        "purpose": "Optional reasoning-oriented model for deeper planning tasks.",
        "example": "o4-mini",
        "scenario": "Useful for multi-step analysis, repair, and evaluation paths.",
    },
    "GENAI_CONTEXT_GUARD_RATIO": {
        "purpose": "Safety ratio applied before the configured model context limit is reached.",
        "example": "0.95",
        "scenario": "Lower this if provider calls are hitting context limit failures.",
    },
    "BROKER_PROVIDER": {
        "purpose": (
            "Selects the broker used for account-authoritative reads and "
            "prepared order execution."
        ),
        "example": "trading212",
        "scenario": (
            "Use none for research-only mode; use trading212 or alpaca when "
            "portfolio or order workflows are needed."
        ),
    },
    "T212_ENVIRONMENT": {
        "purpose": "Selects the active Trading 212 credential set and API host.",
        "example": "demo",
        "scenario": (
            "Keep demo during development. Switch to live only after doctor "
            "and smoke checks are clean."
        ),
    },
    "T212_LIVE_TRADING_ENABLED": {
        "purpose": "Explicit safety switch for live Trading 212 order execution.",
        "example": "false",
        "scenario": (
            "Read-only live account access can stay enabled while live order "
            "execution remains blocked."
        ),
    },
    "ALPACA_ENVIRONMENT": {
        "purpose": "Selects Alpaca paper or live credentials and trading host.",
        "example": "paper",
        "scenario": (
            "Use paper for development and for market-data reuse when you do "
            "not want live broker access."
        ),
    },
    "ALPACA_DATA_FEED": {
        "purpose": "Selects the Alpaca market-data feed.",
        "example": "iex",
        "scenario": (
            "IEX is a common free/paper-friendly baseline; use provider-authorized "
            "feeds for broader coverage."
        ),
    },
    "MARKET_DATA_PROVIDER": {
        "purpose": "Selects the quote/bar provider used for market context.",
        "example": "yahoo",
        "scenario": (
            "Yahoo is convenient for local research; Alpaca is useful when "
            "already configured for market data."
        ),
    },
    "MARKET_INTELLIGENCE_PROVIDER": {
        "purpose": (
            "Selects optional enrichment for movers, indicators, or broader "
            "market intelligence."
        ),
        "example": "alpha_vantage",
        "scenario": "Enable when you want richer analysis beyond raw quote data.",
    },
    "DISCLOSURE_PROVIDER": {
        "purpose": "Selects official disclosure/filing context provider.",
        "example": "sec_edgar",
        "scenario": "Keep enabled for company analysis where official filings matter.",
    },
    "SEARCH_PROVIDER": {
        "purpose": "Selects the web-search provider for research workflows.",
        "example": "searxng",
        "scenario": "Use SearXNG when running the compose stack with local search.",
    },
    "TELEGRAM_ALLOWED_CHAT_ID": {
        "purpose": "Allow-list of chat IDs that may interact with the bot.",
        "example": "123456789",
        "scenario": "The bot fails closed when this is empty for bot startup.",
        "required_when": "Required for brokerai run bot.",
    },
    "TELEGRAM_ALLOWED_USER_ID": {
        "purpose": "Optional user-level allow-list layered on top of chat access.",
        "example": "123456789",
        "scenario": "Use this in groups or shared chats to restrict who can issue requests.",
    },
    "LANGSMITH_TRACING": {
        "purpose": "Enables LangSmith traces for agent, model, and tool execution.",
        "example": "true",
        "scenario": "Turn on while debugging routing, tool use, or provider failures.",
    },
    "DATABASE_URL": {
        "purpose": (
            "SQL database URL for pending actions, proposals, reconciliation, "
            "and scheduler state."
        ),
        "example": "sqlite:///./data/t212ai.db",
        "scenario": (
            "SQLite is the local default. Scheduler and execution audit features "
            "depend on this."
        ),
    },
    "GUIDELINE_MEMORY_PATH": {
        "purpose": "File path for durable user guidelines and operating preferences.",
        "example": "data/guidelines/guidelines.json",
        "scenario": "Keep this on persistent storage if running in containers.",
    },
    "APP_LOG_FORMAT": {
        "purpose": "Controls whether application logs are JSON or plain text.",
        "example": "json",
        "scenario": "JSON is better for local diagnostics and log aggregation.",
    },
    "SCHEDULER_DEFAULT_TIMEZONE": {
        "purpose": "Default timezone used to interpret user schedule requests before UTC storage.",
        "example": "Europe/Rome",
        "scenario": "Set this to your local market operating timezone.",
    },
    "SCHEDULER_LEASE_SECONDS": {
        "purpose": "How long a claimed scheduled process is protected from other workers.",
        "example": "1800",
        "scenario": "Lower for fast local testing; keep higher for longer LLM-assisted jobs.",
    },
    "SCHEDULER_STALE_RUN_AFTER_SECONDS": {
        "purpose": "Age after which started scheduler runs are eligible for stale recovery.",
        "example": "3600",
        "scenario": "Set above the longest normal worker runtime to avoid premature recovery.",
    },
    "SCHEDULER_MAX_LLM_RUNS_PER_PASS": {
        "purpose": (
            "Optional per-pass throttle for LLM-assisted scheduler work. Zero "
            "means unlimited."
        ),
        "example": "0",
        "scenario": "Use a positive value when controlling token spend during catch-up runs.",
    },
    "SCHEDULER_EMBEDDED_WORKER_ENABLED": {
        "purpose": "Runs the scheduler loop inside the Telegram bot process.",
        "example": "true",
        "scenario": (
            "Convenient for single-process local deployment; disable when using "
            "a separate scheduler worker."
        ),
    },
    "ALPACA_NEWS_STREAM_SUPERVISOR_ENABLED": {
        "purpose": "Runs Alpaca news-stream monitors from the bot process when configured.",
        "example": "true",
        "scenario": "Disable when news stream capture is handled by a separate process.",
    },
    "SEARXNG_BASE_URL": {
        "purpose": "Base URL for SearXNG search.",
        "example": "http://searxng:8080",
        "scenario": "Docker Compose can provide this service locally for research workflows.",
    },
    "SEC_EDGAR_USER_AGENT": {
        "purpose": "Optional SEC fair-access identification for EDGAR requests.",
        "example": "Your Name your.email@example.com",
        "scenario": "Set this for polite and identifiable SEC filing access.",
    },
}


_SAMPLE_PROFILES: dict[str, tuple[str, ...]] = {
    "demo": (
        "LLM_PROVIDER=openai",
        "OPENAI_API_KEY=sk-...",
        "BROKER_PROVIDER=trading212",
        "T212_ENVIRONMENT=demo",
        "T212_DEMO_API_KEY=...",
        "T212_DEMO_API_SECRET=...",
        "MARKET_DATA_PROVIDER=yahoo",
        "DISCLOSURE_PROVIDER=sec_edgar",
        "TELEGRAM_BOT_TOKEN=...",
        "TELEGRAM_ALLOWED_CHAT_ID=123456789",
        "DATABASE_URL=sqlite:///./data/t212ai.db",
    ),
    "research": (
        "LLM_PROVIDER=openai",
        "OPENAI_API_KEY=sk-...",
        "BROKER_PROVIDER=none",
        "MARKET_DATA_PROVIDER=yahoo",
        "MARKET_INTELLIGENCE_PROVIDER=alpha_vantage",
        "ALPHA_VANTAGE_API_KEY=...",
        "DISCLOSURE_PROVIDER=sec_edgar",
        "SEARCH_PROVIDER=searxng",
        "SEARXNG_BASE_URL=http://localhost:8080",
        "DATABASE_URL=sqlite:///./data/t212ai.db",
    ),
    "alpaca-paper": (
        "LLM_PROVIDER=openai",
        "OPENAI_API_KEY=sk-...",
        "BROKER_PROVIDER=alpaca",
        "ALPACA_ENVIRONMENT=paper",
        "ALPACA_PAPER_API_KEY=...",
        "ALPACA_PAPER_API_SECRET=...",
        "MARKET_DATA_PROVIDER=alpaca",
        "ALPACA_DATA_FEED=iex",
        "TELEGRAM_BOT_TOKEN=...",
        "TELEGRAM_ALLOWED_CHAT_ID=123456789",
        "DATABASE_URL=sqlite:///./data/t212ai.db",
    ),
    "live-guarded": (
        "LLM_PROVIDER=openai",
        "OPENAI_API_KEY=sk-...",
        "BROKER_PROVIDER=trading212",
        "T212_ENVIRONMENT=live",
        "T212_LIVE_API_KEY=...",
        "T212_LIVE_API_SECRET=...",
        "T212_LIVE_TRADING_ENABLED=false",
        "MARKET_DATA_PROVIDER=yahoo",
        "TELEGRAM_BOT_TOKEN=...",
        "TELEGRAM_ALLOWED_CHAT_ID=123456789",
        "TELEGRAM_ALLOWED_USER_ID=123456789",
        "DATABASE_URL=sqlite:///./data/t212ai.db",
    ),
}


def all_config_keys() -> tuple[ConfigKey, ...]:
    defaults = build_managed_env_values({})
    keys: list[ConfigKey] = []
    for section, section_keys in MANAGED_ENV_SECTIONS:
        for key in section_keys:
            note = _CONFIG_NOTES.get(key, {})
            keys.append(
                ConfigKey(
                    name=key,
                    section=section,
                    purpose=note.get("purpose", f"{section} setting used by brokerai runtime."),
                    default=defaults.get(key, ""),
                    example=note.get("example", defaults.get(key, "")),
                    scenario=note.get("scenario", ""),
                    required_when=note.get("required_when", ""),
                    secret=key in SECRET_KEYS,
                )
            )
    return tuple(keys)


def find_config_key(name: str) -> ConfigKey | None:
    normalized = str(name or "").strip().upper()
    return next((key for key in all_config_keys() if key.name == normalized), None)


def command_config_list(args: argparse.Namespace) -> int:
    keys = _filter_by_section(all_config_keys(), args.section)
    if args.format == "json":
        print(json.dumps([key.to_dict() for key in keys], indent=2, sort_keys=True))
        return 0
    print(render_banner("T212AI"))
    print("brokerai config list")
    current_section = ""
    for key in keys:
        if key.section != current_section:
            current_section = key.section
            print("")
            print(current_section)
        default = "<secret>" if key.secret and key.default else key.default
        suffix = f" default={default}" if default else ""
        print(f"- {key.name}{suffix}")
    return 0


def command_config_explain(args: argparse.Namespace) -> int:
    key = find_config_key(args.key)
    if key is None:
        print(f"Unknown config key: {args.key}")
        return 1
    if args.format == "json":
        print(json.dumps(key.to_dict(), indent=2, sort_keys=True))
        return 0
    lines = [
        f"{key.name}",
        f"Section: {key.section}",
        f"Purpose: {key.purpose}",
        f"Default: {'<secret>' if key.secret and key.default else key.default or '<empty>'}",
        f"Example: {'<secret>' if key.secret else key.example or '<empty>'}",
    ]
    if key.required_when:
        lines.append(f"Required when: {key.required_when}")
    if key.scenario:
        lines.append(f"Scenario: {key.scenario}")
    print(render_box("\n".join(lines), title="Config explain"))
    return 0


def command_config_sample(args: argparse.Namespace) -> int:
    profile = str(args.profile or "").strip().lower()
    if profile not in _SAMPLE_PROFILES:
        print("Unknown sample profile. Available: " + ", ".join(sorted(_SAMPLE_PROFILES)))
        return 1
    print(f"# brokerai config sample: {profile}")
    print("\n".join(_SAMPLE_PROFILES[profile]))
    return 0


def command_config_validate(args: argparse.Namespace) -> int:
    from .doctor import command_doctor

    return command_doctor(argparse.Namespace(env_file=args.env_file, smoke=False))


def _filter_by_section(keys: Iterable[ConfigKey], section: str | None) -> tuple[ConfigKey, ...]:
    if not section:
        return tuple(keys)
    needle = section.strip().lower().replace("-", " ")
    return tuple(
        key
        for key in keys
        if needle in key.section.lower() or needle == key.section.lower().replace("/", "")
    )
