"""Company analyst specialist agent."""

from __future__ import annotations

from t212ai.guidelines.service import GuidelineMemoryService

from ..base import AgentProfile, BaseAgent
from ..planner import TaskComplexity


class CompanyAnalystAgent(BaseAgent):
    def __init__(
        self,
        reasoner,
        guideline_service: GuidelineMemoryService | None = None,
        *,
        toolbox_summary: str | None = None,
    ) -> None:
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
                    "claims and keep market-data providers as convenience context."
                ),
                toolbox_summary=toolbox_summary or (
                    "market-data context: symbol, quote, and chart-ready context; "
                    "research: search and article scraping; "
                    "specialist provider context when needed; market intelligence and fundamentals."
                ),
                task_complexity=TaskComplexity.COMPLEX,
                guideline_scopes=("global", "agent:company"),
                guideline_include_categories=("investment_preference",),
            ),
            guideline_service=guideline_service,
        )

