"""Static Trading 212 toolbox definitions."""

from __future__ import annotations

from t212ai.genai.tools.tools import ToolBox, build_tool_index

from .specs import (
    T212_CANCEL_ORDER_TOOL,
    T212_GET_ORDER_TOOL,
    T212_GET_PORTFOLIO_SNAPSHOT_TOOL,
    T212_LIST_PENDING_ORDERS_TOOL,
    T212_PLACE_ORDER_TOOL,
    T212_PREPARE_CANCEL_ACTION_TOOL,
    T212_PREPARE_ORDER_ACTION_TOOL,
    T212_PREPARE_ORDER_TOOL,
)


T212_READ_TOOLBOX = ToolBox(
    name="t212_read",
    tools=[
        T212_GET_PORTFOLIO_SNAPSHOT_TOOL,
        T212_LIST_PENDING_ORDERS_TOOL,
        T212_GET_ORDER_TOOL,
    ],
    tools_by_name=build_tool_index(
        [
            T212_GET_PORTFOLIO_SNAPSHOT_TOOL,
            T212_LIST_PENDING_ORDERS_TOOL,
            T212_GET_ORDER_TOOL,
        ]
    ),
)

T212_ORDER_PLANNING_TOOLBOX = ToolBox(
    name="t212_order_planning",
    tools=[
        *T212_READ_TOOLBOX.tools,
        T212_PREPARE_ORDER_TOOL,
    ],
    tools_by_name=build_tool_index(
        [
            *T212_READ_TOOLBOX.tools,
            T212_PREPARE_ORDER_TOOL,
        ]
    ),
)

T212_ORDER_ACTION_TOOLBOX = ToolBox(
    name="t212_order_actions",
    tools=[
        *T212_READ_TOOLBOX.tools,
        T212_PREPARE_ORDER_ACTION_TOOL,
        T212_PREPARE_CANCEL_ACTION_TOOL,
    ],
    tools_by_name=build_tool_index(
        [
            *T212_READ_TOOLBOX.tools,
            T212_PREPARE_ORDER_ACTION_TOOL,
            T212_PREPARE_CANCEL_ACTION_TOOL,
        ]
    ),
)

T212_EXECUTION_TOOLBOX = ToolBox(
    name="t212_execution",
    tools=[
        *T212_ORDER_PLANNING_TOOLBOX.tools,
        T212_PLACE_ORDER_TOOL,
        T212_CANCEL_ORDER_TOOL,
    ],
    tools_by_name=build_tool_index(
        [
            *T212_ORDER_PLANNING_TOOLBOX.tools,
            T212_PLACE_ORDER_TOOL,
            T212_CANCEL_ORDER_TOOL,
        ]
    ),
)
