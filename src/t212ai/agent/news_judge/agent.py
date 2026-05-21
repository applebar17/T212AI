"""News ingestion judge agent."""

from __future__ import annotations

import logging
import time

from t212ai.app.logging import log_event
from t212ai.genai.tools.base import render_tool_descriptions
from t212ai.genai.tracing import set_trace_metadata, set_trace_name, traceable
from t212ai.guidelines.service import GuidelineMemoryService

from ..base import AgentProfile, BaseAgent
from ..configurable import ConfigurablePlannerAgent, ConfigurableReasonerAgent
from ..execution import GroupedPlanExecutor
from ..intents import AgentIntent, IntentKind
from ..planner import TaskComplexity
from ..schemas import AgentInvocationContext, AgentRequest, AgentResponse
from ..structured import StructuredAgentOutputSynthesizer
from ..time_context import render_timezone_context
from .context import _portfolio_context
from .guidance import (
    _news_examples,
    _news_judge_guidelines,
    _news_planning_guidelines,
    _news_reasoning_guidelines,
)
from .outputs import _approval_payload_from_execution, _result_text
from .schemas import NewsJudgeDependencies, NewsJudgeResult
from .toolbox import build_news_judge_tool_mapping, build_news_judge_toolbox

LOGGER = logging.getLogger(__name__)


class NewsIngestionJudgeAgent(BaseAgent):
    def __init__(
        self,
        reasoner,
        *,
        guideline_service: GuidelineMemoryService | None = None,
        dependencies: NewsJudgeDependencies | None = None,
        configurable_reasoner_agent: ConfigurableReasonerAgent | None = None,
        configurable_planner_agent: ConfigurablePlannerAgent | None = None,
        grouped_plan_executor: GroupedPlanExecutor | None = None,
        default_timezone: str = "UTC",
        max_tool_calls: int = 10,
    ) -> None:
        self.dependencies = dependencies or NewsJudgeDependencies()
        self.configurable_reasoner_agent = configurable_reasoner_agent or ConfigurableReasonerAgent(
            reasoner.genai
        )
        self.configurable_planner_agent = configurable_planner_agent or ConfigurablePlannerAgent(
            reasoner.genai
        )
        self.grouped_plan_executor = grouped_plan_executor or GroupedPlanExecutor(
            reasoner.genai
        )
        self.default_timezone = default_timezone
        self.max_tool_calls = max(0, int(max_tool_calls))
        toolbox = build_news_judge_toolbox(self.dependencies)
        super().__init__(
            reasoner,
            AgentProfile(
                name="news_ingestion_judge",
                purpose=(
                    "Judge one streamed market-news event in the context of a scheduled "
                    "monitor, decide whether it matters, and coordinate downstream "
                    "market, signal-memory, or order-proposal work when useful."
                ),
                guidelines=_news_judge_guidelines(),
                toolbox_summary=(
                    "Private tools: delegate to market analyst, delegate to order agent, "
                    "and use persistent market-signal memory when configured. "
                    + render_tool_descriptions(toolbox)
                ),
                task_complexity=TaskComplexity.COMPLEX,
                guideline_scopes=("global", "agent:news_ingestion_judge"),
                guideline_include_categories=("investment_preference",),
                toolbox=toolbox,
            ),
            guideline_service=guideline_service,
        )

    @traceable(name="News Ingestion Judge Handle", run_type="chain")
    def handle(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent | None = None,
        task_complexity: TaskComplexity | None = None,
    ) -> AgentResponse:
        resolved_intent = intent or AgentIntent(kind=IntentKind.UNKNOWN)
        complexity = task_complexity or TaskComplexity.COMPLEX
        set_trace_name(f"{self.__class__.__name__}.handle")
        set_trace_metadata(
            agent_name=self.name,
            agent_kind="event_processor",
            intent_kind=resolved_intent.kind.value,
            task_complexity=complexity.value,
            process_id=request.metadata.get("process_id"),
        )
        start = time.monotonic()
        log_event(
            LOGGER,
            "agent.start",
            component="agent",
            agent_name=self.name,
            step="handle",
            status="started",
            chat_id=request.chat_id,
            process_id=request.metadata.get("process_id"),
            task_complexity=complexity.value,
        )
        toolbox = self.profile.toolbox or build_news_judge_toolbox(self.dependencies)
        context_guidance = self._context_guidance(request)
        invocation = AgentInvocationContext(
            user_request=request.user_message,
            chat_history=self._history_for_prompt(request.history),
            invocation_reason=(
                request.orchestrator_guidance
                or "Process one Alpaca real-time news event from a scheduled monitor."
            ),
            intent=resolved_intent,
            persistent_guidance=self._persistent_guidance(),
            agent_name=self.profile.name,
            purpose=self.profile.purpose,
            guidelines=f"{self.profile.guidelines}\n\nRuntime context:\n{context_guidance}",
            toolbox_summary=self.profile.toolbox_summary,
            tool_descriptions=render_tool_descriptions(toolbox),
            reasoning_guidelines=_news_reasoning_guidelines(),
            planning_guidelines=_news_planning_guidelines(),
            reasoning_examples=_news_examples(),
            planning_examples=_news_examples(),
            task_complexity=complexity,
        )
        try:
            reasoning_context = self.configurable_reasoner_agent.reason(invocation)
            grouped_plan = self.configurable_planner_agent.plan(
                invocation,
                reasoning_context=reasoning_context,
            )
            execution = self.grouped_plan_executor.execute(
                invocation=invocation,
                reasoning_context=reasoning_context,
                grouped_plan=grouped_plan,
                toolbox=toolbox,
                tools_mapping=build_news_judge_tool_mapping(
                    self.dependencies,
                    parent_request=request,
                ),
                max_tool_calls=self.max_tool_calls,
            )
            source_response = AgentResponse(
                final_answer=execution.final_answer,
                selected_agent=self.name,
                metadata={
                    "workflow": "news_ingestion_judge",
                    "workflow_status": execution.status,
                },
                artifacts={
                    "workflow": "news_ingestion_judge",
                    "execution": execution.model_dump(mode="json"),
                },
            )
            result = StructuredAgentOutputSynthesizer(self.reasoner.genai).synthesize(
                NewsJudgeResult,
                source_agent_name=self.name,
                source_response=source_response,
                user_request=request.user_message,
                instructions=(
                    "Return the compact final judgment for this one streamed news event. "
                    "Set userVisible true only when the user should be notified now. "
                    "Set relevant false for routine, broad, stale, duplicated, or low-impact news."
                ),
                context={"requestMetadata": request.metadata},
                task_complexity=complexity,
            )
            result = NewsJudgeResult.model_validate(result)
            artifacts = dict(source_response.artifacts)
            artifacts["news_judge_result"] = result.model_dump(
                by_alias=True,
                mode="json",
            )
            approval = _approval_payload_from_execution(execution)
            if approval is not None:
                artifacts["telegram_approval_request"] = approval
            response = AgentResponse(
                final_answer=_result_text(result),
                selected_agent=self.name,
                metadata={
                    "workflow": "news_ingestion_judge",
                    "workflow_status": execution.status,
                    "relevant": str(result.relevant),
                    "user_visible": str(result.user_visible),
                    "confidence": result.confidence,
                },
                artifacts=artifacts,
            )
        except Exception as exc:
            log_event(
                LOGGER,
                "agent.error",
                "error",
                component="agent",
                agent_name=self.name,
                step="handle",
                status="error",
                chat_id=request.chat_id,
                process_id=request.metadata.get("process_id"),
                duration_ms=int((time.monotonic() - start) * 1000),
                error_type=exc.__class__.__name__,
            )
            raise
        log_event(
            LOGGER,
            "agent.end",
            component="agent",
            agent_name=self.name,
            step="handle",
            status=response.metadata.get("workflow_status", "ok"),
            chat_id=request.chat_id,
            process_id=request.metadata.get("process_id"),
            duration_ms=int((time.monotonic() - start) * 1000),
            relevant=response.metadata.get("relevant"),
            user_visible=response.metadata.get("user_visible"),
        )
        return response

    def _context_guidance(self, request: AgentRequest) -> str:
        timezone_name = request.metadata.get("timezone") or self.default_timezone
        pieces = [
            render_timezone_context(timezone_name),
            f"Scheduled process id: {request.metadata.get('process_id') or 'unknown'}.",
            f"Scheduled symbol scope: {request.metadata.get('symbols') or 'unknown'}.",
            (
                "Order proposals enabled for this monitor: "
                f"{request.metadata.get('order_proposals_enabled', 'false')}."
            ),
        ]
        task_guidelines = str(request.metadata.get("task_guidelines") or "").strip()
        if task_guidelines:
            pieces.append(f"Monitor-specific user guidelines: {task_guidelines}")
        portfolio = _portfolio_context(self.dependencies.broker_read_service)
        if portfolio:
            pieces.append(portfolio)
        return "\n".join(pieces)
