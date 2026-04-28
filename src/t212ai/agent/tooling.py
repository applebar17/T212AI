"""Runtime-aware specialist toolbox and summary assembly."""

from __future__ import annotations

from dataclasses import dataclass

from t212ai.app.bootstrap import ConfigAssessment
from t212ai.app.config import AppSettings
from t212ai.brokers.trading212 import T212_ORDER_ACTION_TOOLBOX
from t212ai.genai.tools import build_market_analyst_toolbox, build_toolboxes
from t212ai.genai.tools.base import ToolBox


@dataclass(frozen=True, slots=True)
class SpecialistTooling:
    portfolio_toolbox_summary: str
    order_toolbox: ToolBox | None
    order_toolbox_summary: str
    market_toolbox: ToolBox
    market_toolbox_summary: str
    company_toolbox_summary: str


def build_specialist_tooling(
    *,
    settings: AppSettings,
    assessment: ConfigAssessment,
) -> SpecialistTooling:
    toolboxes = build_toolboxes(settings=settings, assessment=assessment)
    market_toolbox = build_market_analyst_toolbox(
        settings=settings,
        assessment=assessment,
    )
    return SpecialistTooling(
        portfolio_toolbox_summary=_portfolio_summary(settings, assessment),
        order_toolbox=(
            T212_ORDER_ACTION_TOOLBOX
            if _provider_ready(assessment, "broker")
            and settings.broker_provider == "trading212"
            else None
        ),
        order_toolbox_summary=_order_summary(settings, assessment),
        market_toolbox=market_toolbox,
        market_toolbox_summary=_market_summary(market_toolbox),
        company_toolbox_summary=_company_summary(settings, assessment, toolboxes),
    )


def _portfolio_summary(
    settings: AppSettings,
    assessment: ConfigAssessment,
) -> str:
    facts = ["Portfolio snapshot, positions, pending orders"]
    if settings.market_data_provider == "yahoo" and _provider_ready(assessment, "yahoo"):
        facts.append("market data context")
    if (
        settings.market_intelligence_provider == "alpha_vantage"
        and _provider_ready(assessment, "alpha_vantage")
    ):
        facts.append("Alpha Vantage intelligence")
    if settings.disclosure_provider == "sec_edgar" and _provider_ready(assessment, "sec_edgar"):
        facts.append("SEC EDGAR disclosure context")
    if settings.search_provider == "searxng" and _provider_ready(assessment, "searxng"):
        facts.append("web search when needed")
    return ", ".join(facts) + "."


def _order_summary(
    settings: AppSettings,
    assessment: ConfigAssessment,
) -> str:
    if settings.broker_provider == "trading212" and _provider_ready(assessment, "broker"):
        return (
            "Trading 212 pending orders, order lookup, higher-level prepare order-action "
            "and prepare-cancel-action tools, plus deterministic approval/execution "
            "through Telegram."
        )
    return (
        "Broker order tools are unavailable because no ready broker provider is configured. "
        "Order review, preparation, and execution remain disabled until broker setup is ready."
    )


def _market_summary(toolbox: ToolBox) -> str:
    segments: list[str] = []
    names = toolbox.tools_by_name
    if "market_get_market_snapshot" in names or "market_get_volume_monitor" in names:
        segments.append("market snapshot and relative-volume monitoring")
    if "alpha_vantage_most_actively_traded" in names:
        segments.append("Alpha Vantage most-actively-traded context")
    if "edgar_company_disclosure_snapshot" in names:
        segments.append(
            "SEC EDGAR insider, stake, and official disclosure snapshots"
        )
    if "searxng_search" in names or "scrape_article" in names:
        segments.append("web search and article scraping for expansion")
    if not segments:
        return (
            "No market-data or research providers are currently configured for this agent."
        )
    return "Market analyst toolbox: " + "; ".join(segments) + "."


def _company_summary(
    settings: AppSettings,
    assessment: ConfigAssessment,
    toolboxes: dict[str, ToolBox],
) -> str:
    facts: list[str] = []
    market_data_toolbox = toolboxes.get("market_data")
    research_toolbox = toolboxes.get("research")
    if market_data_toolbox and market_data_toolbox.tools:
        facts.append("market data context")
    if (
        settings.market_intelligence_provider == "alpha_vantage"
        and _provider_ready(assessment, "alpha_vantage")
    ):
        facts.append("Alpha Vantage intelligence and fundamentals")
    if settings.disclosure_provider == "sec_edgar" and _provider_ready(assessment, "sec_edgar"):
        facts.append("SEC EDGAR disclosure context")
    if research_toolbox and research_toolbox.tools:
        facts.append("research via search and article scraping")
    if not facts:
        return (
            "Company analysis currently has no configured external market or research providers."
        )
    return "; ".join(facts) + "."


def _provider_ready(assessment: ConfigAssessment, name: str) -> bool:
    provider = assessment.providers.get(name)
    return bool(provider and provider.ready)
