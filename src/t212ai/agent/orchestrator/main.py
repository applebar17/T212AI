"""Main user-facing LLM orchestrator."""

from __future__ import annotations

import logging
import time
from typing import Any

from pydantic import ValidationError
from t212ai.app.logging import log_event
from t212ai.genai.models import ToolError, ToolResult, ToolSpec
from t212ai.genai.tools.base import ToolBox, build_tool_index
from t212ai.genai.tracing import set_trace_metadata, set_trace_name, traceable
from t212ai.guidelines.service import GuidelineMemoryService
from t212ai.scheduler.management import (
    SCHEDULER_ALPACA_NEWS_MONITOR_CREATE_TOOL,
    build_scheduler_agent_tool_mapping,
)
from t212ai.scheduler.service import ScheduledProcessService

from ..base import AgentProfile, BaseAgent
from ..intents import AgentIntent, IntentKind
from ..planner import TaskComplexity
from ..reasoning import AgentReasoner
from ..schemas import AgentRequest, AgentResponse, OrchestratorDelegationRequest
from ..time_context import render_timezone_context
from .classifier import _entities_to_items, _metadata_user_id, classify_message
from .factory import build_specialist_agents
from .registry import (
    _SPECIALIST_TOOL_CONFIGS,
    SpecialistAgents,
    SpecialistToolRun,
)

LOGGER = logging.getLogger(__name__)


class MainOrchestratorAgent(BaseAgent):
    def __init__(
        self,
        reasoner: AgentReasoner,
        *,
        guideline_service: GuidelineMemoryService | None = None,
        specialists: SpecialistAgents | None = None,
        scheduled_process_service: ScheduledProcessService | None = None,
        scheduler_default_timezone: str = "UTC",
        scheduler_default_poll_every_seconds: int = 300,
    ) -> None:
        timezone_context = render_timezone_context(scheduler_default_timezone)
        super().__init__(
            reasoner,
            AgentProfile(
                name="main_orchestrator",
                purpose=(
                    "Hold the user-facing conversation, decide whether to answer directly, "
                    "ask for clarification, or delegate to the right specialist."
                ),
                guidelines=(
                    "Use a concise, professional tone with friendly teammate energy. Keep "
                    "replies calm, direct, and helpful without sounding stiff. Avoid emojis "
                    "unless the user clearly sets that tone first. For Telegram-facing replies, "
                    "prefer plain text over Markdown or HTML. Answer capability questions, help "
                    "questions, and ordinary conversation directly. Delegate when specialist "
                    "reasoning, tools, workflows, or deterministic execution are needed. "
                    "Preserve safety boundaries for orders, approvals, and broker actions. "
                    "Natural-language messages can request or discuss side effects, but "
                    "pending side effects are approved or rejected only through Telegram "
                    "button callbacks. "
                    f"{timezone_context}"
                ),
                toolbox_summary=(
                    "Delegation tools: portfolio_analyst, order_agent, market_analyst, "
                    "company_analyst, guideline_memory_agent, calculator_agent, and "
                    "scheduler_agent when configured. The orchestrator may also answer "
                    "directly or ask clarifying questions."
                ),
                task_complexity=TaskComplexity.EASY,
                guideline_scopes=("global", "orchestrator"),
                guideline_include_categories=("investment_preference",),
            ),
            guideline_service=guideline_service,
        )
        self.specialists = specialists or build_specialist_agents(
            reasoner,
            guideline_service=guideline_service,
        )
        self.scheduled_process_service = scheduled_process_service
        self.scheduler_default_timezone = scheduler_default_timezone
        self.scheduler_default_poll_every_seconds = scheduler_default_poll_every_seconds
        self.orchestrator_toolbox = self._build_orchestrator_toolbox()
        self.profile.toolbox = self.orchestrator_toolbox
        self.profile.toolbox_summary = self._render_orchestrator_toolbox_summary()

    @traceable(
        name="Main Orchestrator Handle",
        run_type="chain"
    )
    def handle(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent | None = None,
        task_complexity: TaskComplexity | None = None,
    ) -> AgentResponse:
        del intent
        set_trace_name(f"{self.__class__.__name__}.handle")
        set_trace_metadata(
            agent_name=self.name,
            agent_kind="orchestrator",
            task_complexity=(task_complexity or TaskComplexity.EASY).value,
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
            task_complexity=(task_complexity or TaskComplexity.EASY).value,
        )
        tool_runs: list[SpecialistToolRun] = []
        try:
            final_answer = self._forced_order_route_answer(request, tool_runs)
            if final_answer is None:
                final_answer = self.reasoner.orchestrate_with_tools(
                    agent_name=self.profile.name,
                    purpose=self.profile.purpose,
                    guidelines=self.profile.guidelines,
                    toolbox_summary=self.profile.toolbox_summary,
                    user_request=request.user_message,
                    toolbox=self.orchestrator_toolbox,
                    tools_mapping=self._build_tool_mapping(request, tool_runs),
                    chat_history=self._history_for_prompt(request.history),
                    persistent_guidance=self._persistent_guidance(),
                )
            approval_payload = self._approval_payload(tool_runs)
            if isinstance(approval_payload, dict) and approval_payload.get("text"):
                final_answer = str(approval_payload["text"])
            elif not final_answer.strip() and tool_runs:
                final_answer = tool_runs[-1].response.final_answer

            metadata, artifacts, plan, critique = self._build_response_package(tool_runs)
            response = AgentResponse(
                final_answer=final_answer,
                selected_agent=self.name,
                plan=plan,
                critique=critique,
                metadata=metadata,
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
                duration_ms=int((time.monotonic() - start) * 1000),
                error_type=exc.__class__.__name__,
            )
            raise
        log_event(
            LOGGER,
            "agent.end",
            component="agent",
            agent_name=self.name,
            selected_agent=response.selected_agent,
            step="handle",
            status=response.metadata.get("workflow_status", "ok"),
            chat_id=request.chat_id,
            duration_ms=int((time.monotonic() - start) * 1000),
            delegated_count=len(tool_runs),
        )
        return response

    @traceable(
        name="Main Orchestrator Forced Order Route",
        run_type="chain"
    )
    def _forced_order_route_answer(
        self,
        request: AgentRequest,
        tool_runs: list[SpecialistToolRun],
    ) -> str | None:
        set_trace_name(f"{self.__class__.__name__}.forced_order_route")
        set_trace_metadata(
            agent_name=self.name,
            agent_step="forced_order_route",
            step_kind="routing",
        )
        inferred_intent = classify_message(request.user_message)
        if inferred_intent.kind not in {
            IntentKind.PLACE_ORDER,
            IntentKind.CANCEL_ORDER,
        }:
            return None
        tool_mapping = self._build_tool_mapping(request, tool_runs)
        delegate = tool_mapping["delegate_to_order_agent"]
        result = delegate(
            task_brief=self._forced_order_task_brief(inferred_intent),
            expected_output=(
                "Return a deterministic broker action result. If approval is required, "
                "prepare the Telegram button approval request; typed confirmation text "
                "is ordinary conversation."
            ),
            intent_kind=inferred_intent.kind.value,
            entities=_entities_to_items(inferred_intent),
        )
        if result.status == "ok":
            return str(result.output or "")
        if result.error is None:
            return str(result.output or "")
        message = result.error.message
        if result.error.hint:
            message = f"{message} Hint: {result.error.hint}"
        return message

    def _build_orchestrator_toolbox(self) -> ToolBox:
        specialists = self.specialists.by_key()
        tools = []
        for tool_name, specialist_key, allowed_intents in _SPECIALIST_TOOL_CONFIGS:
            specialist = specialists.get(specialist_key)
            if specialist is None:
                continue
            tools.append(
                self._delegation_tool(
                    name=tool_name,
                    specialist=specialist,
                    allowed_intents=allowed_intents,
                )
            )
        if self.scheduled_process_service is not None:
            tools.append(SCHEDULER_ALPACA_NEWS_MONITOR_CREATE_TOOL)
        return ToolBox(
            name="orchestrator_routing",
            tools=tools,
            tools_by_name=build_tool_index(tools),
        )

    def _render_orchestrator_toolbox_summary(self) -> str:
        lines: list[str] = []
        for tool in self.orchestrator_toolbox.tools:
            function = tool.get("function", {})
            description = str(function.get("description") or "").strip()
            lines.append(f"- {function.get('name')}: {description}")
        return "\n".join(lines)

    def _delegation_tool(
        self,
        *,
        name: str,
        specialist: BaseAgent,
        allowed_intents: tuple[IntentKind, ...],
    ) -> ToolSpec:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": self._tool_description(
                    specialist=specialist,
                    allowed_intents=allowed_intents,
                ),
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "task_brief": {
                            "type": "string",
                            "description": (
                                "What the specialist should focus on for this turn."
                            ),
                        },
                        "expected_output": {
                            "type": "string",
                            "description": (
                                "What kind of result you want back from the specialist."
                            ),
                        },
                        "intent_kind": {
                            "type": "string",
                            "enum": [intent.value for intent in allowed_intents],
                        },
                        "entities": {
                            "type": "array",
                            "description": (
                                "Structured hints extracted from the request, such as "
                                "ticker, order_ref, domain, or operation."
                            ),
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "key": {"type": "string"},
                                    "value": {"type": "string"},
                                },
                                "required": ["key", "value"],
                            },
                        },
                    },
                    "required": [
                        "task_brief",
                        "expected_output",
                        "intent_kind",
                        "entities",
                    ],
                },
                "strict": True,
            },
        }

    def _tool_description(
        self,
        *,
        specialist: BaseAgent,
        allowed_intents: tuple[IntentKind, ...],
    ) -> str:
        intents = ", ".join(intent.value for intent in allowed_intents)
        return (
            f"Delegate work to {specialist.name}. Purpose: {specialist.profile.purpose} "
            f"Capabilities: {specialist.profile.toolbox_summary} "
            f"Allowed intents: {intents}."
        )

    def _build_tool_mapping(
        self,
        request: AgentRequest,
        tool_runs: list[SpecialistToolRun],
    ) -> dict[str, Any]:
        specialists = self.specialists.by_key()
        mapping: dict[str, Any] = {}
        for tool_name, specialist_key, allowed_intents in _SPECIALIST_TOOL_CONFIGS:
            specialist = specialists.get(specialist_key)
            if specialist is None:
                continue
            mapping[tool_name] = self._build_specialist_tool(
                request=request,
                tool_runs=tool_runs,
                tool_name=tool_name,
                specialist_key=specialist_key,
                specialist=specialist,
                allowed_intents=allowed_intents,
            )
        if self.scheduled_process_service is not None:
            scheduler_mapping = build_scheduler_agent_tool_mapping(
                self.scheduled_process_service,
                default_timezone=self.scheduler_default_timezone,
                default_poll_every_seconds=self.scheduler_default_poll_every_seconds,
                chat_id=request.chat_id,
                user_id=_metadata_user_id(request.metadata),
            )
            mapping["scheduler_alpaca_news_monitor_create"] = scheduler_mapping[
                "scheduler_alpaca_news_monitor_create"
            ]
        return mapping

    def _build_specialist_tool(
        self,
        *,
        request: AgentRequest,
        tool_runs: list[SpecialistToolRun],
        tool_name: str,
        specialist_key: str,
        specialist: BaseAgent,
        allowed_intents: tuple[IntentKind, ...],
    ):
        @traceable(
            name=tool_name,
            run_type="tool"
        )
        def _delegate(
            *,
            task_brief: str,
            expected_output: str,
            intent_kind: str,
            entities: list[dict[str, str]] | None = None,
        ) -> ToolResult:
            start = time.monotonic()
            set_trace_name(tool_name)
            set_trace_metadata(
                agent_name=self.name,
                agent_step="delegate_to_specialist",
                step_kind="tool",
                tool_name=tool_name,
                specialist_key=specialist_key,
                specialist_name=specialist.name,
                intent_kind=intent_kind,
            )
            log_event(
                LOGGER,
                "agent.delegate.start",
                component="agent",
                agent_name=self.name,
                step="delegate_to_specialist",
                tool_name=tool_name,
                selected_agent=specialist.name,
                status="started",
                chat_id=request.chat_id,
                intent_kind=intent_kind,
            )
            try:
                delegation = OrchestratorDelegationRequest.model_validate(
                    {
                        "task_brief": task_brief,
                        "expected_output": expected_output,
                        "intent_kind": intent_kind,
                        "entities": entities or [],
                    }
                )
            except ValidationError as exc:
                log_event(
                    LOGGER,
                    "agent.delegate.error",
                    "warning",
                    component="agent",
                    agent_name=self.name,
                    step="delegate_to_specialist",
                    tool_name=tool_name,
                    selected_agent=specialist.name,
                    status="error",
                    chat_id=request.chat_id,
                    duration_ms=int((time.monotonic() - start) * 1000),
                    error_type=exc.__class__.__name__,
                    error_code="invalid_delegation_payload",
                )
                return ToolResult(
                    status="error",
                    error=ToolError(
                        message="Invalid routing payload for specialist delegation.",
                        code="invalid_delegation_payload",
                        hint="Provide task_brief, expected_output, intent_kind, and entities.",
                        retryable=False,
                        details={"errors": exc.errors()},
                    ),
                )
            if delegation.intent_kind not in allowed_intents:
                log_event(
                    LOGGER,
                    "agent.delegate.error",
                    "warning",
                    component="agent",
                    agent_name=self.name,
                    step="delegate_to_specialist",
                    tool_name=tool_name,
                    selected_agent=specialist.name,
                    status="error",
                    chat_id=request.chat_id,
                    duration_ms=int((time.monotonic() - start) * 1000),
                    error_code="invalid_specialist_intent",
                )
                return ToolResult(
                    status="error",
                    error=ToolError(
                        message=(
                            f"Intent '{delegation.intent_kind.value}' is not valid for "
                            f"{tool_name}."
                        ),
                        code="invalid_specialist_intent",
                        hint=(
                            "Choose one of: "
                            + ", ".join(intent.value for intent in allowed_intents)
                        ),
                        retryable=False,
                    ),
                )
            resolved_intent = delegation.to_agent_intent()
            delegated_request = request.model_copy(
                update={
                    "orchestrator_guidance": self._delegation_guidance(
                        task_brief=delegation.task_brief,
                        expected_output=delegation.expected_output,
                        existing=request.orchestrator_guidance,
                    )
                }
            )
            response = specialist.handle(delegated_request, intent=resolved_intent)
            log_event(
                LOGGER,
                "agent.delegate.end",
                component="agent",
                agent_name=self.name,
                step="delegate_to_specialist",
                tool_name=tool_name,
                selected_agent=specialist.name,
                status=response.metadata.get("workflow_status", "ok"),
                chat_id=request.chat_id,
                duration_ms=int((time.monotonic() - start) * 1000),
                intent_kind=resolved_intent.kind.value,
            )
            tool_runs.append(
                SpecialistToolRun(
                    tool_name=tool_name,
                    specialist_key=specialist_key,
                    task_brief=delegation.task_brief,
                    expected_output=delegation.expected_output,
                    intent=resolved_intent,
                    response=response,
                )
            )
            return ToolResult(
                status="ok",
                output=response.final_answer,
                data={
                    "specialist": specialist.name,
                    "task_brief": delegation.task_brief,
                    "expected_output": delegation.expected_output,
                    "intent": resolved_intent.model_dump(mode="json"),
                    "final_answer": response.final_answer,
                    "plan": (
                        response.plan.model_dump(mode="json")
                        if response.plan is not None
                        else None
                    ),
                    "metadata": response.metadata,
                    "artifacts": response.artifacts,
                },
            )

        return _delegate

    def _delegation_guidance(
        self,
        *,
        task_brief: str,
        expected_output: str,
        existing: str | None,
    ) -> str:
        guidance = (
            f"Task brief: {task_brief}\n"
            f"Expected output: {expected_output}"
        )
        if existing and existing.strip():
            return f"{existing}\n\n{guidance}"
        return guidance

    @traceable(
        name="Main Orchestrator Build Response Package",
        run_type="chain"
    )
    def _build_response_package(
        self,
        tool_runs: list[SpecialistToolRun],
    ) -> tuple[dict[str, str], dict[str, Any], Any, Any]:
        set_trace_name(f"{self.__class__.__name__}.build_response_package")
        set_trace_metadata(
            agent_name=self.name,
            agent_step="build_response_package",
            step_kind="return",
            tool_run_count=len(tool_runs),
        )
        if not tool_runs:
            return (
                {"route": "direct", "orchestrator": self.name},
                {},
                None,
                None,
            )
        last = tool_runs[-1]
        route_sequence = [run.response.selected_agent for run in tool_runs]
        metadata = dict(last.response.metadata)
        metadata.update(
            {
                "orchestrator": self.name,
                "intent": last.intent.kind.value,
                "route": last.response.selected_agent,
            }
        )
        if len(route_sequence) > 1:
            metadata["route_sequence"] = " -> ".join(route_sequence)
        set_trace_metadata(route=last.response.selected_agent, route_sequence=route_sequence)
        artifacts: dict[str, Any] = {
            "route_sequence": route_sequence,
            "orchestrator_tool_runs": [
                {
                    "tool_name": run.tool_name,
                    "specialist": run.response.selected_agent,
                    "task_brief": run.task_brief,
                    "expected_output": run.expected_output,
                    "intent": run.intent.model_dump(mode="json"),
                    "metadata": run.response.metadata,
                    "plan": (
                        run.response.plan.model_dump(mode="json")
                        if run.response.plan is not None
                        else None
                    ),
                }
                for run in tool_runs
            ],
        }
        if len(tool_runs) == 1:
            artifacts.update(dict(last.response.artifacts))
        else:
            specialist_artifacts = {
                run.response.selected_agent: dict(run.response.artifacts)
                for run in tool_runs
                if run.response.artifacts
            }
            if specialist_artifacts:
                artifacts["specialist_artifacts"] = specialist_artifacts
            if last.response.artifacts:
                for key, value in last.response.artifacts.items():
                    artifacts.setdefault(key, value)
        approval_payload = self._approval_payload(tool_runs)
        if isinstance(approval_payload, dict):
            artifacts["telegram_approval_request"] = approval_payload
        return metadata, artifacts, last.response.plan, last.response.critique

    def _approval_payload(
        self,
        tool_runs: list[SpecialistToolRun],
    ) -> dict[str, Any] | None:
        for run in reversed(tool_runs):
            approval = run.response.artifacts.get("telegram_approval_request")
            if isinstance(approval, dict):
                return approval
        return None

    def _forced_order_task_brief(self, intent: AgentIntent) -> str:
        if intent.kind == IntentKind.CANCEL_ORDER:
            return (
                "Treat this as a broker order cancellation request. Resolve the target "
                "deterministically, prepare the cancellation for Telegram approval, and "
                "avoid conversational confirmation."
            )
        return (
            "Treat this as an executable broker order request. Extract the order details, "
            "prepare the order for deterministic Telegram button approval, and avoid "
            "conversational confirmation."
        )
