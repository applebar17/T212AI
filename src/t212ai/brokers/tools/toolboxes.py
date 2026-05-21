"""Toolbox builders for generic broker capabilities."""

from __future__ import annotations

from t212ai.genai.tools.base import ToolBox, build_tool_index

from .specs import (
    BROKER_CANCEL_ORDER_TOOL,
    BROKER_GET_INSTRUMENT_SNAPSHOT_TOOL,
    BROKER_GET_ORDER_TOOL,
    BROKER_GET_PORTFOLIO_SNAPSHOT_TOOL,
    BROKER_LIST_HISTORICAL_ORDERS_TOOL,
    BROKER_LIST_PENDING_ORDERS_TOOL,
    BROKER_PLACE_ORDER_TOOL,
    BROKER_PREPARE_CANCEL_ACTION_TOOL,
    BROKER_PREPARE_ORDER_ACTION_TOOL,
    BROKER_PREPARE_ORDER_TOOL,
    BROKER_RESOLVE_INSTRUMENT_TOOL,
)


def build_broker_read_toolbox() -> ToolBox:
    tools = [
        BROKER_GET_PORTFOLIO_SNAPSHOT_TOOL,
        BROKER_LIST_PENDING_ORDERS_TOOL,
        BROKER_GET_ORDER_TOOL,
        BROKER_LIST_HISTORICAL_ORDERS_TOOL,
        BROKER_GET_INSTRUMENT_SNAPSHOT_TOOL,
        BROKER_RESOLVE_INSTRUMENT_TOOL,
    ]
    return ToolBox(
        name="broker_read",
        tools=tools,
        tools_by_name=build_tool_index(tools),
    )


def build_broker_order_planning_toolbox() -> ToolBox:
    tools = [
        *build_broker_read_toolbox().tools,
        BROKER_PREPARE_ORDER_TOOL,
    ]
    return ToolBox(
        name="broker_order_planning",
        tools=tools,
        tools_by_name=build_tool_index(tools),
    )


def build_broker_order_action_toolbox() -> ToolBox:
    tools = [
        *build_broker_read_toolbox().tools,
        BROKER_PREPARE_ORDER_ACTION_TOOL,
        BROKER_PREPARE_CANCEL_ACTION_TOOL,
    ]
    return ToolBox(
        name="broker_order_actions",
        tools=tools,
        tools_by_name=build_tool_index(tools),
    )


def build_broker_execution_toolbox() -> ToolBox:
    tools = [
        *build_broker_order_action_toolbox().tools,
        BROKER_PREPARE_ORDER_TOOL,
        BROKER_PLACE_ORDER_TOOL,
        BROKER_CANCEL_ORDER_TOOL,
    ]
    return ToolBox(
        name="broker_execution",
        tools=tools,
        tools_by_name=build_tool_index(tools),
    )


BROKER_READ_TOOLBOX = build_broker_read_toolbox()
BROKER_ORDER_PLANNING_TOOLBOX = build_broker_order_planning_toolbox()
BROKER_ORDER_ACTION_TOOLBOX = build_broker_order_action_toolbox()
BROKER_EXECUTION_TOOLBOX = build_broker_execution_toolbox()
