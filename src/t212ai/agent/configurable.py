"""Configurable reason and plan components for the target agent loop."""

from __future__ import annotations

from typing import TYPE_CHECKING

from t212ai.genai.tracing import set_trace_metadata, set_trace_name, traceable

from .planner import GroupedAgentPlan, TaskComplexity
from .prompts import (
    build_grouped_plan_system_prompt,
    build_grouped_plan_user_prompt,
    build_reasoning_context_system_prompt,
    build_reasoning_context_user_prompt,
)
from .schemas import AgentInvocationContext, AgentReasoningContext

if TYPE_CHECKING:
    from t212ai.genai.client import GenAIClient


class ConfigurableReasonerAgent:
    """Reusable no-tool reason step for configurable specialist loops."""

    def __init__(self, genai_client: "GenAIClient") -> None:
        self.genai = genai_client
        self.name = "configurable_reasoner_agent"

    @traceable(
        name="Configurable Reasoner Reason",
        run_type="chain"
    )
    def reason(self, invocation: AgentInvocationContext) -> AgentReasoningContext:
        set_trace_name(f"{invocation.agent_name}.reason")
        set_trace_metadata(
            agent_name=invocation.agent_name,
            agent_step="reason",
            step_kind="reason",
            task_complexity=invocation.task_complexity.value,
            intent_kind=invocation.intent.kind.value,
        )
        system_prompt = build_reasoning_context_system_prompt(
            agent_name=invocation.agent_name,
            purpose=invocation.purpose,
            guidelines=invocation.guidelines,
            toolbox_summary=invocation.toolbox_summary,
            tool_descriptions=invocation.tool_descriptions,
            flow_guidelines=invocation.reasoning_guidelines,
            examples=invocation.reasoning_examples,
            persistent_guidance=invocation.persistent_guidance,
        )
        messages = _messages_with_history(
            invocation,
            build_reasoning_context_user_prompt(
                user_request=invocation.user_request,
                invocation_reason=invocation.invocation_reason,
                intent_payload=invocation.intent.model_dump(mode="json"),
            ),
        )
        result = self.genai.generate_structured(
            AgentReasoningContext,
            system_prompt,
            messages,
            model=_model_for(self.genai, invocation.task_complexity),
            temperature=0.0,
        )
        return AgentReasoningContext.model_validate(result)


class ConfigurablePlannerAgent:
    """Reusable no-tool grouped plan step for configurable specialist loops."""

    def __init__(self, genai_client: "GenAIClient") -> None:
        self.genai = genai_client
        self.name = "configurable_planner_agent"

    @traceable(
        name="Configurable Planner Plan",
        run_type="chain"
    )
    def plan(
        self,
        invocation: AgentInvocationContext,
        *,
        reasoning_context: AgentReasoningContext,
    ) -> GroupedAgentPlan:
        set_trace_name(f"{invocation.agent_name}.plan")
        set_trace_metadata(
            agent_name=invocation.agent_name,
            agent_step="plan",
            step_kind="plan",
            task_complexity=invocation.task_complexity.value,
            intent_kind=invocation.intent.kind.value,
        )
        system_prompt = build_grouped_plan_system_prompt(
            agent_name=invocation.agent_name,
            purpose=invocation.purpose,
            guidelines=invocation.guidelines,
            toolbox_summary=invocation.toolbox_summary,
            tool_descriptions=invocation.tool_descriptions,
            flow_guidelines=invocation.planning_guidelines,
            examples=invocation.planning_examples,
            persistent_guidance=invocation.persistent_guidance,
        )
        messages = _messages_with_history(
            invocation,
            build_grouped_plan_user_prompt(
                user_request=invocation.user_request,
                invocation_reason=invocation.invocation_reason,
                intent_payload=invocation.intent.model_dump(mode="json"),
                reasoning_context_payload=reasoning_context.model_dump(mode="json"),
            ),
        )
        result = self.genai.generate_structured(
            GroupedAgentPlan,
            system_prompt,
            messages,
            model=_model_for(self.genai, invocation.task_complexity),
            temperature=0.0,
        )
        plan = GroupedAgentPlan.model_validate(result)
        if plan.task_complexity != invocation.task_complexity:
            plan = plan.model_copy(update={"task_complexity": invocation.task_complexity})
        return plan


def _messages_with_history(
    invocation: AgentInvocationContext,
    user_prompt: str,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if invocation.chat_history is not None:
        messages.extend(invocation.chat_history.to_llm_messages())
    messages.append({"role": "user", "content": user_prompt})
    return messages


def _model_for(genai: "GenAIClient", task_complexity: TaskComplexity) -> str | None:
    if task_complexity == TaskComplexity.REASONING:
        return genai.chat_model_for("reasoning")
    if task_complexity in {TaskComplexity.COMPLEX, TaskComplexity.CRITICAL}:
        return genai.chat_model_for("smart")
    return genai.chat_model_for("default")
