"""Portfolio specialist agent."""

from __future__ import annotations

import re

from t212ai.genai.tracing import set_trace_metadata, set_trace_name, traceable
from t212ai.guidelines.service import GuidelineMemoryService
from t212ai.workflows import PortfolioSummaryWorkflow, WorkflowExecutionError

from ..base import AgentProfile, BaseAgent
from ..intents import AgentIntent, IntentKind
from ..planner import TaskComplexity
from ..schemas import AgentRequest, AgentResponse


class PortfolioAnalystAgent(BaseAgent):
    def __init__(
        self,
        reasoner,
        guideline_service: GuidelineMemoryService | None = None,
        *,
        portfolio_summary_workflow: PortfolioSummaryWorkflow | None = None,
        toolbox_summary: str | None = None,
    ) -> None:
        super().__init__(
            reasoner,
            AgentProfile(
                name="portfolio_analyst",
                purpose=(
                    "Analyze broker portfolio state, exposure, concentration, "
                    "and attention items."
                ),
                guidelines=(
                    "Use the configured broker as account-authoritative state. For attention scans, "
                    "request fresh market/news context before making recommendations."
                ),
                toolbox_summary=toolbox_summary or (
                    "Portfolio snapshot, positions, pending orders, market data context, "
                    "active-movers intelligence, official disclosure activity, and web research when needed."
                ),
                task_complexity=TaskComplexity.COMPLEX,
                guideline_scopes=("global", "agent:portfolio"),
                guideline_include_categories=("investment_preference",),
            ),
            guideline_service=guideline_service,
        )
        self.portfolio_summary_workflow = portfolio_summary_workflow

    def resolve_complexity(self, message: str) -> TaskComplexity:
        text = message.lower()
        if any(word in text for word in ("attention", "risk", "rebalance", "exposure")):
            return TaskComplexity.COMPLEX
        return TaskComplexity.EASY

    @traceable(
        name="Portfolio Analyst Execute",
        run_type="chain"
    )
    def execute(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent,
        task_complexity: TaskComplexity,
        plan,
    ) -> AgentResponse | None:
        set_trace_name(f"{self.__class__.__name__}.execute")
        set_trace_metadata(
            agent_name=self.name,
            agent_step="execute",
            step_kind="execute",
            intent_kind=intent.kind.value,
            task_complexity=task_complexity.value,
            workflow="portfolio_summary",
        )
        if (
            intent.kind != IntentKind.PORTFOLIO_SUMMARY
            or self.portfolio_summary_workflow is None
        ):
            return None

        top_positions_limit = _extract_top_positions_limit(request.user_message)
        try:
            summary = self.portfolio_summary_workflow.run(
                top_positions_limit=top_positions_limit,
            )
        except WorkflowExecutionError as exc:
            return AgentResponse(
                final_answer=(
                    "I couldn't retrieve the broker portfolio summary. "
                    f"Reason: {exc}. Hint: {exc.hint}"
                ),
                selected_agent=self.name,
                plan=plan,
                metadata={
                    "workflow": "portfolio_summary",
                    "workflow_status": "error",
                    "error_code": exc.code,
                },
                artifacts={"workflow_error": exc.to_dict()},
            )

        return AgentResponse(
            final_answer=summary.render_text(),
            selected_agent=self.name,
            plan=plan,
            metadata={
                "workflow": "portfolio_summary",
                "workflow_status": "ok",
                "position_count": str(summary.position_count),
                "pending_order_count": str(summary.pending_order_count),
                "top_positions_limit": (
                    str(summary.top_positions_limit)
                    if summary.top_positions_limit is not None
                    else "none"
                ),
                "displayed_position_count": str(summary.displayed_position_count),
            },
            artifacts={
                "workflow": "portfolio_summary",
                "portfolio_summary": summary.model_dump(mode="json"),
            },
        )



def _extract_top_positions_limit(message: str) -> int | None:
    text = str(message or "").lower()
    for pattern in (
        r"\btop\s+(\d{1,3})\b",
        r"\b(?:largest|biggest)\s+(\d{1,3})\b",
    ):
        match = re.search(pattern, text)
        if match is None:
            continue
        value = int(match.group(1))
        return value if value > 0 else None
    return None
