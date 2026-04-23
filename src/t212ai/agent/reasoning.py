"""Centralized agent planning and critique helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from .history import ChatHistoryWindow
from .intents import AgentIntent, IntentKind
from .planner import AgentPlan, TaskComplexity
from .schemas import AgentCritique

if TYPE_CHECKING:
    from t212ai.genai.client import GenAIClient


class AgentReasoner:
    def __init__(self, genai_client: "GenAIClient") -> None:
        self.genai = genai_client

    def build_plan(
        self,
        *,
        agent_name: str,
        purpose: str,
        guidelines: str,
        toolbox_summary: str,
        task_complexity: TaskComplexity,
        user_request: str,
        chat_history: ChatHistoryWindow | None = None,
        intent: AgentIntent | None = None,
    ) -> AgentPlan:
        system_prompt = self._build_plan_prompt(
            agent_name=agent_name,
            purpose=purpose,
            guidelines=guidelines,
            toolbox_summary=toolbox_summary,
        )
        messages = self._build_messages(
            user_request=user_request,
            chat_history=chat_history,
            intent=intent,
        )
        model = self._model_for(task_complexity)
        result = self.genai.generate_structured(
            AgentPlan,
            system_prompt,
            messages,
            model=model,
            temperature=0.1,
        )
        plan = AgentPlan.model_validate(result)
        if plan.task_complexity != task_complexity:
            plan = plan.model_copy(update={"task_complexity": task_complexity})
        return plan

    def critique(
        self,
        *,
        agent_name: str,
        purpose: str,
        guidelines: str,
        user_request: str,
        agent_output: str,
        plan: AgentPlan | None = None,
        chat_history: ChatHistoryWindow | None = None,
        task_complexity: TaskComplexity = TaskComplexity.CRITICAL,
    ) -> AgentCritique:
        system_prompt = self._build_critique_prompt(
            agent_name=agent_name,
            purpose=purpose,
            guidelines=guidelines,
        )
        payload: dict[str, Any] = {
            "user_request": user_request,
            "agent_output": agent_output,
            "plan": plan.model_dump(mode="json") if plan else None,
        }
        messages = []
        if chat_history:
            messages.extend(chat_history.to_llm_messages())
        messages.append({"role": "user", "content": str(payload)})
        result = self.genai.generate_structured(
            AgentCritique,
            system_prompt,
            messages,
            model=self._model_for(task_complexity),
            temperature=0.0,
        )
        return AgentCritique.model_validate(result)

    def _model_for(self, task_complexity: TaskComplexity) -> str | None:
        if task_complexity == TaskComplexity.REASONING:
            return self.genai.chat_model_for("reasoning")
        if task_complexity in {TaskComplexity.COMPLEX, TaskComplexity.CRITICAL}:
            return self.genai.chat_model_for("smart")
        return self.genai.chat_model_for("default")

    def _build_messages(
        self,
        *,
        user_request: str,
        chat_history: ChatHistoryWindow | None,
        intent: AgentIntent | None,
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if chat_history:
            messages.extend(chat_history.to_llm_messages())
        intent_payload = (
            intent.model_dump(mode="json")
            if intent
            else AgentIntent(kind=IntentKind.UNKNOWN).model_dump(mode="json")
        )
        messages.append(
            {
                "role": "user",
                "content": (
                    "Create a structured action plan.\n"
                    f"Intent: {intent_payload}\n"
                    f"User request: {user_request}"
                ),
            }
        )
        return messages

    def _build_plan_prompt(
        self,
        *,
        agent_name: str,
        purpose: str,
        guidelines: str,
        toolbox_summary: str,
    ) -> str:
        return (
            f"You are {agent_name}.\n"
            f"Purpose: {purpose}\n\n"
            "Return only the structured AgentPlan schema. Do not include hidden reasoning. "
            "Use explicit assumptions, required_context, tool_steps, risks, and "
            "missing_inputs to make the plan auditable.\n\n"
            f"Available capability/toolbox summary:\n{toolbox_summary}\n\n"
            f"Agent-specific guidelines:\n{guidelines}"
        )

    def _build_critique_prompt(
        self,
        *,
        agent_name: str,
        purpose: str,
        guidelines: str,
    ) -> str:
        return (
            f"You are judging work from {agent_name}.\n"
            f"Agent purpose: {purpose}\n"
            "Return only the structured AgentCritique schema. Check whether the "
            "answer is complete, safe, grounded in available context, and clear. "
            "Do not expose hidden reasoning; use concise findings.\n\n"
            f"Judge guidelines:\n{guidelines}"
        )
