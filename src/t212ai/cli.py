from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, TextIO

from .app.bootstrap import (
    ConfigAssessment,
    ProviderAssessment,
    assess_settings,
    ensure_runtime_directories,
    preflight_run_bot,
)
from .app.config import (
    DEFAULT_ENV_FILE_NAME,
    AppSettings,
    get_app_settings,
    load_env_file,
    parse_env_file,
)


LLM_PROVIDER_OPTIONS = (
    ("openai", "OpenAI"),
    ("azure_openai", "Azure OpenAI"),
    ("none", "Disabled"),
)
BROKER_PROVIDER_OPTIONS = (
    ("trading212", "Trading 212"),
    ("none", "Disabled"),
)
ENVIRONMENT_OPTIONS = (
    ("demo", "Demo"),
    ("live", "Live"),
)
REDDIT_AUTH_OPTIONS = (
    ("refresh_token", "Refresh token"),
    ("username_password", "Username and password"),
)
SECRET_KEYS = frozenset(
    {
        "OPENAI_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "T212_API_KEY",
        "T212_API_SECRET",
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
            "AZURE_OPENAI_ENABLED",
            "AZURE_OPENAI_ENDPOINT",
            "AZURE_OPENAI_API_KEY",
            "AZURE_OPENAI_API_VERSION",
            "AZURE_OPENAI_EMBED_DEPLOYMENT",
        ),
    ),
    (
        "Trading 212",
        (
            "T212_ENVIRONMENT",
            "T212_DEMO_BASE_URL",
            "T212_LIVE_BASE_URL",
            "T212_API_KEY",
            "T212_API_SECRET",
            "T212_LIVE_TRADING_ENABLED",
        ),
    ),
    (
        "Telegram",
        (
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_ALLOWED_CHAT_ID",
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
        "Local persistence",
        (
            "GUIDELINE_MEMORY_PATH",
            "DATABASE_URL",
        ),
    ),
    (
        "Research/search tools",
        ("SEARXNG_BASE_URL",),
    ),
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
    doctor_parser.set_defaults(handler=command_doctor)

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
    io_runtime.write("")

    updates = build_managed_env_values(existing_raw)
    apply_configuration_wizard(io_runtime, updates)

    io_runtime.write("")
    io_runtime.write(render_configuration_review(updates))
    io_runtime.write("")
    if not io_runtime.confirm("Write these settings to disk?", default=True):
        io_runtime.write("Configuration aborted. No changes were written.")
        return 1

    update_env_file(env_path, updates)
    settings = get_app_settings(env=updates)
    directories = ensure_runtime_directories(settings)
    io_runtime.write(f"Saved configuration to {env_path}.")
    io_runtime.write("Ensured local directories:")
    for directory in directories:
        io_runtime.write(f"- {directory}")
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    settings = load_settings_from_cli(env_file=args.env_file)
    assessment = assess_settings(settings)
    preflight = preflight_run_bot(assessment)
    print(render_doctor_report(settings, assessment, preflight))
    return 0 if assessment.is_valid else 1


def command_run_bot(args: argparse.Namespace) -> int:
    settings = load_settings_from_cli(env_file=args.env_file)
    assessment = assess_settings(settings)
    preflight = preflight_run_bot(assessment)
    if not preflight.ok:
        print(render_run_bot_failure(preflight))
        return 1

    if args.env_file is not None:
        load_env_file(args.env_file, override=True)
    ensure_runtime_directories(settings)

    try:
        from .telegram import TelegramBotService

        TelegramBotService.from_settings(settings).run_polling()
    except Exception as exc:  # pragma: no cover - startup safety net
        print(f"brokerai run bot failed: {exc}")
        return 1
    return 0


def load_settings_from_cli(*, env_file: str | None) -> AppSettings:
    if env_file is None:
        return get_app_settings()
    env_path = Path(env_file)
    raw = parse_env_file(env_path) if env_path.exists() else {}
    return get_app_settings(env=raw)


def build_managed_env_values(existing_raw: Mapping[str, str]) -> dict[str, str]:
    settings = get_app_settings(env=existing_raw)
    values = {
        "LLM_PROVIDER": settings.llm_provider,
        "BROKER_PROVIDER": settings.broker_provider,
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
        "T212_ENVIRONMENT": existing_raw.get(
            "T212_ENVIRONMENT",
            settings.trading212_environment,
        ),
        "T212_DEMO_BASE_URL": existing_raw.get(
            "T212_DEMO_BASE_URL",
            settings.trading212_demo_base_url,
        ),
        "T212_LIVE_BASE_URL": existing_raw.get(
            "T212_LIVE_BASE_URL",
            settings.trading212_live_base_url,
        ),
        "T212_API_KEY": existing_raw.get("T212_API_KEY", settings.trading212_api_key or ""),
        "T212_API_SECRET": existing_raw.get(
            "T212_API_SECRET",
            settings.trading212_api_secret or "",
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
        "ALPHA_VANTAGE_API_KEY": existing_raw.get(
            "ALPHA_VANTAGE_API_KEY",
            settings.alpha_vantage_api_key or "",
        ),
        "ALPHA_VANTAGE_BASE_URL": existing_raw.get(
            "ALPHA_VANTAGE_BASE_URL",
            settings.alpha_vantage_base_url,
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
        "GUIDELINE_MEMORY_PATH": existing_raw.get(
            "GUIDELINE_MEMORY_PATH",
            settings.guideline_memory_path,
        ),
        "DATABASE_URL": existing_raw.get("DATABASE_URL", settings.database_url),
        "SEARXNG_BASE_URL": existing_raw.get(
            "SEARXNG_BASE_URL",
            settings.searxng_base_url or "",
        ),
    }
    return values


def apply_configuration_wizard(io_runtime: TerminalIO, updates: dict[str, str]) -> None:
    llm_provider = io_runtime.choose(
        "LLM provider",
        options=LLM_PROVIDER_OPTIONS,
        default=_safe_choice(updates["LLM_PROVIDER"], {"openai", "azure_openai", "none"}, "none"),
    )
    updates["LLM_PROVIDER"] = llm_provider
    if llm_provider == "openai":
        updates["AZURE_OPENAI_ENABLED"] = "false"
        updates["OPENAI_API_KEY"] = io_runtime.prompt(
            "OPENAI_API_KEY",
            default=updates["OPENAI_API_KEY"],
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
    else:
        updates["AZURE_OPENAI_ENABLED"] = "false"

    io_runtime.write("")
    broker_provider = io_runtime.choose(
        "Broker provider",
        options=BROKER_PROVIDER_OPTIONS,
        default=_safe_choice(updates["BROKER_PROVIDER"], {"trading212", "none"}, "none"),
    )
    updates["BROKER_PROVIDER"] = broker_provider
    if broker_provider == "trading212":
        updates["T212_ENVIRONMENT"] = io_runtime.choose(
            "Trading 212 environment",
            options=ENVIRONMENT_OPTIONS,
            default=_safe_choice(updates["T212_ENVIRONMENT"], {"demo", "live"}, "demo"),
        )
        updates["T212_API_KEY"] = io_runtime.prompt(
            "T212_API_KEY",
            default=updates["T212_API_KEY"],
        )
        updates["T212_API_SECRET"] = io_runtime.prompt(
            "T212_API_SECRET",
            default=updates["T212_API_SECRET"],
        )
        if updates["T212_ENVIRONMENT"] == "live":
            allow_live = io_runtime.confirm(
                "Allow live order execution when running in live environment?",
                default=_env_truthy(updates["T212_LIVE_TRADING_ENABLED"]),
            )
            updates["T212_LIVE_TRADING_ENABLED"] = _bool_to_env(allow_live)
        else:
            updates["T212_LIVE_TRADING_ENABLED"] = "false"

    io_runtime.write("")
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

    io_runtime.write("")
    yahoo_enabled = io_runtime.confirm(
        "Enable Yahoo Finance market data?",
        default=_env_truthy(updates["YAHOO_ENABLED"]),
    )
    updates["YAHOO_ENABLED"] = _bool_to_env(yahoo_enabled)

    alpha_enabled = io_runtime.confirm(
        "Enable Alpha Vantage?",
        default=_env_truthy(updates["ALPHA_VANTAGE_ENABLED"]),
    )
    updates["ALPHA_VANTAGE_ENABLED"] = _bool_to_env(alpha_enabled)
    if alpha_enabled:
        updates["ALPHA_VANTAGE_API_KEY"] = io_runtime.prompt(
            "ALPHA_VANTAGE_API_KEY",
            default=updates["ALPHA_VANTAGE_API_KEY"],
        )

    reddit_enabled = io_runtime.confirm(
        "Enable Reddit research integration?",
        default=_env_truthy(updates["REDDIT_ENABLED"]),
    )
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
        else:
            updates["REDDIT_USERNAME"] = io_runtime.prompt(
                "REDDIT_USERNAME",
                default=updates["REDDIT_USERNAME"],
            )
            updates["REDDIT_PASSWORD"] = io_runtime.prompt(
                "REDDIT_PASSWORD",
                default=updates["REDDIT_PASSWORD"],
            )

    searxng_enabled = io_runtime.confirm(
        "Enable SearXNG web search?",
        default=_env_truthy(updates["SEARXNG_ENABLED"]),
    )
    updates["SEARXNG_ENABLED"] = _bool_to_env(searxng_enabled)
    if searxng_enabled:
        updates["SEARXNG_BASE_URL"] = io_runtime.prompt(
            "SEARXNG_BASE_URL",
            default=updates["SEARXNG_BASE_URL"],
        )

    io_runtime.write("")
    if io_runtime.confirm(
        "Customize storage paths?",
        default=False,
    ):
        updates["DATABASE_URL"] = io_runtime.prompt(
            "DATABASE_URL",
            default=updates["DATABASE_URL"],
        )
        updates["GUIDELINE_MEMORY_PATH"] = io_runtime.prompt(
            "GUIDELINE_MEMORY_PATH",
            default=updates["GUIDELINE_MEMORY_PATH"],
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
        "alpha_vantage",
        "reddit",
        "searxng",
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
        "research_community_context",
        "search",
        "persistent_guideline_memory",
    ):
        capability = assessment.capabilities[key]
        lines.append(
            f"- {capability.label}: {'available' if capability.available else 'unavailable'}"
        )
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

    lines.append("")
    lines.append(f"LLM provider selection: {settings.llm_provider}")
    lines.append(f"Broker provider selection: {settings.broker_provider}")
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
