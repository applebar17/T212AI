"""Bootstrap assessment data models and provider selector constants."""

from __future__ import annotations

from dataclasses import dataclass




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


