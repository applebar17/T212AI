"""Shared helpers for specialist agents."""

from __future__ import annotations

import logging
import time
from typing import Any

from t212ai.app.logging import log_event
from t212ai.genai.models import ToolResult, ToolSpec
from t212ai.genai.tools.base import ToolBox
from t212ai.genai.tracing import set_trace_metadata, set_trace_name, traceable

from ..base import BaseAgent
from ..intents import AgentIntent, IntentKind
from ..schemas import AgentRequest

LOGGER = logging.getLogger(__name__)


def _empty_toolbox(name: str) -> ToolBox:
    return ToolBox(name=name, tools=[], tools_by_name={})


def _with_tool(toolbox: ToolBox, tool: ToolSpec) -> ToolBox:
    if tool["function"]["name"] in toolbox.tools_by_name:
        return toolbox
    tools = [*toolbox.tools, tool]
    return ToolBox(
        name=toolbox.name,
        tools=tools,
        tools_by_name={**toolbox.tools_by_name, tool["function"]["name"]: tool},
    )


def _reddit_research_delegation_tool() -> ToolSpec:
    return {
        "type": "function",
        "function": {
            "name": "delegate_to_reddit_research_agent",
            "description": (
                "Delegate to reddit_research_agent for Reddit/community social "
                "analysis. Use when Reddit sentiment, attention, speculative themes, "
                "or finance-subreddit discussion can inform market research. The "
                "agent uses Reddit as social context only and verifies nothing as "
                "execution-grade truth."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "task_brief": {
                        "type": "string",
                        "description": "What Reddit/social topic to explore.",
                    },
                    "expected_output": {
                        "type": "string",
                        "description": (
                            "The social-analysis shape wanted back: sentiment, "
                            "attention level, themes, notable posts, cautions, "
                            "and verification needs."
                        ),
                    },
                    "entities": {
                        "type": "array",
                        "description": (
                            "Structured hints such as ticker, company, subreddit, "
                            "post_id, theme, or time window."
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
                "required": ["task_brief", "expected_output", "entities"],
            },
            "strict": True,
        },
    }


def _build_reddit_research_delegate(
    *,
    delegating_agent: BaseAgent,
    reddit_agent: BaseAgent,
    request: AgentRequest,
):
    @traceable(name="delegate_to_reddit_research_agent", run_type="tool")
    def _delegate(
        *,
        task_brief: str,
        expected_output: str,
        entities: list[dict[str, str]] | None = None,
    ) -> ToolResult:
        start = time.monotonic()
        set_trace_name("delegate_to_reddit_research_agent")
        set_trace_metadata(
            agent_name=delegating_agent.name,
            agent_step="delegate_to_reddit_research_agent",
            step_kind="tool",
            tool_name="delegate_to_reddit_research_agent",
            specialist_name=reddit_agent.name,
            intent_kind=IntentKind.SOCIAL_RESEARCH.value,
        )
        log_event(
            LOGGER,
            "agent.delegate.start",
            component="agent",
            agent_name=delegating_agent.name,
            step="delegate_to_reddit_research_agent",
            tool_name="delegate_to_reddit_research_agent",
            selected_agent=reddit_agent.name,
            status="started",
            chat_id=request.chat_id,
            intent_kind=IntentKind.SOCIAL_RESEARCH.value,
        )
        entity_lines = "\n".join(
            f"- {str(item.get('key', '')).strip()}: {str(item.get('value', '')).strip()}"
            for item in (entities or [])
            if str(item.get("key", "")).strip()
        )
        guidance = (
            f"Task brief: {task_brief}\n"
            f"Expected output: {expected_output}"
        )
        if entity_lines:
            guidance = f"{guidance}\nEntities:\n{entity_lines}"
        if request.orchestrator_guidance:
            guidance = f"{request.orchestrator_guidance}\n\n{guidance}"
        delegated_request = request.model_copy(update={"orchestrator_guidance": guidance})
        response = reddit_agent.handle(
            delegated_request,
            intent=AgentIntent(
                kind=IntentKind.SOCIAL_RESEARCH,
                entities={
                    str(item.get("key", "")).strip(): str(item.get("value", "")).strip()
                    for item in (entities or [])
                    if str(item.get("key", "")).strip()
                },
                confidence=0.8,
            ),
        )
        log_event(
            LOGGER,
            "agent.delegate.end",
            component="agent",
            agent_name=delegating_agent.name,
            step="delegate_to_reddit_research_agent",
            tool_name="delegate_to_reddit_research_agent",
            selected_agent=reddit_agent.name,
            status=response.metadata.get("workflow_status", "ok"),
            chat_id=request.chat_id,
            duration_ms=int((time.monotonic() - start) * 1000),
            intent_kind=IntentKind.SOCIAL_RESEARCH.value,
        )
        return ToolResult(
            status="ok",
            output=response.final_answer,
            data={
                "specialist": reddit_agent.name,
                "task_brief": task_brief,
                "expected_output": expected_output,
                "entities": entities or [],
                "final_answer": response.final_answer,
                "metadata": response.metadata,
            },
        )

    return _delegate

