"""Base classes for purpose-defined agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from t212ai.guidelines.service import GuidelineMemoryService
from t212ai.genai.tracing import (
    _trace_agent_execute_inputs,
    _trace_agent_handle_inputs,
    _trace_agent_plan_outputs,
    _trace_agent_response_outputs,
    set_trace_metadata,
    set_trace_name,
    traceable,
)

from .history import ChatHistoryWindow
from .intents import AgentIntent, IntentKind
from .planner import AgentPlan, TaskComplexity
from .reasoning import AgentReasoner
from .schemas import AgentRequest, AgentResponse

if TYPE_CHECKING:
    from t212ai.genai.tools import ToolBox


@dataclass(slots=True)
class AgentProfile:
    name: str
    purpose: str
    guidelines: str
    toolbox_summary: str
    task_complexity: TaskComplexity = TaskComplexity.EASY
    guideline_scopes: tuple[str, ...] = ("global",)
    guideline_include_categories: tuple[str, ...] = ()
    toolbox: "ToolBox | None" = None


class BaseAgent:
    profile: AgentProfile

    def __init__(
        self,
        reasoner: AgentReasoner,
        profile: AgentProfile,
        *,
        guideline_service: GuidelineMemoryService | None = None,
    ) -> None:
        self.reasoner = reasoner
        self.profile = profile
        self.guideline_service = guideline_service

    @property
    def name(self) -> str:
        return self.profile.name

    @traceable(
        name="Agent Handle",
        run_type="chain"
    )
    def handle(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent | None = None,
        task_complexity: TaskComplexity | None = None,
    ) -> AgentResponse:
        resolved_intent = intent or AgentIntent(kind=IntentKind.UNKNOWN)
        complexity = task_complexity or self.resolve_complexity(request.user_message)
        set_trace_name(f"{self.__class__.__name__}.handle")
        set_trace_metadata(
            agent_name=self.name,
            agent_kind="specialist",
            intent_kind=resolved_intent.kind.value,
            task_complexity=complexity.value,
        )
        plan = self.plan(
            request,
            intent=resolved_intent,
            task_complexity=complexity,
        )
        execution_response = self.execute(
            request,
            intent=resolved_intent,
            task_complexity=complexity,
            plan=plan,
        )
        if execution_response is not None:
            if execution_response.plan is None:
                execution_response = execution_response.model_copy(update={"plan": plan})
            execution_response.metadata.setdefault("agent", self.name)
            execution_response.metadata.setdefault("task_complexity", complexity.value)
            return execution_response
        return AgentResponse(
            final_answer=self._format_plan_response(plan),
            selected_agent=self.name,
            plan=plan,
            metadata={"agent": self.name, "task_complexity": complexity.value},
        )

    @traceable(
        name="Agent Plan",
        run_type="chain",
        process_inputs=_trace_agent_handle_inputs,
        process_outputs=_trace_agent_plan_outputs,
    )
    def plan(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent,
        task_complexity: TaskComplexity,
    ) -> AgentPlan:
        set_trace_name(f"{self.__class__.__name__}.plan")
        set_trace_metadata(
            agent_name=self.name,
            intent_kind=intent.kind.value,
            task_complexity=task_complexity.value,
        )
        return self.reasoner.build_plan(
            agent_name=self.profile.name,
            purpose=self.profile.purpose,
            guidelines=self.profile.guidelines,
            toolbox_summary=self.profile.toolbox_summary,
            task_complexity=task_complexity,
            user_request=request.user_message,
            chat_history=self._history_for_prompt(request.history),
            intent=intent,
            orchestrator_guidance=request.orchestrator_guidance,
            persistent_guidance=self._persistent_guidance(),
        )

    def resolve_complexity(self, message: str) -> TaskComplexity:
        del message
        return self.profile.task_complexity

    @traceable(
        name="Agent Execute",
        run_type="chain",
        process_inputs=_trace_agent_execute_inputs,
        process_outputs=_trace_agent_response_outputs,
    )
    def execute(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent,
        task_complexity: TaskComplexity,
        plan: AgentPlan,
    ) -> AgentResponse | None:
        set_trace_name(f"{self.__class__.__name__}.execute")
        set_trace_metadata(
            agent_name=self.name,
            agent_step="execute",
            step_kind="execute",
            intent_kind=intent.kind.value,
            task_complexity=task_complexity.value,
        )
        del request, plan
        return None

    def _history_for_prompt(
        self,
        history: ChatHistoryWindow | None,
    ) -> ChatHistoryWindow | None:
        return history

    def _format_plan_response(self, plan: AgentPlan) -> str:
        missing = (
            f" Missing inputs: {', '.join(plan.missing_inputs)}."
            if plan.missing_inputs
            else ""
        )
        approval = " Approval is required." if plan.requires_approval else ""
        return f"{self.name} prepared a plan: {plan.summary}.{missing}{approval}"

    def _persistent_guidance(self) -> str | None:
        if self.guideline_service is None:
            return None
        rendered = self.guideline_service.render_markdown(
            scopes=list(self.profile.guideline_scopes),
            include_categories=list(self.profile.guideline_include_categories),
            active_only=True,
        )
        return rendered or None
