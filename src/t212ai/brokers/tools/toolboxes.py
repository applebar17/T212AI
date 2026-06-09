"""Toolbox builders for generic broker capabilities."""

from __future__ import annotations

from copy import deepcopy

from t212ai.data_sources.eodhd import SYMBOL_REFERENCE_SEARCH_TOOL
from t212ai.genai.models import ToolSpec
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


_BROKER_SYMBOL_REFERENCE_SEARCH_SUFFIX = (
    " In the broker order toolbox, use this only when order generation hits "
    "symbol, ticker, or ISIN ambiguity and you need reference data to check an "
    "ISIN code before retrying broker-native instrument resolution. It is not "
    "broker-authoritative; broker_resolve_instrument and broker instrument tools "
    "must still verify tradability before any order action."
)


def _broker_symbol_reference_search_tool() -> ToolSpec:
    tool = deepcopy(SYMBOL_REFERENCE_SEARCH_TOOL)
    fn = tool["function"]
    description = str(fn.get("description") or "").strip()
    fn["description"] = (description + _BROKER_SYMBOL_REFERENCE_SEARCH_SUFFIX).strip()
    return tool


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


def build_broker_order_action_toolbox(
    *,
    include_symbol_reference_search: bool = False,
) -> ToolBox:
    tools = [
        *build_broker_read_toolbox().tools,
        BROKER_PREPARE_ORDER_ACTION_TOOL,
        BROKER_PREPARE_CANCEL_ACTION_TOOL,
    ]
    if include_symbol_reference_search:
        tools.append(_broker_symbol_reference_search_tool())
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
