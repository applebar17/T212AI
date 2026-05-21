"""Runtime binding for generic broker tool callables."""

from __future__ import annotations

from collections.abc import Callable

from t212ai.genai.models import ToolResult

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


def build_broker_tool_mapping(runtime: BrokerToolRuntime) -> dict[str, Callable[..., ToolResult]]:
    return {
        "broker_get_portfolio_snapshot": lambda: broker_get_portfolio_snapshot(runtime=runtime),
        "broker_list_pending_orders": lambda: broker_list_pending_orders(runtime=runtime),
        "broker_get_order": lambda order_ref: broker_get_order(order_ref=order_ref, runtime=runtime),
        "broker_list_historical_orders": lambda **kwargs: broker_list_historical_orders(
            runtime=runtime,
            **kwargs,
        ),
        "broker_get_instrument_snapshot": lambda ticker: broker_get_instrument_snapshot(
            ticker=ticker,
            runtime=runtime,
        ),
        "broker_resolve_instrument": lambda **kwargs: broker_resolve_instrument(
            runtime=runtime,
            **kwargs,
        ),
        "broker_prepare_order": lambda **kwargs: broker_prepare_order(runtime=runtime, **kwargs),
        "broker_prepare_order_action": lambda **kwargs: broker_prepare_order_action(
            runtime=runtime,
            **kwargs,
        ),
        "broker_prepare_cancel_action": lambda **kwargs: broker_prepare_cancel_action(
            runtime=runtime,
            **kwargs,
        ),
        "broker_place_order": lambda **kwargs: broker_place_order(runtime=runtime, **kwargs),
        "broker_cancel_order": lambda **kwargs: broker_cancel_order(runtime=runtime, **kwargs),
}
