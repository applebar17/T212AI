"""Trading 212 order preparation and execution tools."""

from __future__ import annotations

from datetime import datetime

from t212ai.brokers.exceptions import BrokerInstrumentResolutionError
from t212ai.genai.models import ToolResult
from t212ai.genai.tracing import set_trace_metadata, traceable
from t212ai.pending_actions import PendingActionKind, approval_expiry

from ..models import Order
from .errors import _instrument_resolution_tool_error, _tool_error
from .output import _format_cancel_action_summary, _format_prepared_order_action_summary
from .runtime import Trading212ToolRuntime


def t212_prepare_order(
    *,
    order_type: str,
    side: str,
    ticker: str,
    quantity: str | int | float,
    limit_price: str | int | float | None,
    stop_price: str | int | float | None,
    time_validity: str,
    extended_hours: bool,
    runtime: Trading212ToolRuntime,
) -> ToolResult:
    set_trace_metadata(
        provider="trading212",
        tool_name="t212_prepare_order",
        state_changing=False,
    )
    try:
        prepared = runtime.service.prepare_order(
            order_type=order_type,
            side=side,
            ticker=ticker,
            quantity=quantity,
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force=time_validity,
            extended_hours=extended_hours,
        )
    except BrokerInstrumentResolutionError as exc:
        return _instrument_resolution_tool_error(exc)
    except ValueError as exc:
        return _tool_error(str(exc), code="invalid_order_request")

    return ToolResult(
        status="ok",
        output=(
            "Prepared order only; nothing was submitted. "
            f"Fingerprint: {prepared.order_fingerprint}."
        ),
        data=prepared.model_dump(by_alias=True, exclude_none=True, mode="json"),
    )


@traceable(
    name="t212_prepare_order_action",
    run_type="tool"
)
def t212_prepare_order_action(
    *,
    order_type: str,
    side: str,
    ticker: str,
    quantity: str | int | float,
    limit_price: str | int | float | None,
    stop_price: str | int | float | None,
    time_validity: str,
    extended_hours: bool,
    runtime: Trading212ToolRuntime,
) -> ToolResult:
    set_trace_metadata(
        provider="trading212",
        tool_name="t212_prepare_order_action",
        state_changing=False,
    )
    if runtime.pending_action_service is None or not runtime.chat_id:
        return _tool_error(
            "Pending-action runtime is not configured for order preparation.",
            code="missing_pending_action_runtime",
            hint="Run this tool through the order agent inside a Telegram-bound runtime.",
        )

    try:
        prepared = runtime.service.prepare_order(
            order_type=order_type,
            side=side,
            ticker=ticker,
            quantity=quantity,
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force=time_validity,
            extended_hours=extended_hours,
        )
    except BrokerInstrumentResolutionError as exc:
        return _instrument_resolution_tool_error(exc)
    except ValueError as exc:
        return _tool_error(str(exc), code="invalid_order_request")

    action = runtime.pending_action_service.create_submit_action(
        chat_id=runtime.chat_id,
        user_id=runtime.user_id,
        prepared_order=prepared,
        original_user_message=runtime.user_message or "",
        summary_text=_format_prepared_order_action_summary(prepared),
        expires_at=approval_expiry(
            kind=PendingActionKind.SUBMIT_ORDER,
            order_type=prepared.order_type.value,
        ),
    )
    return ToolResult(
        status="ok",
        output=_approval_message_text(action),
        data={
            "pendingAction": action.model_dump(mode="json"),
            "telegramApproval": _approval_payload(action),
        },
    )


@traceable(
    name="t212_prepare_cancel_action",
    run_type="tool"
)
def t212_prepare_cancel_action(
    *,
    order_id: int | None,
    selector: str | None,
    reason: str | None,
    runtime: Trading212ToolRuntime,
) -> ToolResult:
    set_trace_metadata(
        provider="trading212",
        tool_name="t212_prepare_cancel_action",
        state_changing=False,
    )
    if runtime.pending_action_service is None or not runtime.chat_id:
        return _tool_error(
            "Pending-action runtime is not configured for cancellation preparation.",
            code="missing_pending_action_runtime",
            hint="Run this tool through the order agent inside a Telegram-bound runtime.",
        )

    try:
        target_order = _resolve_cancel_target(
            runtime.service.list_pending_orders(),
            order_id=order_id,
            selector=selector,
        )
    except ValueError as exc:
        return _tool_error(
            str(exc),
            code="ambiguous_cancel_target",
            hint=(
                "Provide an explicit pending order id, or use a deterministic selector "
                "such as oldest or latest."
            ),
        )

    action = runtime.pending_action_service.create_cancel_action(
        chat_id=runtime.chat_id,
        user_id=runtime.user_id,
        target_order=target_order,
        original_user_message=runtime.user_message or "",
        summary_text=_format_cancel_action_summary(target_order, reason=reason),
        expires_at=approval_expiry(kind=PendingActionKind.CANCEL_ORDER),
    )
    return ToolResult(
        status="ok",
        output=_approval_message_text(action),
        data={
            "pendingAction": action.model_dump(mode="json"),
            "telegramApproval": _approval_payload(action),
        },
    )


@traceable(
    name="t212_place_order",
    run_type="tool"
)
def t212_place_order(
    *,
    order_type: str,
    side: str,
    ticker: str,
    quantity: str | int | float,
    limit_price: str | int | float | None,
    stop_price: str | int | float | None,
    time_validity: str,
    extended_hours: bool,
    confirmed: bool,
    confirmation_reference: str | None,
    runtime: Trading212ToolRuntime,
) -> ToolResult:
    set_trace_metadata(
        provider="trading212",
        tool_name="t212_place_order",
        state_changing=True,
        runtime_allows_state_changes=runtime.allow_state_changes,
    )
    if not runtime.allow_state_changes:
        return _tool_error(
            "Trading 212 state-changing tools are disabled for this runtime.",
            code="state_changes_disabled",
        )
    if not confirmed:
        return _tool_error(
            "Order submission requires explicit user confirmation.",
            code="confirmation_required",
        )

    try:
        prepared = runtime.service.prepare_order(
            order_type=order_type,
            side=side,
            ticker=ticker,
            quantity=quantity,
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force=time_validity,
            extended_hours=extended_hours,
        )
    except BrokerInstrumentResolutionError as exc:
        return _instrument_resolution_tool_error(exc)
    except ValueError as exc:
        return _tool_error(str(exc), code="invalid_order_request")

    if confirmation_reference != prepared.order_fingerprint:
        return _tool_error(
            "confirmation_reference does not match the prepared order fingerprint.",
            code="fingerprint_mismatch",
            details={"expected_fingerprint": prepared.order_fingerprint},
        )

    result = runtime.service.submit_prepared_order(prepared)
    return ToolResult(
        status="ok",
        output=result.message or "Order submitted to Trading 212.",
        data=result.model_dump(by_alias=True, exclude_none=True, mode="json"),
    )


@traceable(
    name="t212_cancel_order",
    run_type="tool"
)
def t212_cancel_order(
    *,
    order_id: int,
    confirmed: bool,
    reason: str | None,
    runtime: Trading212ToolRuntime,
) -> ToolResult:
    set_trace_metadata(
        provider="trading212",
        tool_name="t212_cancel_order",
        state_changing=True,
        runtime_allows_state_changes=runtime.allow_state_changes,
    )
    del reason
    if not runtime.allow_state_changes:
        return _tool_error(
            "Trading 212 state-changing tools are disabled for this runtime.",
            code="state_changes_disabled",
        )
    if not confirmed:
        return _tool_error(
            "Order cancellation requires explicit user confirmation.",
            code="confirmation_required",
        )

    result = runtime.service.cancel_order(str(order_id))
    return ToolResult(
        status="ok",
        output=result.message or f"Cancellation requested for order {order_id}.",
        data=result.model_dump(by_alias=True, exclude_none=True, mode="json"),
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
    orders: list[Order],
    *,
    order_id: int | None,
    selector: str | None,
) -> Order:
    if order_id is not None:
        for order in orders:
            if order.id == int(order_id):
                return order
        raise ValueError(f"Pending order {order_id} was not found.")
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
