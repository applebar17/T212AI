"""Read-only generic broker tools."""

from __future__ import annotations

from t212ai.genai.models import ToolResult
from t212ai.genai.tracing import set_trace_metadata, traceable

from .errors import _tool_error, _tool_exception
from .formatting import _display_broker_name
from .output import (
    _format_instrument_snapshot_output,
    _format_pending_orders_output,
    _format_portfolio_snapshot_output,
)
from .references import _dump_order_with_public_ref, _dump_snapshot_with_public_refs, _resolve_order_ref
from .runtime import BrokerToolRuntime


def broker_get_portfolio_snapshot(*, runtime: BrokerToolRuntime) -> ToolResult:
    set_trace_metadata(provider=runtime.broker_provider, tool_name="broker_get_portfolio_snapshot")
    if runtime.broker_read_service is None:
        return _tool_error(
            "Broker read service is not configured.",
            code="broker_not_configured",
        )
    try:
        snapshot = runtime.broker_read_service.get_portfolio_snapshot()
    except Exception as exc:
        return _tool_exception(
            exc,
            runtime=runtime,
            operation="get_portfolio_snapshot",
            message="Unable to retrieve the broker portfolio snapshot.",
        )
    return ToolResult(
        status="ok",
        output=_format_portfolio_snapshot_output(
            snapshot,
            provider=runtime.broker_provider,
            runtime=runtime,
        ),
        data={
            "provider": runtime.broker_provider,
            "snapshot": _dump_snapshot_with_public_refs(snapshot, runtime=runtime),
        },
    )


@traceable(
    name="broker_list_pending_orders",
    run_type="tool"
)
def broker_list_pending_orders(*, runtime: BrokerToolRuntime) -> ToolResult:
    set_trace_metadata(provider=runtime.broker_provider, tool_name="broker_list_pending_orders")
    if runtime.broker_read_service is None:
        return _tool_error(
            "Broker read service is not configured.",
            code="broker_not_configured",
        )
    try:
        orders = runtime.broker_read_service.list_pending_orders()
    except Exception as exc:
        return _tool_exception(
            exc,
            runtime=runtime,
            operation="list_pending_orders",
            message="Unable to retrieve broker pending orders.",
        )
    return ToolResult(
        status="ok",
        output=_format_pending_orders_output(orders, runtime=runtime),
        data={
            "provider": runtime.broker_provider,
            "orders": [_dump_order_with_public_ref(order, runtime=runtime) for order in orders],
        },
    )


@traceable(
    name="broker_get_order",
    run_type="tool"
)
def broker_get_order(*, order_ref: str, runtime: BrokerToolRuntime) -> ToolResult:
    set_trace_metadata(provider=runtime.broker_provider, tool_name="broker_get_order")
    if runtime.broker_read_service is None:
        return _tool_error(
            "Broker read service is not configured.",
            code="broker_not_configured",
        )
    resolved_order_ref = _resolve_order_ref(order_ref, runtime=runtime)
    if isinstance(resolved_order_ref, ToolResult):
        return resolved_order_ref
    if resolved_order_ref is None:
        return _tool_error(
            "order_ref is required and cannot be empty.",
            code="missing_order_ref",
            hint="Use an ORDER_000001 reference from broker_list_pending_orders or a broker-native order reference.",
        )
    try:
        order = runtime.broker_read_service.get_order(resolved_order_ref)
    except Exception as exc:
        return _tool_exception(
            exc,
            runtime=runtime,
            operation="get_order",
            message=f"Unable to retrieve broker order {resolved_order_ref}.",
        )
    order_payload = _dump_order_with_public_ref(
        order,
        runtime=runtime,
        fallback_true_ref=resolved_order_ref,
    )
    return ToolResult(
        status="ok",
        output=(
            f"Retrieved { _display_broker_name(runtime.broker_provider) } order "
            f"{order_payload.get('publicOrderRef', resolved_order_ref)}."
        ),
        data={
            "provider": runtime.broker_provider,
            "order": order_payload,
        },
    )


@traceable(
    name="broker_list_historical_orders",
    run_type="tool"
)
def broker_list_historical_orders(
    *,
    cursor: str | int | None,
    ticker: str | None,
    limit: int | None,
    runtime: BrokerToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider=runtime.broker_provider, tool_name="broker_list_historical_orders")
    if runtime.broker_read_service is None:
        return _tool_error(
            "Broker read service is not configured.",
            code="broker_not_configured",
        )
    try:
        page = runtime.broker_read_service.list_historical_orders(
            cursor=cursor,
            ticker=ticker,
            limit=limit,
        )
    except Exception as exc:
        return _tool_exception(
            exc,
            runtime=runtime,
            operation="list_historical_orders",
            message="Unable to retrieve broker historical orders.",
        )
    return ToolResult(
        status="ok",
        output=(
            f"Retrieved {len(page.items)} historical { _display_broker_name(runtime.broker_provider) } "
            "order record(s)."
        ),
        data={
            "provider": runtime.broker_provider,
            "page": page.model_dump(by_alias=True, exclude_none=True, mode="json"),
        },
    )


@traceable(
    name="broker_get_instrument_snapshot",
    run_type="tool",
)
def broker_get_instrument_snapshot(
    *,
    ticker: str,
    runtime: BrokerToolRuntime,
) -> ToolResult:
    set_trace_metadata(
        provider=runtime.broker_provider,
        tool_name="broker_get_instrument_snapshot",
    )
    if runtime.broker_read_service is None:
        return _tool_error(
            "Broker read service is not configured.",
            code="broker_not_configured",
        )
    snapshotter = getattr(runtime.broker_read_service, "get_instrument_snapshot", None)
    if not callable(snapshotter):
        return _tool_error(
            "The configured broker does not expose instrument snapshots.",
            code="instrument_snapshot_unavailable",
            hint=(
                "Use broker_resolve_instrument for broker-native ticker resolution, "
                "or configure a broker adapter with instrument metadata support."
            ),
            details={"provider": runtime.broker_provider},
        )
    resolved_ticker = str(ticker or "").strip()
    if not resolved_ticker:
        return _tool_error(
            "ticker is required and cannot be empty.",
            code="missing_ticker",
            hint="Provide a ticker, broker-native ticker, ISIN, or instrument name.",
        )
    try:
        snapshot = snapshotter(resolved_ticker)
    except Exception as exc:
        return _tool_exception(
            exc,
            runtime=runtime,
            operation="get_instrument_snapshot",
            message="Unable to retrieve broker instrument snapshot.",
        )
    return ToolResult(
        status="ok",
        output=_format_instrument_snapshot_output(
            snapshot,
            provider=runtime.broker_provider,
        ),
        data={
            "provider": runtime.broker_provider,
            "snapshot": snapshot.model_dump(
                by_alias=True,
                exclude_none=True,
                mode="json",
            ),
        },
    )


@traceable(
    name="broker_resolve_instrument",
    run_type="tool"
)
def broker_resolve_instrument(
    *,
    query: str,
    limit: int = 8,
    runtime: BrokerToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider=runtime.broker_provider, tool_name="broker_resolve_instrument")
    if runtime.broker_read_service is None:
        return _tool_error(
            "Broker read service is not configured.",
            code="broker_not_configured",
        )
    resolver = getattr(runtime.broker_read_service, "resolve_instrument", None)
    if not callable(resolver):
        return _tool_error(
            "The configured broker does not expose instrument resolution.",
            code="instrument_resolution_unavailable",
            hint=(
                "Use the broker-native ticker expected by the provider, or configure a "
                "broker adapter that supports instrument metadata lookup."
            ),
            details={"provider": runtime.broker_provider},
        )
    resolved_query = str(query or "").strip()
    if not resolved_query:
        return _tool_error(
            "query is required and cannot be empty.",
            code="missing_query",
            hint="Provide a ticker, broker-native ticker, ISIN, or instrument name.",
        )
    try:
        resolution = resolver(resolved_query, limit=max(1, int(limit)))
    except Exception as exc:
        return _tool_exception(
            exc,
            runtime=runtime,
            operation="resolve_instrument",
            message="Unable to resolve broker instrument metadata.",
        )

    candidates = getattr(resolution, "candidates", []) or []
    resolved_ticker = getattr(resolution, "resolved_ticker", None)
    status = str(getattr(resolution, "status", "unknown"))
    if resolved_ticker:
        output = (
            f"Resolved {resolved_query!r} to broker-native ticker "
            f"{resolved_ticker} for {_display_broker_name(runtime.broker_provider)}."
        )
    elif candidates:
        output = (
            f"{_display_broker_name(runtime.broker_provider)} returned "
            f"{len(candidates)} candidate instrument(s) for {resolved_query!r}; "
            "choose an exact broker-native ticker before preparing an order."
        )
    else:
        output = (
            f"No {_display_broker_name(runtime.broker_provider)} instruments matched "
            f"{resolved_query!r}."
        )
    return ToolResult(
        status="ok",
        output=output,
        data={
            "provider": runtime.broker_provider,
            "resolution": resolution.model_dump(
                by_alias=True,
                exclude_none=True,
                mode="json",
            ),
            "status": status,
        },
    )
