"""Purpose-defined specialist agents."""

from __future__ import annotations

from t212ai.guidelines.service import GuidelineMemoryService

from .base import AgentProfile, BaseAgent
from .planner import TaskComplexity


class PortfolioAnalystAgent(BaseAgent):
    def __init__(self, reasoner, guideline_service: GuidelineMemoryService | None = None) -> None:
        super().__init__(
            reasoner,
            AgentProfile(
                name="portfolio_analyst",
                purpose=(
                    "Analyze broker portfolio state, exposure, concentration, "
                    "and attention items."
                ),
                guidelines=(
                    "Use Trading 212 as broker-authoritative state. For attention scans, "
                    "request fresh market/news context before making recommendations."
                ),
                toolbox_summary=(
                    "Portfolio snapshot, positions, pending orders, Yahoo market context, "
                    "Alpha Vantage intelligence, web search when needed."
                ),
                task_complexity=TaskComplexity.COMPLEX,
                guideline_scopes=("global", "agent:portfolio"),
                guideline_include_categories=("investment_preference",),
            ),
            guideline_service=guideline_service,
        )

    def resolve_complexity(self, message: str) -> TaskComplexity:
        text = message.lower()
        if any(word in text for word in ("attention", "risk", "rebalance", "exposure")):
            return TaskComplexity.COMPLEX
        return TaskComplexity.EASY


class OrderAgent(BaseAgent):
    def __init__(self, reasoner, guideline_service: GuidelineMemoryService | None = None) -> None:
        super().__init__(
            reasoner,
            AgentProfile(
                name="order_agent",
                purpose="Review, prepare, cancel, and reason about Trading 212 orders.",
                guidelines=(
                    "Treat order submission and cancellation as state-changing. "
                    "Require explicit confirmation before execution. Never retry "
                    "uncertain submissions without reconciliation."
                ),
                toolbox_summary=(
                    "Trading 212 pending orders, order lookup, prepare order, gated "
                    "place order, gated cancel order, market context for order review."
                ),
                task_complexity=TaskComplexity.CRITICAL,
                guideline_scopes=("global", "agent:order"),
                guideline_include_categories=("investment_preference",),
            ),
            guideline_service=guideline_service,
        )

    def resolve_complexity(self, message: str) -> TaskComplexity:
        del message
        return TaskComplexity.CRITICAL


class MarketAnalystAgent(BaseAgent):
    def __init__(self, reasoner, guideline_service: GuidelineMemoryService | None = None) -> None:
        super().__init__(
            reasoner,
            AgentProfile(
                name="market_analyst",
                purpose=(
                    "Analyze broad market context, movers, commodities, "
                    "and macro-adjacent signals."
                ),
                guidelines=(
                    "Use market data as context, not broker state. Distinguish latest "
                    "price context from slower research enrichment."
                ),
                toolbox_summary=(
                    "market_data: Yahoo market data and analytics; "
                    "Alpha Vantage commodities and intelligence; web search for source expansion."
                ),
                task_complexity=TaskComplexity.COMPLEX,
                guideline_scopes=("global", "agent:market"),
            ),
            guideline_service=guideline_service,
        )


class CompanyAnalystAgent(BaseAgent):
    def __init__(self, reasoner, guideline_service: GuidelineMemoryService | None = None) -> None:
        super().__init__(
            reasoner,
            AgentProfile(
                name="company_analyst",
                purpose=(
                    "Analyze a company, ETF, or ticker using market, fundamental, "
                    "and research context."
                ),
                guidelines=(
                    "Resolve ticker ambiguity first. Use multiple sources for thesis-level "
                    "claims and keep Yahoo as convenience context."
                ),
                toolbox_summary=(
                    "yahoo_market_context: symbol/quote/options/analyst context; "
                    "research: search and article scraping; "
                    "Alpha Vantage intelligence and fundamentals."
                ),
                task_complexity=TaskComplexity.COMPLEX,
                guideline_scopes=("global", "agent:company"),
                guideline_include_categories=("investment_preference",),
            ),
            guideline_service=guideline_service,
        )
