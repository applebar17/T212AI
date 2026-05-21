"""Order preparation, approval, and execution broker tools."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from t212ai.genai.models import ToolResult
from t212ai.genai.tracing import set_trace_metadata, traceable
from t212ai.pending_actions import PendingActionKind, approval_expiry

from ..models import BrokerOrder
from .errors import _tool_error, _tool_exception
from .output import _format_cancel_action_summary, _format_prepared_order_action_summary
from .references import (
    _dump_order_with_public_ref,
    _register_order_public_ref,
    _resolve_order_ref,
)
from .runtime import BrokerToolRuntime
from .sizing import _prepare_order_or_error


def broker_prepare_order(
    *,
    order_type: str,
    side: str,
    ticker: str,
    quantity: str | int | float | None,
    limit_price: str | int | float | None,
    stop_price: str | int | float | None,
    time_in_force: str,
    extended_hours: bool,
    runtime: BrokerToolRuntime,
    notional_amount: str | int | float | None = None,
    notional_currency: str | None = None,
) -> ToolResult:
    set_trace_metadata(
        provider=runtime.broker_provider,
        tool_name="broker_prepare_order",
        state_changing=False,
    )
    prepared = _prepare_order_or_error(
        runtime=runtime,
        order_type=order_type,
        side=side,
        ticker=ticker,
        quantity=quantity,
        notional_amount=notional_amount,
        notional_currency=notional_currency,
        limit_price=limit_price,
        stop_price=stop_price,
        time_in_force=time_in_force,
        extended_hours=extended_hours,
    )
    if isinstance(prepared, ToolResult):
        return prepared
    return ToolResult(
        status="ok",
        output=(
            "Prepared order only; nothing was submitted. "
            f"Fingerprint: {prepared.order_fingerprint}."
        ),
        data={
            "provider": runtime.broker_provider,
            "preparedOrder": prepared.model_dump(by_alias=True, exclude_none=True, mode="json"),
        },
    )


@traceable(
    name="broker_prepare_order_action",
    run_type="tool"
)
def broker_prepare_order_action(
    *,
    order_type: str,
    side: str,
    ticker: str,
    quantity: str | int | float | None,
    limit_price: str | int | float | None,
    stop_price: str | int | float | None,
    time_in_force: str,
    extended_hours: bool,
    runtime: BrokerToolRuntime,
    notional_amount: str | int | float | None = None,
    notional_currency: str | None = None,
) -> ToolResult:
    set_trace_metadata(
        provider=runtime.broker_provider,
        tool_name="broker_prepare_order_action",
        state_changing=False,
    )
    if runtime.pending_action_service is None or not runtime.chat_id:
        return _tool_error(
            "Pending-action runtime is not configured for order preparation.",
            code="missing_pending_action_runtime",
            hint="Run this tool through the order agent inside a Telegram-bound runtime.",
        )
    prepared = _prepare_order_or_error(
        runtime=runtime,
        order_type=order_type,
        side=side,
        ticker=ticker,
        quantity=quantity,
        notional_amount=notional_amount,
        notional_currency=notional_currency,
        limit_price=limit_price,
        stop_price=stop_price,
        time_in_force=time_in_force,
        extended_hours=extended_hours,
    )
    if isinstance(prepared, ToolResult):
        return prepared
    action = runtime.pending_action_service.create_submit_action(
        chat_id=runtime.chat_id,
        user_id=runtime.user_id,
        prepared_order=prepared,
        original_user_message=runtime.user_message or "",
        summary_text=_format_prepared_order_action_summary(prepared, provider=runtime.broker_provider),
        expires_at=approval_expiry(
            kind=PendingActionKind.SUBMIT_ORDER,
            order_type=prepared.order_type.value,
        ),
        broker_provider=runtime.broker_provider,
    )
    return ToolResult(
        status="ok",
        output=_approval_message_text(action),
        data={
            "provider": runtime.broker_provider,
            "pendingAction": action.model_dump(mode="json"),
            "telegramApproval": _approval_payload(action),
        },
    )


@traceable(
    name="broker_prepare_cancel_action",
    run_type="tool"
)
def broker_prepare_cancel_action(
    *,
    order_ref: str | None,
    selector: str | None,
    reason: str | None,
    runtime: BrokerToolRuntime,
) -> ToolResult:
    set_trace_metadata(
        provider=runtime.broker_provider,
        tool_name="broker_prepare_cancel_action",
        state_changing=False,
    )
    if runtime.pending_action_service is None or not runtime.chat_id:
        return _tool_error(
            "Pending-action runtime is not configured for cancellation preparation.",
            code="missing_pending_action_runtime",
            hint="Run this tool through the order agent inside a Telegram-bound runtime.",
        )
    if runtime.broker_read_service is None:
        return _tool_error(
            "Broker read service is not configured.",
            code="broker_not_configured",
        )
    resolved_order_ref = _resolve_order_ref(order_ref, runtime=runtime)
    if isinstance(resolved_order_ref, ToolResult):
        return resolved_order_ref
    try:
        pending_orders = runtime.broker_read_service.list_pending_orders()
        for pending_order in pending_orders:
            _register_order_public_ref(pending_order, runtime=runtime)
        target_order = _resolve_cancel_target(
            pending_orders,
            order_ref=resolved_order_ref,
            selector=selector,
        )
    except ValueError as exc:
        return _tool_error(
            str(exc),
            code="ambiguous_cancel_target",
            hint=(
                "Provide an explicit pending order reference, or use a deterministic selector "
                "such as oldest or latest."
            ),
        )
    action = runtime.pending_action_service.create_cancel_action(
        chat_id=runtime.chat_id,
        user_id=runtime.user_id,
        target_order=target_order,
        original_user_message=runtime.user_message or "",
        summary_text=_format_cancel_action_summary(
            target_order,
            provider=runtime.broker_provider,
            reason=reason,
            runtime=runtime,
        ),
        expires_at=approval_expiry(kind=PendingActionKind.CANCEL_ORDER),
        broker_provider=runtime.broker_provider,
    )
    return ToolResult(
        status="ok",
        output=_approval_message_text(action),
        data={
            "provider": runtime.broker_provider,
            "pendingAction": action.model_dump(mode="json"),
            "telegramApproval": _approval_payload(action),
            "targetOrder": _dump_order_with_public_ref(target_order, runtime=runtime),
        },
    )


@traceable(
    name="broker_place_order",
    run_type="tool"
)
def broker_place_order(
    *,
    order_type: str,
    side: str,
    ticker: str,
    quantity: str | int | float | None,
    limit_price: str | int | float | None,
    stop_price: str | int | float | None,
    time_in_force: str,
    extended_hours: bool,
    confirmed: bool,
    confirmation_reference: str | None,
    runtime: BrokerToolRuntime,
    notional_amount: str | int | float | None = None,
    notional_currency: str | None = None,
) -> ToolResult:
    set_trace_metadata(
        provider=runtime.broker_provider,
        tool_name="broker_place_order",
        state_changing=True,
        runtime_allows_state_changes=runtime.allow_state_changes,
    )
    if runtime.broker_execution_service is None:
        return _tool_error(
            "Broker execution service is not configured.",
            code="broker_not_configured",
        )
    if not runtime.allow_state_changes:
        return _tool_error(
            "Broker state-changing tools are disabled for this runtime.",
            code="state_changes_disabled",
        )
    if not confirmed:
        return _tool_error(
            "Order submission requires explicit user confirmation.",
            code="confirmation_required",
        )
    prepared = _prepare_order_or_error(
        runtime=runtime,
        order_type=order_type,
        side=side,
        ticker=ticker,
        quantity=quantity,
        notional_amount=notional_amount,
        notional_currency=notional_currency,
        limit_price=limit_price,
        stop_price=stop_price,
        time_in_force=time_in_force,
        extended_hours=extended_hours,
    )
    if isinstance(prepared, ToolResult):
        return prepared
    if confirmation_reference != prepared.order_fingerprint:
        return _tool_error(
            "confirmation_reference does not match the prepared order fingerprint.",
            code="fingerprint_mismatch",
            details={"expected_fingerprint": prepared.order_fingerprint},
        )
    try:
        result = runtime.broker_execution_service.submit_prepared_order(prepared)
    except Exception as exc:
        return _tool_exception(
            exc,
            runtime=runtime,
            operation="place_order",
            message="Broker order submission failed.",
        )
    return ToolResult(
        status="ok",
        output=result.message or f"Order submitted to { _display_broker_name(runtime.broker_provider) }.",
        data={
            "provider": runtime.broker_provider,
            "result": result.model_dump(by_alias=True, exclude_none=True, mode="json"),
        },
    )


@traceable(
    name="broker_cancel_order",
    run_type="tool"
)
def broker_cancel_order(
    *,
    order_ref: str,
    confirmed: bool,
    reason: str | None,
    runtime: BrokerToolRuntime,
) -> ToolResult:
    set_trace_metadata(
        provider=runtime.broker_provider,
        tool_name="broker_cancel_order",
        state_changing=True,
        runtime_allows_state_changes=runtime.allow_state_changes,
    )
    del reason
    if runtime.broker_execution_service is None:
        return _tool_error(
            "Broker execution service is not configured.",
            code="broker_not_configured",
        )
    if not runtime.allow_state_changes:
        return _tool_error(
            "Broker state-changing tools are disabled for this runtime.",
            code="state_changes_disabled",
        )
    if not confirmed:
        return _tool_error(
            "Order cancellation requires explicit user confirmation.",
            code="confirmation_required",
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
    result = runtime.broker_execution_service.cancel_order(resolved_order_ref)
    return ToolResult(
        status="ok",
        output=result.message or f"Cancellation requested for order {order_ref}.",
        data={
            "provider": runtime.broker_provider,
            "result": result.model_dump(by_alias=True, exclude_none=True, mode="json"),
            "brokerOrderRef": resolved_order_ref,
        },
    )


def _approval_payload(action) -> dict[str, Any]:
    return {
        "actionId": action.action_id,
        "text": _approval_message_text(action),
        "approveCallbackData": f"pa:approve:{action.action_id}",
        "rejectCallbackData": f"pa:reject:{action.action_id}",
    }


def _approval_message_text(action) -> str:
    return (
        f"{action.summary_text}\n\n"
        "Nothing has been executed yet.\n"
        "Approve or reject with the Telegram buttons below."
    )


def _resolve_cancel_target(
    orders: list[BrokerOrder],
    *,
    order_ref: str | None,
    selector: str | None,
) -> BrokerOrder:
    if order_ref is not None:
        for order in orders:
            if str(order.id or "").strip() == str(order_ref).strip():
                return order
        raise ValueError(f"Pending order {order_ref} was not found.")
    if not orders:
        raise ValueError("There are no pending orders to cancel.")
    if len(orders) == 1:
        return orders[0]
    resolved_selector = str(selector or "").strip().lower()
    if resolved_selector == "oldest":
        return min(orders, key=lambda item: item.created_at or datetime.max)
    if resolved_selector == "latest":
        return max(orders, key=lambda item: item.created_at or datetime.min)
    if resolved_selector == "only":
        raise ValueError(
            "Selector 'only' requires exactly one pending order, but multiple were found."
        )
    raise ValueError(
        "Cancellation target is ambiguous because multiple pending orders exist."
    )
