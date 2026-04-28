from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import AppSettings


VALID_LLM_PROVIDERS = frozenset({"openai", "azure_openai", "none"})
VALID_BROKER_PROVIDERS = frozenset({"trading212", "none"})


@dataclass(frozen=True, slots=True)
class ProviderAssessment:
    name: str
    label: str
    enabled: bool
    optional: bool
    configured: bool
    ready: bool
    required_keys: tuple[str, ...] = ()
    missing_keys: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CapabilityAssessment:
    name: str
    label: str
    available: bool
    optional: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConfigAssessment:
    providers: dict[str, ProviderAssessment]
    capabilities: dict[str, CapabilityAssessment]
    configuration_errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.configuration_errors


@dataclass(frozen=True, slots=True)
class StartupPreflight:
    ok: bool
    blocking_errors: tuple[str, ...]
    warnings: tuple[str, ...]


def assess_settings(settings: AppSettings) -> ConfigAssessment:
    providers = {
        "llm": _assess_llm_provider(settings),
        "broker": _assess_broker_provider(settings),
        "telegram": _assess_telegram_provider(settings),
        "yahoo": _assess_yahoo_provider(settings),
        "alpha_vantage": _assess_alpha_vantage_provider(settings),
        "reddit": _assess_reddit_provider(settings),
        "searxng": _assess_searxng_provider(settings),
    }
    capabilities = {
        "llm_reasoning": CapabilityAssessment(
            name="llm_reasoning",
            label="LLM reasoning",
            available=providers["llm"].ready,
            optional=False,
            reasons=_reasons_for_capability(
                providers["llm"].ready,
                "Configure a valid LLM provider and credentials.",
            ),
        ),
        "telegram_bridge": CapabilityAssessment(
            name="telegram_bridge",
            label="Telegram bridge",
            available=providers["telegram"].ready,
            optional=False,
            reasons=_reasons_for_capability(
                providers["telegram"].ready,
                "Set TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_CHAT_ID.",
            ),
        ),
        "broker_read": CapabilityAssessment(
            name="broker_read",
            label="Broker read",
            available=providers["broker"].ready,
            optional=True,
            reasons=_reasons_for_capability(
                providers["broker"].ready,
                "Configure BROKER_PROVIDER=trading212 plus T212 credentials.",
            ),
        ),
        "broker_execution_eligibility": CapabilityAssessment(
            name="broker_execution_eligibility",
            label="Broker execution eligibility",
            available=_broker_execution_available(settings, providers["broker"]),
            optional=True,
            reasons=_broker_execution_reasons(settings, providers["broker"]),
        ),
        "market_data": CapabilityAssessment(
            name="market_data",
            label="Market data",
            available=providers["yahoo"].ready or providers["alpha_vantage"].ready,
            optional=True,
            reasons=_reasons_for_capability(
                providers["yahoo"].ready or providers["alpha_vantage"].ready,
                "Enable Yahoo and/or Alpha Vantage for market context.",
            ),
        ),
        "research_community_context": CapabilityAssessment(
            name="research_community_context",
            label="Research/community context",
            available=providers["reddit"].ready,
            optional=True,
            reasons=_reasons_for_capability(
                providers["reddit"].ready,
                "Enable Reddit to add community discussion context.",
            ),
        ),
        "search": CapabilityAssessment(
            name="search",
            label="Search",
            available=providers["searxng"].ready,
            optional=True,
            reasons=_reasons_for_capability(
                providers["searxng"].ready,
                "Enable SearXNG and set SEARXNG_BASE_URL.",
            ),
        ),
        "persistent_guideline_memory": CapabilityAssessment(
            name="persistent_guideline_memory",
            label="Persistent guideline memory",
            available=bool(str(settings.guideline_memory_path or "").strip()),
            optional=True,
            reasons=_reasons_for_capability(
                bool(str(settings.guideline_memory_path or "").strip()),
                "Set GUIDELINE_MEMORY_PATH to a writable JSON path.",
            ),
        ),
    }

    errors = _unique_messages(
        message
        for provider in providers.values()
        for message in provider.errors
    )
    warnings = _unique_messages(
        message
        for provider in providers.values()
        for message in provider.warnings
    )
    return ConfigAssessment(
        providers=providers,
        capabilities=capabilities,
        configuration_errors=errors,
        warnings=warnings,
    )


def preflight_run_bot(assessment: ConfigAssessment) -> StartupPreflight:
    errors = list(assessment.configuration_errors)
    if not assessment.capabilities["llm_reasoning"].available:
        errors.append(
            "Run bot requires LLM reasoning. Configure LLM_PROVIDER and the required credentials."
        )
    if not assessment.capabilities["telegram_bridge"].available:
        errors.append(
            "Run bot requires Telegram bridge credentials. Set TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_CHAT_ID."
        )
    return StartupPreflight(
        ok=not errors,
        blocking_errors=_unique_messages(errors),
        warnings=assessment.warnings,
    )


def preflight_reconcile(
    assessment: ConfigAssessment,
    settings: AppSettings,
) -> StartupPreflight:
    errors: list[str] = []
    broker = assessment.providers["broker"]
    if broker.enabled and broker.errors:
        errors.extend(broker.errors)
    if not assessment.capabilities["broker_read"].available:
        errors.append(
            "Reconciliation requires broker read access. Configure BROKER_PROVIDER=trading212 and valid Trading 212 credentials."
        )
    if not bool(str(settings.database_url or "").strip()):
        errors.append("Reconciliation requires DATABASE_URL.")
    return StartupPreflight(
        ok=not errors,
        blocking_errors=_unique_messages(errors),
        warnings=assessment.warnings,
    )


def ensure_runtime_directories(settings: AppSettings) -> tuple[Path, ...]:
    directories = {
        Path("data"),
        Path(settings.guideline_memory_path).expanduser().parent,
    }
    sqlite_path = _sqlite_local_path(settings.database_url)
    if sqlite_path is not None:
        directories.add(sqlite_path.parent)
    resolved = tuple(sorted(directories, key=lambda item: str(item)))
    for directory in resolved:
        directory.mkdir(parents=True, exist_ok=True)
    return resolved


def _assess_llm_provider(settings: AppSettings) -> ProviderAssessment:
    provider = str(settings.llm_provider or "none").strip().lower()
    if provider not in VALID_LLM_PROVIDERS:
        return ProviderAssessment(
            name="llm",
            label="LLM provider",
            enabled=True,
            optional=False,
            configured=True,
            ready=False,
            errors=(f"LLM_PROVIDER has unsupported value '{settings.llm_provider}'.",),
        )
    if provider == "none":
        return ProviderAssessment(
            name="llm",
            label="LLM provider",
            enabled=False,
            optional=False,
            configured=False,
            ready=False,
            notes=("LLM provider is disabled.",),
        )
    if provider == "openai":
        missing = _missing_keys({"OPENAI_API_KEY": settings.openai_api_key})
        return ProviderAssessment(
            name="llm",
            label="OpenAI",
            enabled=True,
            optional=False,
            configured=bool(settings.openai_api_key),
            ready=not missing,
            required_keys=("OPENAI_API_KEY",),
            missing_keys=missing,
            errors=_provider_errors("OpenAI", missing),
        )
    missing = _missing_keys(
        {
            "AZURE_OPENAI_ENDPOINT": settings.azure_openai_endpoint,
            "AZURE_OPENAI_API_KEY": settings.azure_openai_api_key,
        }
    )
    return ProviderAssessment(
        name="llm",
        label="Azure OpenAI",
        enabled=True,
        optional=False,
        configured=bool(settings.azure_openai_endpoint or settings.azure_openai_api_key),
        ready=not missing,
        required_keys=("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY"),
        missing_keys=missing,
        errors=_provider_errors("Azure OpenAI", missing),
        notes=("AZURE_OPENAI_ENABLED should be true for Azure runtime mode.",),
    )


def _assess_broker_provider(settings: AppSettings) -> ProviderAssessment:
    provider = str(settings.broker_provider or "none").strip().lower()
    if provider not in VALID_BROKER_PROVIDERS:
        return ProviderAssessment(
            name="broker",
            label="Broker provider",
            enabled=True,
            optional=True,
            configured=True,
            ready=False,
            errors=(f"BROKER_PROVIDER has unsupported value '{settings.broker_provider}'.",),
        )
    if provider == "none":
        return ProviderAssessment(
            name="broker",
            label="Broker provider",
            enabled=False,
            optional=True,
            configured=False,
            ready=False,
            notes=("Broker provider is disabled.",),
        )
    missing = _missing_keys(
        {
            "T212_API_KEY": settings.trading212_api_key,
            "T212_API_SECRET": settings.trading212_api_secret,
        }
    )
    notes = (
        f"Trading 212 environment: {settings.trading212_environment}.",
        f"Live trading enabled: {settings.live_trading_enabled}.",
    )
    return ProviderAssessment(
        name="broker",
        label="Trading 212",
        enabled=True,
        optional=True,
        configured=bool(settings.trading212_api_key or settings.trading212_api_secret),
        ready=not missing,
        required_keys=("T212_API_KEY", "T212_API_SECRET"),
        missing_keys=missing,
        errors=_provider_errors("Trading 212", missing),
        notes=notes,
    )


def _assess_telegram_provider(settings: AppSettings) -> ProviderAssessment:
    has_token = bool(str(settings.telegram_bot_token or "").strip())
    has_chat = bool(str(settings.telegram_allowed_chat_id or "").strip())
    enabled = has_token or has_chat
    missing = tuple(
        key
        for key, present in (
            ("TELEGRAM_BOT_TOKEN", has_token),
            ("TELEGRAM_ALLOWED_CHAT_ID", has_chat),
        )
        if not present
    )
    errors = ()
    if enabled and missing:
        errors = (
            "Telegram is partially configured. Missing: " + ", ".join(missing) + ".",
        )
    notes = ()
    if not enabled:
        notes = ("Telegram integration is not configured.",)
    return ProviderAssessment(
        name="telegram",
        label="Telegram",
        enabled=enabled,
        optional=False,
        configured=has_token and has_chat,
        ready=has_token and has_chat,
        required_keys=("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_CHAT_ID"),
        missing_keys=missing,
        errors=errors,
        notes=notes,
    )


def _assess_yahoo_provider(settings: AppSettings) -> ProviderAssessment:
    return ProviderAssessment(
        name="yahoo",
        label="Yahoo Finance",
        enabled=settings.yahoo_enabled,
        optional=True,
        configured=settings.yahoo_enabled,
        ready=settings.yahoo_enabled,
        notes=("Yahoo is best-effort and mostly no-auth.",) if settings.yahoo_enabled else (),
    )


def _assess_alpha_vantage_provider(settings: AppSettings) -> ProviderAssessment:
    missing = _missing_keys({"ALPHA_VANTAGE_API_KEY": settings.alpha_vantage_api_key})
    enabled = settings.alpha_vantage_enabled
    return ProviderAssessment(
        name="alpha_vantage",
        label="Alpha Vantage",
        enabled=enabled,
        optional=True,
        configured=bool(settings.alpha_vantage_api_key),
        ready=enabled and not missing,
        required_keys=("ALPHA_VANTAGE_API_KEY",),
        missing_keys=missing if enabled else (),
        errors=_provider_errors("Alpha Vantage", missing) if enabled else (),
    )


def _assess_reddit_provider(settings: AppSettings) -> ProviderAssessment:
    enabled = settings.reddit_enabled
    missing = []
    if enabled and not str(settings.reddit_client_id or "").strip():
        missing.append("REDDIT_CLIENT_ID")
    if enabled and not str(settings.reddit_client_secret or "").strip():
        missing.append("REDDIT_CLIENT_SECRET")
    if enabled and not str(settings.reddit_user_agent or "").strip():
        missing.append("REDDIT_USER_AGENT")
    has_refresh = bool(str(settings.reddit_refresh_token or "").strip())
    has_user_pass = bool(str(settings.reddit_username or "").strip()) and bool(
        str(settings.reddit_password or "").strip()
    )
    if enabled and not (has_refresh or has_user_pass):
        missing.append("REDDIT_REFRESH_TOKEN or REDDIT_USERNAME + REDDIT_PASSWORD")
    return ProviderAssessment(
        name="reddit",
        label="Reddit",
        enabled=enabled,
        optional=True,
        configured=bool(
            settings.reddit_client_id
            or settings.reddit_client_secret
            or settings.reddit_refresh_token
            or settings.reddit_username
            or settings.reddit_password
        ),
        ready=enabled and not missing,
        required_keys=(
            "REDDIT_CLIENT_ID",
            "REDDIT_CLIENT_SECRET",
            "REDDIT_USER_AGENT",
            "REDDIT_REFRESH_TOKEN or REDDIT_USERNAME + REDDIT_PASSWORD",
        ),
        missing_keys=tuple(missing),
        errors=_provider_errors("Reddit", tuple(missing)) if enabled else (),
    )


def _assess_searxng_provider(settings: AppSettings) -> ProviderAssessment:
    missing = _missing_keys({"SEARXNG_BASE_URL": settings.searxng_base_url})
    enabled = settings.searxng_enabled
    return ProviderAssessment(
        name="searxng",
        label="SearXNG",
        enabled=enabled,
        optional=True,
        configured=bool(settings.searxng_base_url),
        ready=enabled and not missing,
        required_keys=("SEARXNG_BASE_URL",),
        missing_keys=missing if enabled else (),
        errors=_provider_errors("SearXNG", missing) if enabled else (),
    )


def _broker_execution_available(
    settings: AppSettings,
    broker: ProviderAssessment,
) -> bool:
    if not broker.ready:
        return False
    if str(settings.trading212_environment or "").strip().lower() != "live":
        return True
    return settings.live_trading_enabled


def _broker_execution_reasons(
    settings: AppSettings,
    broker: ProviderAssessment,
) -> tuple[str, ...]:
    if not broker.ready:
        return ("Broker credentials are not ready for execution.",)
    if str(settings.trading212_environment or "").strip().lower() != "live":
        return ()
    if settings.live_trading_enabled:
        return ()
    return (
        "Trading 212 is set to live environment, but T212_LIVE_TRADING_ENABLED is false.",
    )


def _reasons_for_capability(available: bool, reason: str) -> tuple[str, ...]:
    return () if available else (reason,)


def _provider_errors(label: str, missing: tuple[str, ...]) -> tuple[str, ...]:
    if not missing:
        return ()
    return (f"{label} is missing required settings: {', '.join(missing)}.",)


def _missing_keys(values: dict[str, str | None]) -> tuple[str, ...]:
    return tuple(
        key for key, value in values.items() if not bool(str(value or "").strip())
    )


def _unique_messages(messages: list[str] | tuple[str, ...] | object) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for message in messages:
        normalized = str(message).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return tuple(ordered)


def _sqlite_local_path(database_url: str) -> Path | None:
    raw = str(database_url or "").strip()
    prefix = "sqlite:///"
    if not raw.startswith(prefix):
        return None
    local_path = raw.removeprefix(prefix).strip()
    if not local_path or local_path == ":memory:":
        return None
    return Path(local_path).expanduser()
