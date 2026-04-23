"""Base classes for purpose-defined agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

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
    toolbox: "ToolBox | None" = None


class BaseAgent:
    profile: AgentProfile

    def __init__(self, reasoner: AgentReasoner, profile: AgentProfile) -> None:
        self.reasoner = reasoner
        self.profile = profile

    @property
    def name(self) -> str:
        return self.profile.name

    def handle(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent | None = None,
        task_complexity: TaskComplexity | None = None,
    ) -> AgentResponse:
        resolved_intent = intent or AgentIntent(kind=IntentKind.UNKNOWN)
        complexity = task_complexity or self.resolve_complexity(request.user_message)
        plan = self.plan(
            request,
            intent=resolved_intent,
            task_complexity=complexity,
        )
        return AgentResponse(
            final_answer=self._format_plan_response(plan),
            selected_agent=self.name,
            plan=plan,
            metadata={"agent": self.name, "task_complexity": complexity.value},
        )

    def plan(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent,
        task_complexity: TaskComplexity,
    ) -> AgentPlan:
        return self.reasoner.build_plan(
            agent_name=self.profile.name,
            purpose=self.profile.purpose,
            guidelines=self.profile.guidelines,
            toolbox_summary=self.profile.toolbox_summary,
            task_complexity=task_complexity,
            user_request=request.user_message,
            chat_history=self._history_for_prompt(request.history),
            intent=intent,
        )

    def resolve_complexity(self, message: str) -> TaskComplexity:
        del message
        return self.profile.task_complexity

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
