"""Runtime binding for Trading 212 tool callables."""

from __future__ import annotations

from collections.abc import Callable

from t212ai.genai.models import ToolResult

from .orders import (
    t212_cancel_order,
    t212_place_order,
    t212_prepare_cancel_action,
    t212_prepare_order,
    t212_prepare_order_action,
)
from .read import t212_get_order, t212_get_portfolio_snapshot, t212_list_pending_orders
from .runtime import Trading212ToolRuntime


def build_trading212_tool_mapping(
    runtime: Trading212ToolRuntime,
) -> dict[str, Callable[..., ToolResult]]:
    return {
        "t212_get_portfolio_snapshot": lambda: t212_get_portfolio_snapshot(runtime=runtime),
        "t212_list_pending_orders": lambda: t212_list_pending_orders(runtime=runtime),
        "t212_get_order": lambda order_id: t212_get_order(
            order_id=order_id,
            runtime=runtime,
        ),
        "t212_prepare_order": lambda **kwargs: t212_prepare_order(runtime=runtime, **kwargs),
        "t212_prepare_order_action": lambda **kwargs: t212_prepare_order_action(
            runtime=runtime,
            **kwargs,
        ),
        "t212_prepare_cancel_action": lambda **kwargs: t212_prepare_cancel_action(
            runtime=runtime,
            **kwargs,
        ),
        "t212_place_order": lambda **kwargs: t212_place_order(runtime=runtime, **kwargs),
        "t212_cancel_order": lambda **kwargs: t212_cancel_order(runtime=runtime, **kwargs),
}
