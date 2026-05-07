from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import AppSettings


VALID_LLM_PROVIDERS = frozenset({"openai", "azure_openai", "none"})
VALID_BROKER_PROVIDERS = frozenset({"trading212", "alpaca", "none"})
VALID_MARKET_DATA_PROVIDERS = frozenset({"yahoo", "alpaca", "none"})
VALID_MARKET_INTELLIGENCE_PROVIDERS = frozenset({"alpha_vantage", "none"})
VALID_DISCLOSURE_PROVIDERS = frozenset({"sec_edgar", "none"})
VALID_COMMUNITY_PROVIDERS = frozenset({"reddit", "none"})
VALID_SEARCH_PROVIDERS = frozenset({"searxng", "none"})


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
    selected_provider: str | None = None
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


@dataclass(frozen=True, slots=True)
class ProviderSmokeResult:
    name: str
    label: str
    status: str
    message: str
    warnings: tuple[str, ...] = ()


def assess_settings(settings: AppSettings) -> ConfigAssessment:
    providers = {
        "llm": _assess_llm_provider(settings),
        "broker": _assess_broker_provider(settings),
        "telegram": _assess_telegram_provider(settings),
        "yahoo": _assess_yahoo_provider(settings),
        "alpaca": _assess_alpaca_provider(settings),
        "alpha_vantage": _assess_alpha_vantage_provider(settings),
        "reddit": _assess_reddit_provider(settings),
        "searxng": _assess_searxng_provider(settings),
        "sec_edgar": _assess_sec_edgar_provider(settings),
    }
    selector_errors = _validate_selector_values(settings)
    market_data_capability = _build_market_data_capability(settings, providers)
    capabilities = {
        "llm_reasoning": CapabilityAssessment(
            name="llm_reasoning",
            label="LLM reasoning",
            available=providers["llm"].ready,
            optional=False,
            selected_provider=settings.llm_provider if settings.llm_provider != "none" else None,
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
            selected_provider="telegram" if providers["telegram"].enabled else None,
            reasons=_reasons_for_capability(
                providers["telegram"].ready,
                "Set TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_CHAT_ID.",
            ),
        ),
        "broker_read": CapabilityAssessment(
            name="broker_read",
            label="Broker read",
            available=providers["broker"].ready
            and settings.broker_provider in VALID_BROKER_PROVIDERS,
            optional=True,
            selected_provider=(
                settings.broker_provider if settings.broker_provider != "none" else None
            ),
            reasons=_broker_read_reasons(settings, providers["broker"]),
        ),
        "broker_execution_eligibility": CapabilityAssessment(
            name="broker_execution_eligibility",
            label="Broker execution eligibility",
            available=_broker_execution_available(settings, providers["broker"]),
            optional=True,
            selected_provider=(
                settings.broker_provider if settings.broker_provider != "none" else None
            ),
            reasons=_broker_execution_reasons(settings, providers["broker"]),
        ),
        "market_data": market_data_capability,
        "market_intelligence": _build_market_intelligence_capability(settings, providers),
        "disclosure": _build_disclosure_capability(settings, providers),
        "research_community_context": CapabilityAssessment(
            name="research_community_context",
            label="Research/community context",
            available=providers["reddit"].ready
            and settings.community_provider in VALID_COMMUNITY_PROVIDERS,
            optional=True,
            selected_provider=(
                settings.community_provider
                if settings.community_provider != "none"
                else None
            ),
            reasons=_community_reasons(settings, providers["reddit"]),
        ),
        "search": CapabilityAssessment(
            name="search",
            label="Search",
            available=providers["searxng"].ready
            and settings.search_provider in VALID_SEARCH_PROVIDERS,
            optional=True,
            selected_provider=(
                settings.search_provider if settings.search_provider != "none" else None
            ),
            reasons=_search_reasons(settings, providers["searxng"]),
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
        "market_signal_memory": CapabilityAssessment(
            name="market_signal_memory",
            label="Market signal memory",
            available=bool(str(settings.database_url or "").strip()),
            optional=True,
            selected_provider="sql" if str(settings.database_url or "").strip() else None,
            reasons=_reasons_for_capability(
                bool(str(settings.database_url or "").strip()),
                "Set DATABASE_URL to enable SQL-backed market signal memory.",
            ),
        ),
        "scheduled_processes": CapabilityAssessment(
            name="scheduled_processes",
            label="Scheduled processes",
            available=bool(str(settings.database_url or "").strip()),
            optional=True,
            selected_provider="sql" if str(settings.database_url or "").strip() else None,
            reasons=_reasons_for_capability(
                bool(str(settings.database_url or "").strip()),
                "Set DATABASE_URL to enable SQL-backed scheduled processes.",
            ),
        ),
        "scheduler_notifications": CapabilityAssessment(
            name="scheduler_notifications",
            label="Scheduler notifications",
            available=bool(str(settings.database_url or "").strip())
            and providers["telegram"].ready,
            optional=True,
            selected_provider="telegram" if providers["telegram"].ready else None,
            reasons=_scheduler_notification_reasons(settings, providers["telegram"]),
        ),
        "scheduler_instrument_monitor": CapabilityAssessment(
            name="scheduler_instrument_monitor",
            label="Scheduler instrument monitor",
            available=bool(str(settings.database_url or "").strip())
            and market_data_capability.available,
            optional=True,
            selected_provider=market_data_capability.selected_provider,
            reasons=_scheduler_instrument_monitor_reasons(settings, market_data_capability),
        ),
        "scheduler_delegate": CapabilityAssessment(
            name="scheduler_delegate",
            label="Scheduler delegate",
            available=providers["llm"].ready
            and bool(str(settings.database_url or "").strip()),
            optional=True,
            selected_provider=(
                "llm+sql"
                if providers["llm"].ready and bool(str(settings.database_url or "").strip())
                else None
            ),
            reasons=_scheduler_delegate_reasons(settings, providers["llm"]),
        ),
        "scheduler_company_event_analyst": CapabilityAssessment(
            name="scheduler_company_event_analyst",
            label="Scheduler company event analyst",
            available=providers["llm"].ready
            and bool(str(settings.database_url or "").strip()),
            optional=True,
            selected_provider=(
                "llm+sql"
                if providers["llm"].ready and bool(str(settings.database_url or "").strip())
                else None
            ),
            reasons=_scheduler_delegate_reasons(settings, providers["llm"]),
        ),
    }

    errors = _unique_messages(
        message
        for provider in providers.values()
        for message in provider.errors
    )
    errors = _unique_messages([*errors, *selector_errors])
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
            "Reconciliation requires broker read access. Configure BROKER_PROVIDER plus valid credentials for the selected broker."
        )
    if not bool(str(settings.database_url or "").strip()):
        errors.append("Reconciliation requires DATABASE_URL.")
    return StartupPreflight(
        ok=not errors,
        blocking_errors=_unique_messages(errors),
        warnings=assessment.warnings,
    )


def preflight_scheduler(
    assessment: ConfigAssessment,
    settings: AppSettings,
) -> StartupPreflight:
    errors: list[str] = []
    if not bool(str(settings.database_url or "").strip()):
        errors.append("Scheduler requires DATABASE_URL.")
    return StartupPreflight(
        ok=not errors,
        blocking_errors=_unique_messages(errors),
        warnings=assessment.warnings,
    )


def _scheduler_notification_reasons(
    settings: AppSettings,
    telegram: ProviderAssessment,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not bool(str(settings.database_url or "").strip()):
        reasons.append("Set DATABASE_URL to enable SQL-backed scheduler notification audit.")
    if not telegram.ready:
        reasons.append(
            "Set TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_CHAT_ID to enable scheduler Telegram notifications."
        )
    return tuple(reasons)


def _scheduler_instrument_monitor_reasons(
    settings: AppSettings,
    market_data: CapabilityAssessment,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not bool(str(settings.database_url or "").strip()):
        reasons.append("Set DATABASE_URL to enable SQL-backed scheduled processes.")
    if not market_data.available:
        reasons.append("Configure MARKET_DATA_PROVIDER to enable scheduler instrument monitors.")
    return tuple(reasons)


def _scheduler_delegate_reasons(
    settings: AppSettings,
    llm: ProviderAssessment,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not llm.ready:
        reasons.append("Configure LLM reasoning to enable natural-language scheduling.")
    if not bool(str(settings.database_url or "").strip()):
        reasons.append("Set DATABASE_URL to enable SQL-backed scheduled processes.")
    return tuple(reasons)


def ensure_runtime_directories(settings: AppSettings) -> tuple[Path, ...]:
    directories = {
        Path("data"),
        Path(settings.guideline_memory_path).expanduser().parent,
        Path(settings.app_log_file_path).expanduser().parent,
    }
    sqlite_path = _sqlite_local_path(settings.database_url)
    if sqlite_path is not None:
        directories.add(sqlite_path.parent)
    resolved = tuple(sorted(directories, key=lambda item: str(item)))
    for directory in resolved:
        directory.mkdir(parents=True, exist_ok=True)
    return resolved


def run_provider_smoke_tests(
    settings: AppSettings,
    assessment: ConfigAssessment,
) -> dict[str, ProviderSmokeResult]:
    results: dict[str, ProviderSmokeResult] = {}
    for name, provider in assessment.providers.items():
        if not provider.enabled:
            continue
        if not provider.ready:
            results[name] = ProviderSmokeResult(
                name=name,
                label=provider.label,
                status="invalid",
                message="Structural readiness failed.",
                warnings=provider.errors,
            )
            continue
        probe = _PROVIDER_SMOKE_PROBES.get(name)
        if probe is None:
            results[name] = ProviderSmokeResult(
                name=name,
                label=provider.label,
                status="ready",
                message="Structural readiness passed. Live probe not implemented.",
            )
            continue
        try:
            probe(settings)
        except Exception as exc:
            results[name] = ProviderSmokeResult(
                name=name,
                label=provider.label,
                status="warning",
                message="Structural readiness passed, but the live smoke probe failed.",
                warnings=(str(exc),),
            )
            continue
        results[name] = ProviderSmokeResult(
            name=name,
            label=provider.label,
            status="ready",
            message="Structural readiness and live smoke probe passed.",
        )
    return results


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
    if provider == "trading212":
        api_key_name, api_secret_name = settings.trading212_active_credential_keys
        missing = _missing_keys(
            {
                api_key_name: settings.trading212_api_key,
                api_secret_name: settings.trading212_api_secret,
            }
        )
        notes = (
            f"Trading 212 environment: {settings.trading212_environment}.",
            f"Live trading enabled: {settings.live_trading_enabled}.",
            "Legacy fallback vars T212_API_KEY and T212_API_SECRET remain supported.",
        )
        return ProviderAssessment(
            name="broker",
            label="Trading 212 broker",
            enabled=True,
            optional=True,
            configured=bool(settings.trading212_api_key or settings.trading212_api_secret),
            ready=not missing,
            required_keys=(api_key_name, api_secret_name),
            missing_keys=missing,
            errors=_provider_errors("Trading 212", missing),
            notes=notes,
        )
    api_key_name, api_secret_name = settings.alpaca_active_credential_keys
    missing = _missing_keys(
        {
            api_key_name: settings.alpaca_api_key,
            api_secret_name: settings.alpaca_api_secret,
        }
    )
    return ProviderAssessment(
        name="broker",
        label="Alpaca broker",
        enabled=True,
        optional=True,
        configured=bool(settings.alpaca_api_key or settings.alpaca_api_secret),
        ready=not missing,
        required_keys=(api_key_name, api_secret_name),
        missing_keys=missing,
        errors=_provider_errors("Alpaca broker", missing),
        notes=(
            f"Alpaca environment: {settings.alpaca_environment}.",
            "Legacy fallback vars ALPACA_API_KEY and ALPACA_API_SECRET remain supported.",
        ),
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
        enabled=settings.market_data_provider == "yahoo",
        optional=True,
        configured=settings.market_data_provider == "yahoo",
        ready=settings.market_data_provider == "yahoo",
        notes=(
            "Yahoo is best-effort, mostly no-auth, and the default market-data baseline.",
        )
        if settings.market_data_provider == "yahoo"
        else (),
    )


def _assess_alpaca_provider(settings: AppSettings) -> ProviderAssessment:
    enabled = settings.market_data_provider == "alpaca"
    api_key_name, api_secret_name = settings.alpaca_active_credential_keys
    missing = _missing_keys(
        {
            api_key_name: settings.alpaca_api_key,
            api_secret_name: settings.alpaca_api_secret,
        }
    )
    return ProviderAssessment(
        name="alpaca",
        label="Alpaca",
        enabled=enabled,
        optional=True,
        configured=enabled and bool(settings.alpaca_api_key or settings.alpaca_api_secret),
        ready=enabled and not missing,
        required_keys=(api_key_name, api_secret_name),
        missing_keys=missing if enabled else (),
        errors=_provider_errors("Alpaca", missing) if enabled else (),
        notes=(
            f"Alpaca environment: {settings.alpaca_environment}.",
            f"Alpaca market-data feed: {settings.alpaca_data_feed}.",
            "Legacy fallback vars ALPACA_API_KEY and ALPACA_API_SECRET remain supported.",
        )
        if enabled
        else ("Alpaca market data is disabled.",),
    )


def _assess_alpha_vantage_provider(settings: AppSettings) -> ProviderAssessment:
    missing = _missing_keys({"ALPHA_VANTAGE_API_KEY": settings.alpha_vantage_api_key})
    enabled = settings.market_intelligence_provider == "alpha_vantage"
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
    enabled = settings.community_provider == "reddit"
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
    enabled = settings.search_provider == "searxng"
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


def _assess_sec_edgar_provider(settings: AppSettings) -> ProviderAssessment:
    enabled = settings.disclosure_provider == "sec_edgar"
    notes = (
        "SEC EDGAR is the default disclosure provider and uses free public filings data.",
    )
    if not enabled:
        return ProviderAssessment(
            name="sec_edgar",
            label="SEC EDGAR",
            enabled=False,
            optional=True,
            configured=False,
            ready=False,
            notes=("SEC EDGAR disclosure integration is disabled.",),
        )
    return ProviderAssessment(
        name="sec_edgar",
        label="SEC EDGAR",
        enabled=True,
        optional=True,
        configured=True,
        ready=True,
        notes=notes,
    )


def _broker_execution_available(
    settings: AppSettings,
    broker: ProviderAssessment,
) -> bool:
    if not broker.ready:
        return False
    if str(settings.broker_provider or "").strip().lower() == "alpaca":
        return True
    if str(settings.trading212_environment or "").strip().lower() != "live":
        return True
    return settings.live_trading_enabled


def _broker_execution_reasons(
    settings: AppSettings,
    broker: ProviderAssessment,
) -> tuple[str, ...]:
    if not broker.ready:
        return ("Broker credentials are not ready for execution.",)
    if str(settings.broker_provider or "").strip().lower() == "alpaca":
        return ()
    if str(settings.trading212_environment or "").strip().lower() != "live":
        return ()
    if settings.live_trading_enabled:
        return ()
    return (
        "Trading 212 is set to live environment, but T212_LIVE_TRADING_ENABLED is false.",
    )


def _broker_read_reasons(
    settings: AppSettings,
    provider: ProviderAssessment,
) -> tuple[str, ...]:
    if settings.broker_provider not in VALID_BROKER_PROVIDERS:
        return (
            f"BROKER_PROVIDER has unsupported value '{settings.broker_provider}'.",
        )
    if settings.broker_provider == "none":
        return ("Broker provider is disabled.",)
    return _reasons_for_capability(
        provider.ready,
        "Configure BROKER_PROVIDER and valid credentials for the selected broker.",
    )


def _build_market_data_capability(
    settings: AppSettings,
    providers: dict[str, ProviderAssessment],
) -> CapabilityAssessment:
    selected = str(settings.market_data_provider or "").strip().lower()
    if selected not in VALID_MARKET_DATA_PROVIDERS:
        return CapabilityAssessment(
            name="market_data",
            label="Market data",
            available=False,
            optional=True,
            reasons=(f"MARKET_DATA_PROVIDER has unsupported value '{settings.market_data_provider}'.",),
        )
    if selected == "none":
        return CapabilityAssessment(
            name="market_data",
            label="Market data",
            available=False,
            optional=True,
            reasons=("Market data provider is disabled.",),
        )
    provider_key = "alpaca" if selected == "alpaca" else "yahoo"
    provider = providers[provider_key]
    return CapabilityAssessment(
        name="market_data",
        label="Market data",
        available=provider.ready,
        optional=True,
        selected_provider=selected,
        reasons=_reasons_for_capability(
            provider.ready,
            (
                "Configure Alpaca market data credentials or select a different market-data provider."
                if selected == "alpaca"
                else "Enable Yahoo market data or set MARKET_DATA_PROVIDER=none."
            ),
        ),
    )


def _build_market_intelligence_capability(
    settings: AppSettings,
    providers: dict[str, ProviderAssessment],
) -> CapabilityAssessment:
    selected = str(settings.market_intelligence_provider or "").strip().lower()
    if selected not in VALID_MARKET_INTELLIGENCE_PROVIDERS:
        return CapabilityAssessment(
            name="market_intelligence",
            label="Market intelligence",
            available=False,
            optional=True,
            reasons=(
                f"MARKET_INTELLIGENCE_PROVIDER has unsupported value '{settings.market_intelligence_provider}'.",
            ),
        )
    if selected == "none":
        return CapabilityAssessment(
            name="market_intelligence",
            label="Market intelligence",
            available=False,
            optional=True,
            reasons=("Market intelligence provider is disabled.",),
        )
    provider = providers["alpha_vantage"]
    return CapabilityAssessment(
        name="market_intelligence",
        label="Market intelligence",
        available=provider.ready,
        optional=True,
        selected_provider="alpha_vantage",
        reasons=_reasons_for_capability(
            provider.ready,
            "Configure Alpha Vantage credentials or disable market intelligence.",
        ),
    )


def _build_disclosure_capability(
    settings: AppSettings,
    providers: dict[str, ProviderAssessment],
) -> CapabilityAssessment:
    selected = str(settings.disclosure_provider or "").strip().lower()
    if selected not in VALID_DISCLOSURE_PROVIDERS:
        return CapabilityAssessment(
            name="disclosure",
            label="Disclosure",
            available=False,
            optional=True,
            reasons=(
                f"DISCLOSURE_PROVIDER has unsupported value '{settings.disclosure_provider}'.",
            ),
        )
    if selected == "none":
        return CapabilityAssessment(
            name="disclosure",
            label="Disclosure",
            available=False,
            optional=True,
            reasons=("Disclosure provider is disabled.",),
        )
    provider = providers["sec_edgar"]
    return CapabilityAssessment(
        name="disclosure",
        label="Disclosure",
        available=provider.ready,
        optional=True,
        selected_provider="sec_edgar",
        reasons=_reasons_for_capability(
            provider.ready,
            "Enable SEC EDGAR disclosure integration or set DISCLOSURE_PROVIDER=none.",
        ),
    )


def _community_reasons(
    settings: AppSettings,
    provider: ProviderAssessment,
) -> tuple[str, ...]:
    selected = str(settings.community_provider or "").strip().lower()
    if selected not in VALID_COMMUNITY_PROVIDERS:
        return (
            f"COMMUNITY_PROVIDER has unsupported value '{settings.community_provider}'.",
        )
    if selected == "none":
        return ("Community provider is disabled.",)
    return _reasons_for_capability(
        provider.ready,
        "Enable Reddit to add community discussion context.",
    )


def _search_reasons(
    settings: AppSettings,
    provider: ProviderAssessment,
) -> tuple[str, ...]:
    selected = str(settings.search_provider or "").strip().lower()
    if selected not in VALID_SEARCH_PROVIDERS:
        return (
            f"SEARCH_PROVIDER has unsupported value '{settings.search_provider}'.",
        )
    if selected == "none":
        return ("Search provider is disabled.",)
    return _reasons_for_capability(
        provider.ready,
        "Enable SearXNG and set SEARXNG_BASE_URL.",
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


def _validate_selector_values(settings: AppSettings) -> tuple[str, ...]:
    errors: list[str] = []
    errors.extend(
        _selector_error(
            "MARKET_DATA_PROVIDER",
            settings.market_data_provider,
            VALID_MARKET_DATA_PROVIDERS,
        )
    )
    errors.extend(
        _selector_error(
            "MARKET_INTELLIGENCE_PROVIDER",
            settings.market_intelligence_provider,
            VALID_MARKET_INTELLIGENCE_PROVIDERS,
        )
    )
    errors.extend(
        _selector_error(
            "DISCLOSURE_PROVIDER",
            settings.disclosure_provider,
            VALID_DISCLOSURE_PROVIDERS,
        )
    )
    errors.extend(
        _selector_error(
            "COMMUNITY_PROVIDER",
            settings.community_provider,
            VALID_COMMUNITY_PROVIDERS,
        )
    )
    errors.extend(
        _selector_error(
            "SEARCH_PROVIDER",
            settings.search_provider,
            VALID_SEARCH_PROVIDERS,
        )
    )
    return _unique_messages(errors)


def _selector_error(
    name: str,
    value: str,
    allowed: frozenset[str],
) -> tuple[str, ...]:
    resolved = str(value or "").strip().lower()
    if resolved in allowed:
        return ()
    return (f"{name} has unsupported value '{value}'.",)


def _smoke_probe_broker(settings: AppSettings) -> None:
    provider = str(settings.broker_provider or "").strip().lower()
    if provider == "trading212":
        from t212ai.brokers.trading212 import Trading212Client

        Trading212Client.from_settings(settings).get_account_summary()
        return
    if provider == "alpaca":
        from t212ai.alpaca import AlpacaBrokerClient

        AlpacaBrokerClient.from_settings(settings).get_account()
        return
    raise RuntimeError("Broker provider is not configured for smoke testing.")


def _smoke_probe_yahoo(_settings: AppSettings) -> None:
    from t212ai.data_sources.yahoo import YahooFinanceClient

    YahooFinanceClient().get_quote_snapshot(["AAPL"])


def _smoke_probe_alpaca(settings: AppSettings) -> None:
    from t212ai.alpaca import AlpacaMarketDataClient

    AlpacaMarketDataClient.from_settings(settings).get_quote_snapshot(["AAPL"])


def _smoke_probe_alpha_vantage(settings: AppSettings) -> None:
    from t212ai.data_sources.alpha_vantage import AlphaVantageClient

    AlphaVantageClient.from_settings(settings).market_status()


def _smoke_probe_reddit(settings: AppSettings) -> None:
    from t212ai.data_sources.reddit import RedditClient

    RedditClient.from_settings(settings).subreddit_about("investing")


def _smoke_probe_searxng(settings: AppSettings) -> None:
    from t212ai.genai.tools.searxng import searxng_search

    result = searxng_search(
        query="market",
        base_url=settings.searxng_base_url,
        max_results=1,
    )
    if result.status != "ok":
        message = result.error.message if result.error is not None else "SearXNG probe failed."
        raise RuntimeError(message)


def _smoke_probe_sec_edgar(settings: AppSettings) -> None:
    from t212ai.data_sources.sec_edgar import SecEdgarClient

    SecEdgarClient.from_settings(settings).get_company_tickers()


_PROVIDER_SMOKE_PROBES = {
    "broker": _smoke_probe_broker,
    "yahoo": _smoke_probe_yahoo,
    "alpaca": _smoke_probe_alpaca,
    "alpha_vantage": _smoke_probe_alpha_vantage,
    "reddit": _smoke_probe_reddit,
    "searxng": _smoke_probe_searxng,
    "sec_edgar": _smoke_probe_sec_edgar,
}


def _sqlite_local_path(database_url: str) -> Path | None:
    raw = str(database_url or "").strip()
    prefix = "sqlite:///"
    if not raw.startswith(prefix):
        return None
    local_path = raw.removeprefix(prefix).strip()
    if not local_path or local_path == ":memory:":
        return None
    return Path(local_path).expanduser()
