"""Centralized agent planning and critique helpers."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Callable

from t212ai.app.logging import log_event
from t212ai.genai.tracing import (
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
    build_orchestrator_manager_system_prompt,
    build_orchestrator_manager_user_prompt,
    build_plan_system_prompt,
    build_plan_user_prompt,
)
from .schemas import AgentCritique

if TYPE_CHECKING:
    from t212ai.genai.client import GenAIClient
    from t212ai.genai.tools.base import ToolBox

LOGGER = logging.getLogger(__name__)


class AgentReasoner:
    def __init__(self, genai_client: "GenAIClient") -> None:
        self.genai = genai_client

    @traceable(
        name="Agent Reasoner Build Plan",
        run_type="chain"
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
        orchestrator_guidance: str | None = None,
        persistent_guidance: str | None = None,
    ) -> AgentPlan:
        set_trace_name(f"{agent_name}.build_plan")
        set_trace_metadata(
            agent_name=agent_name,
            task_complexity=task_complexity.value,
            intent_kind=intent.kind.value if intent else None,
        )
        start = time.monotonic()
        log_event(
            LOGGER,
            "agent.plan.start",
            component="agent",
            agent_name=agent_name,
            step="build_plan",
            status="started",
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
            orchestrator_guidance=orchestrator_guidance,
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
        log_event(
            LOGGER,
            "agent.plan.end",
            component="agent",
            agent_name=agent_name,
            step="build_plan",
            status="ok",
            duration_ms=int((time.monotonic() - start) * 1000),
            step_count=len(plan.tool_steps),
        )
        return plan

    @traceable(
        name="Agent Reasoner Critique",
        run_type="chain"
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

    def orchestrate_with_tools(
        self,
        *,
        agent_name: str,
        purpose: str,
        guidelines: str,
        toolbox_summary: str,
        user_request: str,
        toolbox: "ToolBox",
        tools_mapping: dict[str, Callable[..., Any]],
        chat_history: ChatHistoryWindow | None = None,
        persistent_guidance: str | None = None,
        max_tool_calls: int | None = None,
    ) -> str:
        start = time.monotonic()
        log_event(
            LOGGER,
            "agent.tool_orchestration.start",
            component="agent",
            agent_name=agent_name,
            step="orchestrate_with_tools",
            status="started",
            tool_count=len(toolbox.tools),
        )
        system_prompt = build_orchestrator_manager_system_prompt(
            agent_name=agent_name,
            purpose=purpose,
            guidelines=guidelines,
            toolbox_summary=toolbox_summary,
            persistent_guidance=persistent_guidance,
        )
        messages: list[dict[str, str]] = []
        if chat_history:
            messages.extend(chat_history.to_llm_messages())
        messages.append(
            {
                "role": "user",
                "content": build_orchestrator_manager_user_prompt(
                    user_request=user_request
                ),
            }
        )
        params = self.genai.handle_params(
            system_prompt,
            messages,
            model=self.genai.chat_model_for("smart"),
            temperature=0.1,
            toolbox=toolbox,
            parallel_tool_calls=False,
        )
        try:
            call_kwargs: dict[str, Any] = {
                "tools_mapping": tools_mapping,
                "toolbox": toolbox,
            }
            if max_tool_calls is not None:
                call_kwargs["max_tool_calls"] = max_tool_calls
            response = self.genai.call_openai(
                params,
                **call_kwargs,
            )
            text = self._assistant_text(response)
        except Exception as exc:
            log_event(
                LOGGER,
                "agent.tool_orchestration.error",
                "error",
                component="agent",
                agent_name=agent_name,
                step="orchestrate_with_tools",
                status="error",
                duration_ms=int((time.monotonic() - start) * 1000),
                error_type=exc.__class__.__name__,
            )
            raise
        log_event(
            LOGGER,
            "agent.tool_orchestration.end",
            component="agent",
            agent_name=agent_name,
            step="orchestrate_with_tools",
            status="ok",
            duration_ms=int((time.monotonic() - start) * 1000),
            response_length=len(text),
        )
        return text

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
        orchestrator_guidance: str | None = None,
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
                    orchestrator_guidance=orchestrator_guidance,
                ),
            }
        )
        return messages

    def _assistant_text(self, response: Any) -> str:
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
                if isinstance(item, str):
                    chunks.append(item)
                    continue
                if isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if isinstance(text, str) and text.strip():
                        chunks.append(text.strip())
                    continue
                text = getattr(item, "text", None)
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
            return "\n".join(chunks).strip()
        if content is None:
            return ""
        return str(content).strip()

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
