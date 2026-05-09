"""Grouped plan execution for configurable specialist loops."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from t212ai.app.logging import log_event
from t212ai.genai.tracing import set_trace_metadata, set_trace_name, traceable

from .planner import (
    GroupedAgentPlan,
    PlanAction,
    PlanActionGroup,
    PlanExecutionMode,
    TaskComplexity,
)
from .prompts import (
    build_final_synthesis_system_prompt,
    build_final_synthesis_user_prompt,
    build_plan_action_system_prompt,
    build_plan_action_user_prompt,
)
from .schemas import AgentInvocationContext, AgentReasoningContext

if TYPE_CHECKING:
    from t212ai.genai.client import GenAIClient
    from t212ai.genai.tools import ToolBox

LOGGER = logging.getLogger(__name__)


class PlanActionExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str
    group_id: str
    tool_name: str | None = None
    purpose: str
    status: str
    parallel_tool_calls: bool = False
    output_summary: str
    error_message: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)


class PlanActionGroupExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: str
    title: str
    execution_mode: PlanExecutionMode
    actions: list[PlanActionExecution] = Field(default_factory=list)


class GroupedPlanExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    final_answer: str
    action_summaries: list[str] = Field(default_factory=list)
    group_executions: list[PlanActionGroupExecution] = Field(default_factory=list)

    @property
    def action_count(self) -> int:
        return sum(len(group.actions) for group in self.group_executions)


class GroupedPlanExecutor:
    """Run grouped plan actions while forwarding only compact context summaries."""

    def __init__(self, genai_client: "GenAIClient") -> None:
        self.genai = genai_client

    @traceable(
        name="Grouped Plan Executor",
        run_type="chain"
    )
    def execute(
        self,
        *,
        invocation: AgentInvocationContext,
        reasoning_context: AgentReasoningContext,
        grouped_plan: GroupedAgentPlan,
        toolbox: "ToolBox",
        tools_mapping: dict[str, Callable[..., Any]],
    ) -> GroupedPlanExecutionResult:
        set_trace_name(f"{invocation.agent_name}.grouped_execute")
        set_trace_metadata(
            agent_name=invocation.agent_name,
            agent_step="execute",
            step_kind="execute",
            task_complexity=invocation.task_complexity.value,
            intent_kind=invocation.intent.kind.value,
            group_count=len(grouped_plan.action_groups),
        )
        start = time.monotonic()
        log_event(
            LOGGER,
            "agent.execute.start",
            component="agent",
            agent_name=invocation.agent_name,
            step="execute",
            status="started",
            intent_kind=invocation.intent.kind.value,
            group_count=len(grouped_plan.action_groups),
        )
        completed_by_id: dict[str, PlanActionExecution] = {}
        forwarded_summaries: list[str] = []
        group_executions: list[PlanActionGroupExecution] = []

        for group in grouped_plan.action_groups:
            group_start_summaries = list(forwarded_summaries)
            current_group_summaries: list[str] = []
            action_executions: list[PlanActionExecution] = []
            for action in group.actions:
                visible_summaries = (
                    group_start_summaries
                    if group.execution_mode == PlanExecutionMode.PARALLEL
                    else forwarded_summaries
                )
                execution = self._execute_action(
                    invocation=invocation,
                    reasoning_context=reasoning_context,
                    group=group,
                    action=action,
                    grouped_plan=grouped_plan,
                    toolbox=toolbox,
                    tools_mapping=tools_mapping,
                    forwarded_summaries=visible_summaries,
                    completed_by_id=completed_by_id,
                )
                completed_by_id[action.action_id] = execution
                action_executions.append(execution)
                summary = _format_forwarded_summary(execution)
                current_group_summaries.append(summary)
                if group.execution_mode == PlanExecutionMode.SEQUENTIAL:
                    forwarded_summaries.append(summary)

            if group.execution_mode == PlanExecutionMode.PARALLEL:
                forwarded_summaries.extend(current_group_summaries)
            group_executions.append(
                PlanActionGroupExecution(
                    group_id=group.group_id,
                    title=group.title,
                    execution_mode=group.execution_mode,
                    actions=action_executions,
                )
            )

        if _plan_has_final_synthesis(grouped_plan) and forwarded_summaries:
            final_answer = completed_by_id[
                grouped_plan.action_groups[-1].actions[-1].action_id
            ].output_summary
        else:
            final_answer = self._run_final_synthesis(
                invocation=invocation,
                reasoning_context=reasoning_context,
                grouped_plan=grouped_plan,
                forwarded_summaries=forwarded_summaries,
            )

        status = "ok"
        if any(action.status == "error" for group in group_executions for action in group.actions):
            status = "partial"
        if not group_executions:
            status = "ok" if final_answer.strip() else "error"
        result = GroupedPlanExecutionResult(
            status=status,
            final_answer=final_answer.strip(),
            action_summaries=list(forwarded_summaries),
            group_executions=group_executions,
        )
        log_event(
            LOGGER,
            "agent.execute.end",
            component="agent",
            agent_name=invocation.agent_name,
            step="execute",
            status=result.status,
            duration_ms=int((time.monotonic() - start) * 1000),
            group_count=len(result.group_executions),
            action_count=result.action_count,
        )
        return result

    @traceable(
        name="Plan Action Execution",
        run_type="chain"
    )
    def _execute_action(
        self,
        *,
        invocation: AgentInvocationContext,
        reasoning_context: AgentReasoningContext,
        group: PlanActionGroup,
        action: PlanAction,
        grouped_plan: GroupedAgentPlan,
        toolbox: "ToolBox",
        tools_mapping: dict[str, Callable[..., Any]],
        forwarded_summaries: list[str],
        completed_by_id: dict[str, PlanActionExecution],
    ) -> PlanActionExecution:
        set_trace_name(f"{invocation.agent_name}.execute.{action.action_id}")
        set_trace_metadata(
            agent_name=invocation.agent_name,
            agent_step="execute_action",
            step_kind="execute_action",
            action_id=action.action_id,
            group_id=group.group_id,
            tool_name=action.tool_name,
            risk_class=action.risk_class,
            execution_mode=group.execution_mode.value,
        )
        start = time.monotonic()
        log_event(
            LOGGER,
            "agent.action.start",
            component="agent",
            agent_name=invocation.agent_name,
            step="execute_action",
            status="started",
            action_id=action.action_id,
            group_id=group.group_id,
            tool_name=action.tool_name,
            risk_class=action.risk_class,
        )
        parallel_tool_calls = _parallel_tool_calls_for(group=group, action=action)
        if action.tool_name and action.tool_name not in toolbox.tools_by_name:
            message = f"Planned tool '{action.tool_name}' is not available."
            log_event(
                LOGGER,
                "agent.action.error",
                "warning",
                component="agent",
                agent_name=invocation.agent_name,
                step="execute_action",
                status="error",
                action_id=action.action_id,
                group_id=group.group_id,
                tool_name=action.tool_name,
                duration_ms=int((time.monotonic() - start) * 1000),
                error_code="tool_not_allowed",
            )
            return PlanActionExecution(
                action_id=action.action_id,
                group_id=group.group_id,
                tool_name=action.tool_name,
                purpose=action.purpose,
                status="error",
                parallel_tool_calls=False,
                output_summary=message,
                error_message="tool_not_allowed",
            )

        dependency_summaries = [
            _format_forwarded_summary(completed_by_id[dependency])
            for dependency in action.depends_on
            if dependency in completed_by_id
        ]
        system_prompt = build_plan_action_system_prompt(
            agent_name=invocation.agent_name,
            purpose=invocation.purpose,
            guidelines=invocation.guidelines,
            toolbox_summary=invocation.toolbox_summary,
            persistent_guidance=invocation.persistent_guidance,
        )
        messages = _action_messages(
            invocation=invocation,
            reasoning_context=reasoning_context,
            group=group,
            action=action,
            dependency_summaries=dependency_summaries,
            forwarded_summaries=forwarded_summaries,
        )
        use_tools = bool(action.tool_name)
        handle_kwargs: dict[str, Any] = {}
        if use_tools:
            handle_kwargs["toolbox"] = toolbox
            handle_kwargs["parallel_tool_calls"] = parallel_tool_calls
        params = self.genai.handle_params(
            system_prompt,
            messages,
            model=_model_for(self.genai, invocation.task_complexity),
            temperature=0.1,
            **handle_kwargs,
        )
        try:
            response = self.genai.call_openai(
                params,
                tools_mapping=tools_mapping if use_tools else None,
                toolbox=toolbox if use_tools else None,
            )
            output_summary = _assistant_text(response).strip()
            if not output_summary:
                output_summary = "Action completed but returned no assistant summary."
            execution = PlanActionExecution(
                action_id=action.action_id,
                group_id=group.group_id,
                tool_name=action.tool_name,
                purpose=action.purpose,
                status="ok",
                parallel_tool_calls=parallel_tool_calls,
                output_summary=output_summary,
                tool_calls=_summarize_tool_messages(params.get("messages")),
            )
            log_event(
                LOGGER,
                "agent.action.end",
                component="agent",
                agent_name=invocation.agent_name,
                step="execute_action",
                status=execution.status,
                action_id=action.action_id,
                group_id=group.group_id,
                tool_name=action.tool_name,
                duration_ms=int((time.monotonic() - start) * 1000),
                tool_call_count=len(execution.tool_calls),
            )
            return execution
        except Exception as exc:  # pragma: no cover - safety net for live providers
            message = f"Action failed: {exc.__class__.__name__}: {exc}"
            log_event(
                LOGGER,
                "agent.action.error",
                "error",
                component="agent",
                agent_name=invocation.agent_name,
                step="execute_action",
                status="error",
                action_id=action.action_id,
                group_id=group.group_id,
                tool_name=action.tool_name,
                duration_ms=int((time.monotonic() - start) * 1000),
                error_type=exc.__class__.__name__,
            )
            return PlanActionExecution(
                action_id=action.action_id,
                group_id=group.group_id,
                tool_name=action.tool_name,
                purpose=action.purpose,
                status="error",
                parallel_tool_calls=parallel_tool_calls,
                output_summary=message,
                error_message=str(exc),
                tool_calls=_summarize_tool_messages(params.get("messages")),
            )

    @traceable(
        name="Final Synthesis",
        run_type="chain"
    )
    def _run_final_synthesis(
        self,
        *,
        invocation: AgentInvocationContext,
        reasoning_context: AgentReasoningContext,
        grouped_plan: GroupedAgentPlan,
        forwarded_summaries: list[str],
    ) -> str:
        set_trace_name(f"{invocation.agent_name}.return")
        set_trace_metadata(
            agent_name=invocation.agent_name,
            agent_step="return",
            step_kind="return",
            task_complexity=invocation.task_complexity.value,
            intent_kind=invocation.intent.kind.value,
            action_summary_count=len(forwarded_summaries),
        )
        system_prompt = build_final_synthesis_system_prompt(
            agent_name=invocation.agent_name,
            purpose=invocation.purpose,
            guidelines=invocation.guidelines,
            persistent_guidance=invocation.persistent_guidance,
        )
        messages = _base_context_messages(
            invocation=invocation,
            reasoning_context=reasoning_context,
            forwarded_summaries=forwarded_summaries,
        )
        messages.append(
            {
                "role": "user",
                "content": build_final_synthesis_user_prompt(
                    user_request=invocation.user_request,
                    reasoning_context_payload=reasoning_context.model_dump(mode="json"),
                    grouped_plan_payload=grouped_plan.model_dump(mode="json"),
                    action_summaries=forwarded_summaries,
                ),
            }
        )
        params = self.genai.handle_params(
            system_prompt,
            messages,
            model=_model_for(self.genai, invocation.task_complexity),
            temperature=0.1,
        )
        response = self.genai.call_openai(params, tools_mapping=None, toolbox=None)
        return _assistant_text(response) or "I could not synthesize a market answer."


def _action_messages(
    *,
    invocation: AgentInvocationContext,
    reasoning_context: AgentReasoningContext,
    group: PlanActionGroup,
    action: PlanAction,
    dependency_summaries: list[str],
    forwarded_summaries: list[str],
) -> list[dict[str, str]]:
    messages = _base_context_messages(
        invocation=invocation,
        reasoning_context=reasoning_context,
        forwarded_summaries=forwarded_summaries,
    )
    messages.append(
        {
            "role": "user",
            "content": build_plan_action_user_prompt(
                user_request=invocation.user_request,
                reasoning_context_payload=reasoning_context.model_dump(mode="json"),
                group_payload={
                    "group_id": group.group_id,
                    "title": group.title,
                    "execution_mode": group.execution_mode.value,
                },
                action_payload=action.model_dump(mode="json"),
                dependency_summaries=dependency_summaries,
            ),
        }
    )
    return messages


def _base_context_messages(
    *,
    invocation: AgentInvocationContext,
    reasoning_context: AgentReasoningContext,
    forwarded_summaries: list[str],
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if invocation.chat_history is not None:
        messages.extend(invocation.chat_history.to_llm_messages())
    messages.append(
        {
            "role": "assistant",
            "content": (
                "Reasoning context for this planned execution: "
                f"{reasoning_context.model_dump(mode='json')}"
            ),
        }
    )
    for summary in forwarded_summaries:
        messages.append({"role": "assistant", "content": summary})
    return messages


def _parallel_tool_calls_for(*, group: PlanActionGroup, action: PlanAction) -> bool:
    risk_class = str(action.risk_class or "").strip().lower().replace("-", "_")
    if group.execution_mode != PlanExecutionMode.PARALLEL:
        return False
    if not action.tool_name:
        return False
    if risk_class != "read_only":
        return False
    if str(action.tool_name).lower().startswith("broker_"):
        return False
    return True


def _plan_has_final_synthesis(grouped_plan: GroupedAgentPlan) -> bool:
    if not grouped_plan.action_groups:
        return False
    last_group = grouped_plan.action_groups[-1]
    if not last_group.actions:
        return False
    last_action = last_group.actions[-1]
    purpose = str(last_action.purpose or "").lower()
    if last_action.tool_name:
        return False
    return any(word in purpose for word in ("synth", "final", "answer", "summar"))


def _format_forwarded_summary(execution: PlanActionExecution) -> str:
    prefix = f"Completed action {execution.action_id} ({execution.status})"
    if execution.tool_name:
        prefix = f"{prefix} using {execution.tool_name}"
    return f"{prefix}: {execution.output_summary}"


def _summarize_tool_messages(messages: Any) -> list[dict[str, Any]]:
    if not isinstance(messages, list):
        return []
    summaries: list[dict[str, Any]] = []
    pending_names: dict[str, str | None] = {}
    for message in messages:
        if not isinstance(message, dict):
            continue
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            for call in tool_calls:
                if not isinstance(call, dict):
                    continue
                call_id = str(call.get("id") or "")
                fn = call.get("function") or {}
                pending_names[call_id] = fn.get("name")
        if message.get("role") != "tool":
            continue
        content = message.get("content")
        parsed = _parse_tool_content(content)
        call_id = str(message.get("tool_call_id") or "")
        entry: dict[str, Any] = {
            "tool_call_id": call_id or None,
            "tool_name": pending_names.get(call_id),
            "status": parsed.get("status"),
        }
        data = parsed.get("data")
        if isinstance(data, dict):
            entry["data_keys"] = sorted(str(key) for key in data.keys())[:12]
            telegram_approval = data.get("telegramApproval")
            if isinstance(telegram_approval, dict):
                entry["telegramApproval"] = telegram_approval
            pending_action = data.get("pendingAction")
            if isinstance(pending_action, dict):
                entry["pendingAction"] = {
                    key: pending_action.get(key)
                    for key in ("action_id", "actionId", "kind", "status")
                    if pending_action.get(key) is not None
                }
        error = parsed.get("error")
        if isinstance(error, dict):
            entry["error_code"] = error.get("code")
            entry["error_message"] = error.get("message")
            if error.get("hint"):
                entry["error_hint"] = _trim(str(error.get("hint")))
        output = parsed.get("output")
        if isinstance(output, str) and output.strip():
            entry["output_preview"] = _trim(output)
        summaries.append(entry)
    return summaries


def _parse_tool_content(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        try:
            import json

            parsed = json.loads(content)
        except Exception:
            return {"status": "unknown", "output": _trim(content)}
        if isinstance(parsed, dict):
            return parsed
        return {"status": "unknown", "output": _trim(str(parsed))}
    return {"status": "unknown"}


def _trim(value: str, limit: int = 240) -> str:
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "... [truncated]"


def _assistant_text(response: Any) -> str:
    try:
        message = response.choices[0].message
    except Exception:
        return ""
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str) and item.strip():
                chunks.append(item.strip())
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
        return "\n".join(chunks).strip()
    return "" if content is None else str(content).strip()


def _model_for(genai: "GenAIClient", task_complexity: TaskComplexity) -> str | None:
    if task_complexity == TaskComplexity.REASONING:
        return genai.chat_model_for("reasoning")
    if task_complexity in {TaskComplexity.COMPLEX, TaskComplexity.CRITICAL}:
        return genai.chat_model_for("smart")
    return genai.chat_model_for("default")
