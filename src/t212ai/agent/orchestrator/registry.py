"""Specialist registry types for the main orchestrator."""

from __future__ import annotations

from dataclasses import dataclass

from ..base import BaseAgent
from ..intents import AgentIntent, IntentKind
from ..schemas import AgentResponse
from ..specialists import (
    CalculatorAgent,
    CompanyAnalystAgent,
    LogDiagnosticAgent,
    MarketAnalystAgent,
    OrderAgent,
    PortfolioAnalystAgent,
    RedditResearchAgent,
    SchedulerAgent,
)


@dataclass(slots=True)
class SpecialistAgents:
    portfolio: PortfolioAnalystAgent
    order: OrderAgent
    market: MarketAnalystAgent
    company: CompanyAnalystAgent
    guideline_memory: GuidelineMemoryAgent
    calculator: CalculatorAgent
    scheduler: SchedulerAgent | None = None
    log_diagnostic: LogDiagnosticAgent | None = None
    reddit_research: RedditResearchAgent | None = None

    def by_key(self) -> dict[str, BaseAgent]:
        agents: dict[str, BaseAgent] = {
            "portfolio": self.portfolio,
            "order": self.order,
            "market": self.market,
            "company": self.company,
            "guideline_memory": self.guideline_memory,
            "calculator": self.calculator,
        }
        if self.scheduler is not None:
            agents["scheduler"] = self.scheduler
        if self.log_diagnostic is not None:
            agents["log_diagnostic"] = self.log_diagnostic
        if self.reddit_research is not None:
            agents["reddit_research"] = self.reddit_research
        return agents


@dataclass(slots=True)
class SpecialistToolRun:
    tool_name: str
    specialist_key: str
    task_brief: str
    expected_output: str
    intent: AgentIntent
    response: AgentResponse


_SPECIALIST_TOOL_CONFIGS: tuple[tuple[str, str, tuple[IntentKind, ...]], ...] = (
    (
        "delegate_to_portfolio_analyst",
        "portfolio",
        (
            IntentKind.PORTFOLIO_SUMMARY,
            IntentKind.PORTFOLIO_ATTENTION_SCAN,
            IntentKind.REBALANCE,
        ),
    ),
    (
        "delegate_to_order_agent",
        "order",
        (
            IntentKind.PLACE_ORDER,
            IntentKind.CANCEL_ORDER,
            IntentKind.REVIEW_PENDING_ORDERS,
            IntentKind.PROPOSE_TRADE,
        ),
    ),
    (
        "delegate_to_market_analyst",
        "market",
        (IntentKind.UNKNOWN,),
    ),
    (
        "delegate_to_company_analyst",
        "company",
        (IntentKind.ANALYZE_INSTRUMENT,),
    ),
    (
        "delegate_to_guideline_memory_agent",
        "guideline_memory",
        (IntentKind.MANAGE_GUIDELINES,),
    ),
    (
        "delegate_to_calculator_agent",
        "calculator",
        (IntentKind.CALCULATE,),
    ),
    (
        "delegate_to_scheduler_agent",
        "scheduler",
        (IntentKind.MANAGE_SCHEDULED_PROCESSES,),
    ),
    (
        "delegate_to_log_diagnostic_agent",
        "log_diagnostic",
        (IntentKind.DEBUG_LOGS,),
    ),
    (
        "delegate_to_reddit_research_agent",
        "reddit_research",
        (IntentKind.SOCIAL_RESEARCH,),
    ),
)
