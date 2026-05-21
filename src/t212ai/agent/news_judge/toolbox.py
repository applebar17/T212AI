"""Toolbox and delegation tools for the news ingestion judge."""

from __future__ import annotations

import json
from typing import Any

from t212ai.genai.models import ToolResult, ToolSpec
from t212ai.genai.tools.base import ToolBox, build_tool_index
from t212ai.market_signals import (
    MARKET_SIGNAL_TOOLBOX,
    build_market_signal_tool_mapping,
)

from ..base import BaseAgent
from ..intents import AgentIntent, IntentKind, StructuredIntentEntity
from ..planner import TaskComplexity
from ..schemas import AgentRequest, AgentResponse
from .schemas import NewsJudgeDependencies


def build_news_judge_toolbox(dependencies: NewsJudgeDependencies) -> ToolBox:
    tools: list[ToolSpec] = []
    if dependencies.market_agent is not None:
        tools.append(_delegate_tool("news_delegate_to_market_analyst"))
    if dependencies.order_agent is not None:
        tools.append(_delegate_order_tool())
    if dependencies.market_signal_service is not None:
        tools.extend(MARKET_SIGNAL_TOOLBOX.tools)
    return ToolBox(
        name="news_ingestion_judge",
        tools=tools,
        tools_by_name=build_tool_index(tools),
    )


def build_news_judge_tool_mapping(
    dependencies: NewsJudgeDependencies,
    *,
    parent_request: AgentRequest,
) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    if dependencies.market_agent is not None:
        mapping["news_delegate_to_market_analyst"] = _delegate_to_agent_tool(
            dependencies.market_agent,
            parent_request=parent_request,
            intent=AgentIntent(kind=IntentKind.UNKNOWN, entities={"domain": "market"}),
        )
    if dependencies.order_agent is not None:
        mapping["news_delegate_to_order_agent"] = _delegate_to_order_tool(
            dependencies.order_agent,
            parent_request=parent_request,
        )
    mapping.update(build_market_signal_tool_mapping(dependencies.market_signal_service))
    return mapping


def _delegate_tool(name: str) -> ToolSpec:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": (
                "Delegate focused market analysis for the current streamed news event. "
                "Use this when market context, price action, volume, sector impact, "
                "or catalyst interpretation is needed."
            ),
            "strict": True,
            "parameters": _delegate_parameters(include_intent=False),
        },
    }


def _delegate_order_tool() -> ToolSpec:
    parameters = _delegate_parameters(include_intent=True)
    return {
        "type": "function",
        "function": {
            "name": "news_delegate_to_order_agent",
            "description": (
                "Delegate to the order agent when the current news and context may "
                "justify a concrete approval-gated order proposal. The order agent "
                "may prepare a pending action, but execution remains button-approved."
            ),
            "strict": True,
            "parameters": parameters,
        },
    }


def _delegate_parameters(*, include_intent: bool) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "task_brief": {
            "type": "string",
            "description": "Focused task for the downstream specialist.",
        },
        "expected_output": {
            "type": "string",
            "description": "Expected specialist result.",
        },
    }
    required = ["task_brief", "expected_output"]
    if include_intent:
        properties["intent_kind"] = {
            "type": "string",
            "enum": [IntentKind.PROPOSE_TRADE.value, IntentKind.PLACE_ORDER.value],
            "default": IntentKind.PROPOSE_TRADE.value,
        }
        properties["entities"] = {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": ["key", "value"],
            },
            "default": [],
        }
        required.extend(["intent_kind", "entities"])
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


def _delegate_to_agent_tool(
    agent: BaseAgent,
    *,
    parent_request: AgentRequest,
    intent: AgentIntent,
):
    def _delegate(*, task_brief: str, expected_output: str) -> ToolResult:
        response = agent.handle(
            AgentRequest(
                user_message=_delegated_message(task_brief, expected_output),
                chat_id=parent_request.chat_id,
                trigger_type="scheduler_news",
                history=parent_request.history,
                metadata=dict(parent_request.metadata),
            ),
            intent=intent,
            task_complexity=TaskComplexity.COMPLEX,
        )
        return _agent_tool_result(response)

    return _delegate


def _delegate_to_order_tool(
    agent: BaseAgent,
    *,
    parent_request: AgentRequest,
):
    def _delegate(
        *,
        task_brief: str,
        expected_output: str,
        intent_kind: str,
        entities: list[dict[str, str]],
    ) -> ToolResult:
        intent = AgentIntent(
            kind=IntentKind(intent_kind),
            entities={
                item.key: item.value
                for item in [
                    StructuredIntentEntity.model_validate(entity)
                    for entity in entities or []
                ]
            },
        )
        response = agent.handle(
            AgentRequest(
                user_message=_delegated_message(task_brief, expected_output),
                chat_id=parent_request.chat_id,
                trigger_type="scheduler_news",
                history=parent_request.history,
                metadata=dict(parent_request.metadata),
            ),
            intent=intent,
            task_complexity=TaskComplexity.COMPLEX,
        )
        return _agent_tool_result(response)

    return _delegate


def _agent_tool_result(response: AgentResponse) -> ToolResult:
    data: dict[str, Any] = {
        "selectedAgent": response.selected_agent,
        "metadata": response.metadata,
    }
    approval = response.artifacts.get("telegram_approval_request")
    if isinstance(approval, dict):
        data["telegramApproval"] = approval
    order_action = response.artifacts.get("order_action")
    if isinstance(order_action, dict):
        pending = order_action.get("pendingAction")
        if isinstance(pending, dict):
            data["pendingAction"] = pending
    proposal_id = response.artifacts.get("proposal_id")
    if proposal_id:
        data["proposalId"] = str(proposal_id)
    return ToolResult(status="ok", output=response.final_answer, data=data)


def _delegated_message(task_brief: str, expected_output: str) -> str:
    return json.dumps(
        {
            "taskBrief": str(task_brief or "").strip(),
            "expectedOutput": str(expected_output or "").strip(),
        },
        ensure_ascii=True,
        sort_keys=True,
    )
