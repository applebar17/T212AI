"""Configurable reason and plan components for the target agent loop."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
        run_type="chain",
        process_inputs=lambda *args, **kwargs: _trace_invocation_inputs(
            *args, **kwargs
        ),
        process_outputs=lambda output: _trace_reasoning_context_outputs(output),
    )
    def reason(self, invocation: AgentInvocationContext) -> AgentReasoningContext:
        set_trace_name(f"{self.__class__.__name__}.reason")
        set_trace_metadata(
            agent_name=invocation.agent_name,
            task_complexity=invocation.task_complexity.value,
            intent_kind=invocation.intent.kind.value,
        )
        system_prompt = build_reasoning_context_system_prompt(
            agent_name=invocation.agent_name,
            purpose=invocation.purpose,
            guidelines=invocation.guidelines,
            toolbox_summary=invocation.toolbox_summary,
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
        run_type="chain",
        process_inputs=lambda *args, **kwargs: _trace_planner_inputs(
            *args, **kwargs
        ),
        process_outputs=lambda output: _trace_grouped_plan_outputs(output),
    )
    def plan(
        self,
        invocation: AgentInvocationContext,
        *,
        reasoning_context: AgentReasoningContext,
    ) -> GroupedAgentPlan:
        set_trace_name(f"{self.__class__.__name__}.plan")
        set_trace_metadata(
            agent_name=invocation.agent_name,
            task_complexity=invocation.task_complexity.value,
            intent_kind=invocation.intent.kind.value,
        )
        system_prompt = build_grouped_plan_system_prompt(
            agent_name=invocation.agent_name,
            purpose=invocation.purpose,
            guidelines=invocation.guidelines,
            toolbox_summary=invocation.toolbox_summary,
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


def _trace_invocation_inputs(*args: Any, **kwargs: Any) -> dict[str, Any]:
    invocation = _extract_invocation(args, kwargs)
    if invocation is None:
        return {"invocation": None}
    return {
        "agent_name": invocation.agent_name,
        "task_complexity": invocation.task_complexity.value,
        "intent_kind": invocation.intent.kind.value,
        "user_request_chars": len(invocation.user_request),
        "invocation_reason_chars": len(invocation.invocation_reason),
        "history_messages": (
            len(invocation.chat_history.messages)
            if invocation.chat_history is not None
            else 0
        ),
        "toolbox_summary_chars": len(invocation.toolbox_summary),
        "has_persistent_guidance": bool(invocation.persistent_guidance),
    }


def _trace_planner_inputs(*args: Any, **kwargs: Any) -> dict[str, Any]:
    summary = _trace_invocation_inputs(*args, **kwargs)
    reasoning_context = kwargs.get("reasoning_context")
    if reasoning_context is not None:
        summary["reasoning_context"] = {
            "known_facts": len(getattr(reasoning_context, "known_facts", []) or []),
            "ambiguities": len(getattr(reasoning_context, "ambiguities", []) or []),
            "required_evidence": len(
                getattr(reasoning_context, "required_evidence", []) or []
            ),
            "can_proceed": getattr(reasoning_context, "can_proceed", None),
        }
    return summary


def _trace_reasoning_context_outputs(output: Any) -> dict[str, Any]:
    if output is None:
        return {"output_type": None}
    return {
        "task_interpretation_chars": len(
            getattr(output, "task_interpretation", "") or ""
        ),
        "known_facts": len(getattr(output, "known_facts", []) or []),
        "ambiguities": len(getattr(output, "ambiguities", []) or []),
        "required_evidence": len(getattr(output, "required_evidence", []) or []),
        "safety_constraints": len(getattr(output, "safety_constraints", []) or []),
        "can_proceed": getattr(output, "can_proceed", None),
        "confidence": getattr(output, "confidence", None),
    }


def _trace_grouped_plan_outputs(output: Any) -> dict[str, Any]:
    if output is None:
        return {"output_type": None}
    groups = getattr(output, "action_groups", []) or []
    action_count = sum(len(getattr(group, "actions", []) or []) for group in groups)
    return {
        "summary_chars": len(getattr(output, "summary", "") or ""),
        "group_count": len(groups),
        "action_count": action_count,
        "requires_approval": getattr(output, "requires_approval", None),
        "task_complexity": getattr(
            getattr(output, "task_complexity", None), "value", None
        ),
    }


def _extract_invocation(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> AgentInvocationContext | None:
    invocation = kwargs.get("invocation")
    if isinstance(invocation, AgentInvocationContext):
        return invocation
    for arg in args:
        if isinstance(arg, AgentInvocationContext):
            return arg
    return None
