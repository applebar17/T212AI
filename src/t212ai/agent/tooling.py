"""Runtime-aware specialist toolbox and summary assembly."""

from __future__ import annotations

from dataclasses import dataclass

from t212ai.app.bootstrap import ConfigAssessment
from t212ai.app.config import AppSettings
from t212ai.brokers.tools import build_broker_order_action_toolbox
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
        portfolio_toolbox_summary=_portfolio_summary(assessment),
        order_toolbox=(
            build_broker_order_action_toolbox()
            if assessment.capabilities["broker_execution_eligibility"].available
            else None
        ),
        order_toolbox_summary=_order_summary(settings, assessment),
        market_toolbox=market_toolbox,
        market_toolbox_summary=_market_summary(market_toolbox),
        company_toolbox_summary=_company_summary(settings, assessment, toolboxes),
    )


def _portfolio_summary(assessment: ConfigAssessment) -> str:
    facts = ["Portfolio snapshot, positions, pending orders"]
    if assessment.capabilities["market_data"].available:
        facts.append("market data context")
    if assessment.capabilities["market_intelligence"].available:
        facts.append("active-movers intelligence")
    if assessment.capabilities["disclosure"].available:
        facts.append("official disclosure activity")
    if assessment.capabilities["search"].available:
        facts.append("web research when needed")
    return ", ".join(facts) + "."


def _order_summary(
    settings: AppSettings,
    assessment: ConfigAssessment,
) -> str:
    del settings
    if assessment.capabilities["broker_execution_eligibility"].available:
        return (
            "Broker portfolio, pending orders, order lookup, instrument resolution "
            "and instrument snapshots, order/cancellation preparation tools, plus "
            "deterministic approval/execution through Telegram buttons."
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
        segments.append("active-movers intelligence")
    if "edgar_company_disclosure_snapshot" in names:
        segments.append("official disclosure activity")
    if "searxng_search" in names or "scrape_page" in names or "scrape_article" in names:
        segments.append("web search and page scraping for expansion")
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
    del settings
    facts: list[str] = []
    market_data_toolbox = toolboxes.get("market_data")
    research_toolbox = toolboxes.get("research")
    if market_data_toolbox and market_data_toolbox.tools:
        facts.append("market data context")
    if assessment.capabilities["market_intelligence"].available:
        facts.append("market intelligence and fundamentals context")
    if assessment.capabilities["disclosure"].available:
        facts.append("official disclosure context")
    if research_toolbox and research_toolbox.tools:
        facts.append("research via search and page scraping")
    if not facts:
        return (
            "Company analysis currently has no configured external market or research providers."
        )
    return "; ".join(facts) + "."
