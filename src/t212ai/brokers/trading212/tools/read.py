"""Read-only Trading 212 tools."""

from __future__ import annotations

from t212ai.genai.models import ToolResult
from t212ai.genai.tracing import set_trace_metadata, traceable

from .errors import _tool_exception
from .output import _format_portfolio_snapshot_output
from .runtime import Trading212ToolRuntime


def t212_get_portfolio_snapshot(*, runtime: Trading212ToolRuntime) -> ToolResult:
    set_trace_metadata(provider="trading212", tool_name="t212_get_portfolio_snapshot")
    try:
        snapshot = runtime.service.get_portfolio_snapshot()
    except Exception as exc:
        return _tool_exception(
            exc,
            operation="get_portfolio_snapshot",
            message="Unable to retrieve the Trading 212 portfolio snapshot.",
            hint=(
                "Do not infer broker state from market-data or news tools. "
                "Check Trading 212 credentials, selected demo/live environment, "
                "API scopes for account/portfolio/orders, network availability, "
                "and endpoint rate limits before retrying."
            ),
        )

    return ToolResult(
        status="ok",
        output=_format_portfolio_snapshot_output(snapshot),
        data=snapshot.model_dump(by_alias=True, exclude_none=True, mode="json"),
    )


@traceable(
    name="t212_list_pending_orders",
    run_type="tool"
)
def t212_list_pending_orders(*, runtime: Trading212ToolRuntime) -> ToolResult:
    set_trace_metadata(provider="trading212", tool_name="t212_list_pending_orders")
    orders = runtime.service.list_pending_orders()
    return ToolResult(
        status="ok",
        output=f"Retrieved {len(orders)} pending Trading 212 orders.",
        data=[order.model_dump(by_alias=True, exclude_none=True, mode="json") for order in orders],
    )


@traceable(
    name="t212_get_order",
    run_type="tool"
)
def t212_get_order(*, order_id: int, runtime: Trading212ToolRuntime) -> ToolResult:
    set_trace_metadata(provider="trading212", tool_name="t212_get_order")
    order = runtime.service.get_order(str(order_id))
    return ToolResult(
        status="ok",
        output=f"Retrieved Trading 212 order {order_id}.",
        data=order.model_dump(by_alias=True, exclude_none=True, mode="json"),
    )
