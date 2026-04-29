"""Centralized agent planning and critique helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from t212ai.genai.tracing import (
    _trace_agent_critique_outputs,
    _trace_agent_plan_outputs,
    _trace_reasoner_build_plan_inputs,
    _trace_reasoner_critique_inputs,
    set_trace_metadata,
    set_trace_name,
    traceable,
)

from .history import ChatHistoryWindow
from .intents import AgentIntent, IntentKind
from .planner import AgentPlan, StructuredAgentPlan, TaskComplexity
from .prompts import (
    build_critique_system_prompt,
    build_critique_user_prompt,
    build_plan_system_prompt,
    build_plan_user_prompt,
)
from .schemas import AgentCritique

if TYPE_CHECKING:
    from t212ai.genai.client import GenAIClient


class AgentReasoner:
    def __init__(self, genai_client: "GenAIClient") -> None:
        self.genai = genai_client

    @traceable(
        name="Agent Reasoner Build Plan",
        run_type="chain",
        process_inputs=_trace_reasoner_build_plan_inputs,
        process_outputs=_trace_agent_plan_outputs,
    )
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
        persistent_guidance: str | None = None,
    ) -> AgentPlan:
        set_trace_name(f"{agent_name}.build_plan")
        set_trace_metadata(
            agent_name=agent_name,
            task_complexity=task_complexity.value,
            intent_kind=intent.kind.value if intent else None,
        )
        system_prompt = self._build_plan_prompt(
            agent_name=agent_name,
            purpose=purpose,
            guidelines=guidelines,
            toolbox_summary=toolbox_summary,
            persistent_guidance=persistent_guidance,
        )
        messages = self._build_messages(
            user_request=user_request,
            chat_history=chat_history,
            intent=intent,
        )
        model = self._model_for(task_complexity)
        result = self.genai.generate_structured(
            StructuredAgentPlan,
            system_prompt,
            messages,
            model=model,
            temperature=0.1,
        )
        structured_plan = StructuredAgentPlan.model_validate(result)
        plan = structured_plan.to_agent_plan()
        if plan.task_complexity != task_complexity:
            plan = plan.model_copy(update={"task_complexity": task_complexity})
        return plan

    @traceable(
        name="Agent Reasoner Critique",
        run_type="chain",
        process_inputs=_trace_reasoner_critique_inputs,
        process_outputs=_trace_agent_critique_outputs,
    )
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
        persistent_guidance: str | None = None,
    ) -> AgentCritique:
        set_trace_name(f"{agent_name}.critique")
        set_trace_metadata(
            agent_name=agent_name,
            task_complexity=task_complexity.value,
            critique_mode=True,
        )
        system_prompt = self._build_critique_prompt(
            agent_name=agent_name,
            purpose=purpose,
            guidelines=guidelines,
            persistent_guidance=persistent_guidance,
        )
        messages = []
        if chat_history:
            messages.extend(chat_history.to_llm_messages())
        messages.append(
            {
                "role": "user",
                "content": build_critique_user_prompt(
                    user_request=user_request,
                    agent_output=agent_output,
                    plan_payload=plan.model_dump(mode="json") if plan else None,
                ),
            }
        )
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
                "content": build_plan_user_prompt(
                    user_request=user_request,
                    intent_payload=intent_payload,
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
        persistent_guidance: str | None,
    ) -> str:
        return build_plan_system_prompt(
            agent_name=agent_name,
            purpose=purpose,
            guidelines=guidelines,
            toolbox_summary=toolbox_summary,
            persistent_guidance=persistent_guidance,
        )

    def _build_critique_prompt(
        self,
        *,
        agent_name: str,
        purpose: str,
        guidelines: str,
        persistent_guidance: str | None,
    ) -> str:
        return build_critique_system_prompt(
            agent_name=agent_name,
            purpose=purpose,
            guidelines=guidelines,
            persistent_guidance=persistent_guidance,
        )
