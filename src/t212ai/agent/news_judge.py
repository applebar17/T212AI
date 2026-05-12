"""Agent for processing one streamed market-news event at a time."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from t212ai.app.logging import log_event
from t212ai.capabilities.protocols import BrokerReadService
from t212ai.genai.models import ToolResult, ToolSpec
from t212ai.genai.tools.base import ToolBox, build_tool_index, render_tool_descriptions
from t212ai.genai.tracing import set_trace_metadata, set_trace_name, traceable
from t212ai.guidelines.service import GuidelineMemoryService
from t212ai.market_signals import (
    MARKET_SIGNAL_TOOLBOX,
    MarketSignalService,
    build_market_signal_tool_mapping,
)

from .base import AgentProfile, BaseAgent
from .configurable import ConfigurablePlannerAgent, ConfigurableReasonerAgent
from .execution import GroupedPlanExecutor
from .intents import AgentIntent, IntentKind, StructuredIntentEntity
from .planner import TaskComplexity
from .schemas import AgentInvocationContext, AgentRequest, AgentResponse
from .structured import StructuredAgentOutputSynthesizer
from .time_context import render_timezone_context

LOGGER = logging.getLogger(__name__)


class NewsJudgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relevant: bool
    user_visible: bool = Field(alias="userVisible")
    summary: str
    actions_taken: list[str] = Field(default_factory=list, alias="actionsTaken")
    outcome: str
    confidence: str = Field(pattern="^(low|medium|high)$")


@dataclass(slots=True)
class NewsJudgeDependencies:
    market_agent: BaseAgent | None = None
    order_agent: BaseAgent | None = None
    market_signal_service: MarketSignalService | None = None
    broker_read_service: BrokerReadService | None = None


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


def build_news_judge_toolbox(dependencies: NewsJudgeDependencies) -> ToolBox:
    tools: list[ToolSpec] = []
    if dependencies.market_agent is not None:
        tools.append(_delegate_tool("news_delegate_to_market_analyst"))
    if dependencies.order_agent is not None:
        tools.append(_delegate_order_tool())
    if dependencies.market_signal_service is not None:
        tools.extend(MARKET_SIGNAL_TOOLBOX.tools)
    return ToolBox(
        name="news_ingestion_judge",
        tools=tools,
        tools_by_name=build_tool_index(tools),
    )


def build_news_judge_tool_mapping(
    dependencies: NewsJudgeDependencies,
    *,
    parent_request: AgentRequest,
) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    if dependencies.market_agent is not None:
        mapping["news_delegate_to_market_analyst"] = _delegate_to_agent_tool(
            dependencies.market_agent,
            parent_request=parent_request,
            intent=AgentIntent(kind=IntentKind.UNKNOWN, entities={"domain": "market"}),
        )
    if dependencies.order_agent is not None:
        mapping["news_delegate_to_order_agent"] = _delegate_to_order_tool(
            dependencies.order_agent,
            parent_request=parent_request,
        )
    mapping.update(build_market_signal_tool_mapping(dependencies.market_signal_service))
    return mapping


def _delegate_tool(name: str) -> ToolSpec:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": (
                "Delegate focused market analysis for the current streamed news event. "
                "Use this when market context, price action, volume, sector impact, "
                "or catalyst interpretation is needed."
            ),
            "strict": True,
            "parameters": _delegate_parameters(include_intent=False),
        },
    }


def _delegate_order_tool() -> ToolSpec:
    parameters = _delegate_parameters(include_intent=True)
    return {
        "type": "function",
        "function": {
            "name": "news_delegate_to_order_agent",
            "description": (
                "Delegate to the order agent when the current news and context may "
                "justify a concrete approval-gated order proposal. The order agent "
                "may prepare a pending action, but execution remains button-approved."
            ),
            "strict": True,
            "parameters": parameters,
        },
    }


def _delegate_parameters(*, include_intent: bool) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "task_brief": {
            "type": "string",
            "description": "Focused task for the downstream specialist.",
        },
        "expected_output": {
            "type": "string",
            "description": "Expected specialist result.",
        },
    }
    required = ["task_brief", "expected_output"]
    if include_intent:
        properties["intent_kind"] = {
            "type": "string",
            "enum": [IntentKind.PROPOSE_TRADE.value, IntentKind.PLACE_ORDER.value],
            "default": IntentKind.PROPOSE_TRADE.value,
        }
        properties["entities"] = {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": ["key", "value"],
            },
            "default": [],
        }
        required.extend(["intent_kind", "entities"])
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


def _delegate_to_agent_tool(
    agent: BaseAgent,
    *,
    parent_request: AgentRequest,
    intent: AgentIntent,
):
    def _delegate(*, task_brief: str, expected_output: str) -> ToolResult:
        response = agent.handle(
            AgentRequest(
                user_message=_delegated_message(task_brief, expected_output),
                chat_id=parent_request.chat_id,
                trigger_type="scheduler_news",
                history=parent_request.history,
                metadata=dict(parent_request.metadata),
            ),
            intent=intent,
            task_complexity=TaskComplexity.COMPLEX,
        )
        return _agent_tool_result(response)

    return _delegate


def _delegate_to_order_tool(
    agent: BaseAgent,
    *,
    parent_request: AgentRequest,
):
    def _delegate(
        *,
        task_brief: str,
        expected_output: str,
        intent_kind: str,
        entities: list[dict[str, str]],
    ) -> ToolResult:
        intent = AgentIntent(
            kind=IntentKind(intent_kind),
            entities={
                item.key: item.value
                for item in [
                    StructuredIntentEntity.model_validate(entity)
                    for entity in entities or []
                ]
            },
        )
        response = agent.handle(
            AgentRequest(
                user_message=_delegated_message(task_brief, expected_output),
                chat_id=parent_request.chat_id,
                trigger_type="scheduler_news",
                history=parent_request.history,
                metadata=dict(parent_request.metadata),
            ),
            intent=intent,
            task_complexity=TaskComplexity.COMPLEX,
        )
        return _agent_tool_result(response)

    return _delegate


def _agent_tool_result(response: AgentResponse) -> ToolResult:
    data: dict[str, Any] = {
        "selectedAgent": response.selected_agent,
        "metadata": response.metadata,
    }
    approval = response.artifacts.get("telegram_approval_request")
    if isinstance(approval, dict):
        data["telegramApproval"] = approval
    order_action = response.artifacts.get("order_action")
    if isinstance(order_action, dict):
        pending = order_action.get("pendingAction")
        if isinstance(pending, dict):
            data["pendingAction"] = pending
    proposal_id = response.artifacts.get("proposal_id")
    if proposal_id:
        data["proposalId"] = str(proposal_id)
    return ToolResult(status="ok", output=response.final_answer, data=data)


def _delegated_message(task_brief: str, expected_output: str) -> str:
    return json.dumps(
        {
            "taskBrief": str(task_brief or "").strip(),
            "expectedOutput": str(expected_output or "").strip(),
        },
        ensure_ascii=True,
        sort_keys=True,
    )


def _portfolio_context(broker_read_service: BrokerReadService | None) -> str:
    if broker_read_service is None:
        return "Portfolio snapshot: unavailable."
    try:
        snapshot = broker_read_service.get_portfolio_snapshot()
    except Exception as exc:
        return f"Portfolio snapshot: unavailable ({exc.__class__.__name__})."
    positions = []
    for position in snapshot.positions[:20]:
        instrument = position.instrument
        ticker = getattr(instrument, "ticker", None) if instrument is not None else None
        name = getattr(instrument, "name", None) if instrument is not None else None
        quantity = position.quantity_available_for_trading or position.quantity
        if ticker or name:
            positions.append(
                {
                    "ticker": str(ticker or ""),
                    "name": str(name or ""),
                    "quantity": str(quantity) if quantity is not None else None,
                    "currentPrice": (
                        str(position.current_price)
                        if position.current_price is not None
                        else None
                    ),
                }
            )
    account = snapshot.account
    context = {
        "asOf": snapshot.as_of.isoformat(),
        "currency": account.currency,
        "totalValue": str(account.total_value) if account.total_value is not None else None,
        "positionCount": len(snapshot.positions),
        "positions": positions,
    }
    return "Portfolio snapshot: " + json.dumps(context, ensure_ascii=True)


def _approval_payload_from_execution(execution: Any) -> dict[str, Any] | None:
    for group in reversed(list(getattr(execution, "group_executions", []) or [])):
        for action in reversed(list(getattr(group, "actions", []) or [])):
            for tool_call in reversed(list(getattr(action, "tool_calls", []) or [])):
                if isinstance(tool_call, dict) and isinstance(
                    tool_call.get("telegramApproval"),
                    dict,
                ):
                    return tool_call["telegramApproval"]
    return None


def _result_text(result: NewsJudgeResult) -> str:
    if result.outcome and result.summary:
        return f"{result.summary}\n\n{result.outcome}"
    return result.summary or result.outcome


def _news_judge_guidelines() -> str:
    return (
        "You operate in the background for scheduled Alpaca news monitoring. Most "
        "streamed news is noise; ignore broad commentary, repeated articles, generic "
        "theme pieces, low-impact analyst tweaks, and unrelated symbols. Relevant "
        "events include earnings/guidance, contracts, financing/dilution, M&A, "
        "regulatory decisions, bankruptcy/liquidity risk, company-specific catalysts, "
        "and material sector news directly affecting the configured symbols or "
        "portfolio. Your added value is filtering real-time noise, using portfolio "
        "and guideline context, saving useful signals, notifying only when useful, "
        "and proposing approval-gated orders when the thesis is coherent."
        " If the runtime context says order proposals are disabled, do not call "
        "the order agent."
    )


def _news_reasoning_guidelines() -> list[str]:
    return [
        "Treat the streamed news packet as the primary input and judge one event only.",
        "Use portfolio and investment guidelines to decide relevance and urgency.",
        "Do not notify the user for routine or unrelated news.",
        "Use downstream agents/tools only when they materially improve the outcome.",
        "Order proposals are allowed when supported, but execution remains approval-gated.",
    ]


def _news_planning_guidelines() -> list[str]:
    return [
        "Start with relevance judgment before expensive downstream work.",
        "Use market analysis for price/volume/context checks when market impact is plausible.",
        "Use market signal memory to save durable, concise catalysts.",
        "Use the order agent only for concrete approval-gated proposals.",
        "End with a concise structured judgment, not a raw research dump.",
    ]


def _news_examples() -> list[str]:
    return [
        (
            "Routine unrelated analyst note: relevant=false, userVisible=false, "
            "actionsTaken=[], outcome=Ignored."
        ),
        (
            "Monitored company signs a material supply agreement: analyze context, "
            "save signal, set relevant=true, userVisible=true if actionable."
        ),
        (
            "High-impact funding/regulatory approval with market momentum: analyze, "
            "save signal, and consider an approval-gated order proposal."
        ),
    ]
