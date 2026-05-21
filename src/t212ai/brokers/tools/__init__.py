"""Generic broker tool facade for capability-backed broker operations."""

from .mapping import build_broker_tool_mapping
from .orders import (
    broker_cancel_order,
    broker_place_order,
    broker_prepare_cancel_action,
    broker_prepare_order,
    broker_prepare_order_action,
)
from .read import (
    broker_get_instrument_snapshot,
    broker_get_order,
    broker_get_portfolio_snapshot,
    broker_list_historical_orders,
    broker_list_pending_orders,
    broker_resolve_instrument,
)
from .runtime import BrokerToolRuntime
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
    _BROKER_ORDER_ARGUMENTS_SCHEMA,
)
from .toolboxes import (
    BROKER_EXECUTION_TOOLBOX,
    BROKER_ORDER_ACTION_TOOLBOX,
    BROKER_ORDER_PLANNING_TOOLBOX,
    BROKER_READ_TOOLBOX,
    build_broker_execution_toolbox,
    build_broker_order_action_toolbox,
    build_broker_order_planning_toolbox,
    build_broker_read_toolbox,
)

__all__ = [
    "BROKER_CANCEL_ORDER_TOOL",
    "BROKER_EXECUTION_TOOLBOX",
    "BROKER_GET_INSTRUMENT_SNAPSHOT_TOOL",
    "BROKER_GET_ORDER_TOOL",
    "BROKER_GET_PORTFOLIO_SNAPSHOT_TOOL",
    "BROKER_LIST_HISTORICAL_ORDERS_TOOL",
    "BROKER_LIST_PENDING_ORDERS_TOOL",
    "BROKER_ORDER_ACTION_TOOLBOX",
    "BROKER_ORDER_PLANNING_TOOLBOX",
    "BROKER_PLACE_ORDER_TOOL",
    "BROKER_PREPARE_CANCEL_ACTION_TOOL",
    "BROKER_PREPARE_ORDER_ACTION_TOOL",
    "BROKER_PREPARE_ORDER_TOOL",
    "BROKER_READ_TOOLBOX",
    "BROKER_RESOLVE_INSTRUMENT_TOOL",
    "BrokerToolRuntime",
    "_BROKER_ORDER_ARGUMENTS_SCHEMA",
    "broker_cancel_order",
    "broker_get_instrument_snapshot",
    "broker_get_order",
    "broker_get_portfolio_snapshot",
    "broker_list_historical_orders",
    "broker_list_pending_orders",
    "broker_place_order",
    "broker_prepare_cancel_action",
    "broker_prepare_order",
    "broker_prepare_order_action",
    "broker_resolve_instrument",
    "build_broker_execution_toolbox",
    "build_broker_order_action_toolbox",
    "build_broker_order_planning_toolbox",
    "build_broker_read_toolbox",
    "build_broker_tool_mapping",
]
