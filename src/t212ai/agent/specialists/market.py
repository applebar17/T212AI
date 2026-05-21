"""Market analyst specialist agent."""

from __future__ import annotations

from typing import Any

from t212ai.genai.tools import build_tool_mapping_for
from t212ai.genai.tools.base import ToolBox, render_tool_descriptions
from t212ai.genai.tracing import set_trace_metadata, set_trace_name, traceable
from t212ai.guidelines.service import GuidelineMemoryService

from ..base import AgentProfile, BaseAgent
from ..configurable import ConfigurablePlannerAgent, ConfigurableReasonerAgent
from ..execution import GroupedPlanExecutor
from ..intents import AgentIntent, IntentKind
from ..planner import TaskComplexity
from ..schemas import AgentInvocationContext, AgentRequest, AgentResponse
from .shared import (
    _build_reddit_research_delegate,
    _empty_toolbox,
    _reddit_research_delegation_tool,
    _with_tool,
)


class MarketAnalystAgent(BaseAgent):
    def __init__(
        self,
        reasoner,
        guideline_service: GuidelineMemoryService | None = None,
        *,
        market_data_service=None,
        market_signal_service=None,
        toolbox: ToolBox | None = None,
        toolbox_summary: str | None = None,
        configurable_reasoner_agent: ConfigurableReasonerAgent | None = None,
        configurable_planner_agent: ConfigurablePlannerAgent | None = None,
        grouped_plan_executor: GroupedPlanExecutor | None = None,
        reddit_research_agent: BaseAgent | None = None,
    ) -> None:
        resolved_toolbox = toolbox or _empty_toolbox("market_analyst")
        if reddit_research_agent is not None:
            resolved_toolbox = _with_tool(
                resolved_toolbox,
                _reddit_research_delegation_tool(),
            )
        resolved_toolbox_summary = toolbox_summary or (
            "Market analyst toolbox: market snapshot and relative-volume monitoring; "
            "active-movers intelligence; official disclosure activity; web search "
            "and article scraping for expansion; persistent market signal memory."
        )
        if reddit_research_agent is not None:
            resolved_toolbox_summary = (
                resolved_toolbox_summary.rstrip(".")
                + "; delegated Reddit/community social analysis."
            )
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
                    "price context from slower research enrichment. For broad live market "
                    "scans, movers, gainers, losers, or watchlists, use available market "
                    "tools and proceed with reasonable defaults instead of asking broker "
                    "execution-risk or volatility-preference questions. Search stored "
                    "market signals before deeper research when the request mentions known "
                    "symbols, sectors, themes, watchlists, catalysts, or portfolio-relevant "
                    "market context. Treat stored signals as advisory context only."
                ),
                toolbox_summary=resolved_toolbox_summary,
                task_complexity=TaskComplexity.COMPLEX,
                guideline_scopes=("global", "agent:market"),
                toolbox=resolved_toolbox,
            ),
            guideline_service=guideline_service,
        )
        self.market_data_service = market_data_service
        self.market_signal_service = market_signal_service
        self.configurable_reasoner_agent = configurable_reasoner_agent
        self.configurable_planner_agent = configurable_planner_agent
        self.grouped_plan_executor = grouped_plan_executor
        self.reddit_research_agent = reddit_research_agent

    @traceable(
        name="Market Analyst Handle",
        run_type="chain"
    )
    def handle(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent | None = None,
        task_complexity: TaskComplexity | None = None,
    ) -> AgentResponse:
        if not self._can_use_configurable_loop():
            return super().handle(
                request,
                intent=intent,
                task_complexity=task_complexity,
            )

        resolved_intent = intent or AgentIntent(kind=IntentKind.UNKNOWN)
        complexity = task_complexity or self.resolve_complexity(request.user_message)
        set_trace_name(f"{self.__class__.__name__}.handle")
        set_trace_metadata(
            agent_name=self.name,
            agent_kind="specialist",
            intent_kind=resolved_intent.kind.value,
            task_complexity=complexity.value,
            workflow="market_analysis",
            execution_mode="grouped_plan",
        )
        try:
            return self._handle_configurable_market_analysis(
                request,
                intent=resolved_intent,
                task_complexity=complexity,
            )
        except Exception as exc:  # pragma: no cover - live LLM/provider safety net
            return AgentResponse(
                final_answer=(
                    "I couldn't complete the configurable market-analysis loop. "
                    f"Reason: {exc.__class__.__name__}: {exc}"
                ),
                selected_agent=self.name,
                metadata={
                    "workflow": "market_analysis",
                    "workflow_status": "error",
                    "execution_mode": "grouped_plan",
                    "error_type": exc.__class__.__name__,
                },
                artifacts={
                    "workflow": "market_analysis",
                    "market_analysis": {
                        "status": "error",
                        "error": str(exc),
                        "error_type": exc.__class__.__name__,
                    },
                },
            )

    @traceable(
        name="Market Analyst Configurable Market Analysis",
        run_type="chain"
    )
    def _handle_configurable_market_analysis(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent,
        task_complexity: TaskComplexity,
    ) -> AgentResponse:
        set_trace_name(f"{self.__class__.__name__}.configurable_market_analysis")
        set_trace_metadata(
            agent_name=self.name,
            agent_step="configurable_market_analysis",
            step_kind="agentic_flow",
            intent_kind=intent.kind.value,
            task_complexity=task_complexity.value,
            workflow="market_analysis",
            execution_mode="grouped_plan",
        )
        invocation = AgentInvocationContext(
            user_request=request.user_message,
            chat_history=self._history_for_prompt(request.history),
            invocation_reason=(
                request.orchestrator_guidance
                or "Market analyst handling the current user request."
            ),
            intent=intent,
            persistent_guidance=self._persistent_guidance(),
            agent_name=self.profile.name,
            purpose=self.profile.purpose,
            guidelines=self.profile.guidelines,
            toolbox_summary=self.profile.toolbox_summary,
            tool_descriptions=render_tool_descriptions(self.profile.toolbox),
            task_complexity=task_complexity,
        )
        assert self.configurable_reasoner_agent is not None
        assert self.configurable_planner_agent is not None
        assert self.grouped_plan_executor is not None
        assert self.profile.toolbox is not None

        reasoning_context = self.configurable_reasoner_agent.reason(invocation)
        if not reasoning_context.can_proceed and reasoning_context.clarifying_questions:
            return AgentResponse(
                final_answer="I need one clarification: "
                + " ".join(reasoning_context.clarifying_questions),
                selected_agent=self.name,
                metadata={
                    "workflow": "market_analysis",
                    "workflow_status": "needs_clarification",
                    "execution_mode": "grouped_plan",
                },
                artifacts={
                    "workflow": "market_analysis",
                    "market_analysis": {
                        "reasoning_context": reasoning_context.model_dump(mode="json"),
                    },
                },
            )

        grouped_plan = self.configurable_planner_agent.plan(
            invocation,
            reasoning_context=reasoning_context,
        )
        tools_mapping = self._build_tools_mapping(request)
        execution_result = self.grouped_plan_executor.execute(
            invocation=invocation,
            reasoning_context=reasoning_context,
            grouped_plan=grouped_plan,
            toolbox=self.profile.toolbox,
            tools_mapping=tools_mapping,
        )
        compatible_plan = grouped_plan.to_agent_plan()
        group_count = len(grouped_plan.action_groups)
        return AgentResponse(
            final_answer=execution_result.final_answer,
            selected_agent=self.name,
            plan=compatible_plan,
            metadata={
                "workflow": "market_analysis",
                "workflow_status": execution_result.status,
                "execution_mode": "grouped_plan",
                "group_count": str(group_count),
                "action_count": str(execution_result.action_count),
            },
            artifacts={
                "workflow": "market_analysis",
                "market_analysis": {
                    "reasoning_context": reasoning_context.model_dump(mode="json"),
                    "grouped_plan": grouped_plan.model_dump(mode="json"),
                    "execution": execution_result.model_dump(mode="json"),
                    "final_synthesis": execution_result.final_answer,
                },
            },
        )

    def _can_use_configurable_loop(self) -> bool:
        return (
            self.configurable_reasoner_agent is not None
            and self.configurable_planner_agent is not None
            and self.grouped_plan_executor is not None
            and self.profile.toolbox is not None
            and bool(self.profile.toolbox.tools)
        )

    @traceable(
        name="Market Analyst Execute",
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
            workflow="market_analysis",
            execution_mode="tool_orchestration",
        )
        if self.profile.toolbox is None or not self.profile.toolbox.tools:
            return None

        final_answer = self.reasoner.orchestrate_with_tools(
            agent_name=self.profile.name,
            purpose=self.profile.purpose,
            guidelines=self.profile.guidelines,
            toolbox_summary=self.profile.toolbox_summary,
            user_request=request.user_message,
            toolbox=self.profile.toolbox,
            tools_mapping=self._build_tools_mapping(request),
            chat_history=self._history_for_prompt(request.history),
            persistent_guidance=self._persistent_guidance(),
        )
        if not final_answer.strip():
            return None
        return AgentResponse(
            final_answer=final_answer,
            selected_agent=self.name,
            plan=plan,
            metadata={"workflow": "market_analysis", "workflow_status": "ok"},
            artifacts={"workflow": "market_analysis"},
        )

    def _build_tools_mapping(self, request: AgentRequest) -> dict[str, Any]:
        assert self.profile.toolbox is not None
        mapping = build_tool_mapping_for(
            self.profile.toolbox,
            market_data_service=self.market_data_service,
            market_signal_service=self.market_signal_service,
        )
        if self.reddit_research_agent is not None:
            mapping["delegate_to_reddit_research_agent"] = _build_reddit_research_delegate(
                delegating_agent=self,
                reddit_agent=self.reddit_research_agent,
                request=request,
            )
        return mapping

