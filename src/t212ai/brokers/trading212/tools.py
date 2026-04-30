"""Trading 212 agent tool definitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable

from t212ai.brokers.exceptions import BrokerInstrumentResolutionError
from t212ai.genai.models import ToolError, ToolResult, ToolSpec
from t212ai.genai.tracing import (
    _trace_tool_function_inputs,
    _trace_tool_function_outputs,
    set_trace_metadata,
    traceable,
)
from t212ai.genai.tools.tools import ToolBox, build_tool_index
from t212ai.pending_actions import PendingActionKind, PendingActionService, approval_expiry

from .models import Order, PortfolioSnapshot, Position
from .protocols import Trading212AgentBrokerProtocol


@dataclass(slots=True)
class Trading212ToolRuntime:
    service: Trading212AgentBrokerProtocol
    allow_state_changes: bool = False
    pending_action_service: PendingActionService | None = None
    chat_id: str | None = None
    user_id: int | None = None
    user_message: str | None = None


T212_GET_PORTFOLIO_SNAPSHOT_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "t212_get_portfolio_snapshot",
        "description": (
            "Read-only Trading 212 portfolio snapshot. Returns account summary, "
            "open positions, and pending orders."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
}

T212_LIST_PENDING_ORDERS_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "t212_list_pending_orders",
        "description": "Read-only list of active/pending Trading 212 orders.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
}

T212_GET_ORDER_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "t212_get_order",
        "description": "Read-only lookup for one pending Trading 212 order by id.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "integer",
                    "description": "Trading 212 order id.",
                },
            },
            "required": ["order_id"],
            "additionalProperties": False,
        },
    },
}

_ORDER_ARGUMENTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "order_type": {
            "type": "string",
            "enum": ["MARKET", "LIMIT", "STOP", "STOP_LIMIT"],
            "description": "Trading 212 order type.",
        },
        "side": {
            "type": "string",
            "enum": ["BUY", "SELL"],
            "description": "Trade direction. SELL is sent as negative quantity to Trading 212.",
        },
        "ticker": {
            "type": "string",
            "description": "Trading 212 instrument ticker, for example AAPL_US_EQ.",
        },
        "quantity": {
            "type": ["number", "string"],
            "description": "Positive share quantity before side is applied.",
        },
        "limit_price": {
            "type": ["number", "string", "null"],
            "default": None,
            "description": "Required for LIMIT and STOP_LIMIT orders.",
        },
        "stop_price": {
            "type": ["number", "string", "null"],
            "default": None,
            "description": "Required for STOP and STOP_LIMIT orders.",
        },
        "time_validity": {
            "type": "string",
            "enum": ["DAY", "GOOD_TILL_CANCEL"],
            "default": "DAY",
            "description": "Expiration for non-market orders.",
        },
        "extended_hours": {
            "type": "boolean",
            "default": False,
            "description": "Only supported by Trading 212 market orders.",
        },
    },
    "required": [
        "order_type",
        "side",
        "ticker",
        "quantity",
        "limit_price",
        "stop_price",
        "time_validity",
        "extended_hours",
    ],
    "additionalProperties": False,
}

T212_PREPARE_ORDER_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "t212_prepare_order",
        "description": (
            "Prepare a Trading 212 order without submitting it. Use this to convert "
            "natural language into a validated order payload and fingerprint for "
            "human confirmation."
        ),
        "strict": True,
        "parameters": _ORDER_ARGUMENTS_SCHEMA,
    },
}

T212_PREPARE_ORDER_ACTION_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "t212_prepare_order_action",
        "description": (
            "Prepare a Trading 212 order action for user approval. This validates "
            "the order, persists a pending action, and returns approval metadata."
        ),
        "strict": True,
        "parameters": _ORDER_ARGUMENTS_SCHEMA,
    },
}

T212_PREPARE_CANCEL_ACTION_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "t212_prepare_cancel_action",
        "description": (
            "Prepare cancellation of a pending Trading 212 order for user approval."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": ["integer", "null"],
                    "default": None,
                    "description": "Explicit Trading 212 pending order id to cancel.",
                },
                "selector": {
                    "type": ["string", "null"],
                    "enum": ["oldest", "latest", "only", None],
                    "default": None,
                    "description": "Fallback selector when no explicit order id is given.",
                },
                "reason": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Optional user reason for the cancellation request.",
                },
            },
            "required": ["order_id", "selector", "reason"],
            "additionalProperties": False,
        },
    },
}

T212_PLACE_ORDER_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "t212_place_order",
        "description": (
            "Submit a Trading 212 order after explicit user confirmation. This is "
            "state-changing and must only be enabled in an execution toolbox."
        ),
        "strict": True,
        "parameters": {
            **_ORDER_ARGUMENTS_SCHEMA,
            "properties": {
                **_ORDER_ARGUMENTS_SCHEMA["properties"],
                "confirmed": {
                    "type": "boolean",
                    "description": "Must be true only after explicit user confirmation.",
                },
                "confirmation_reference": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": (
                        "The order_fingerprint returned by t212_prepare_order for "
                        "the same order payload."
                    ),
                },
            },
            "required": [
                *_ORDER_ARGUMENTS_SCHEMA["required"],
                "confirmed",
                "confirmation_reference",
            ],
        },
    },
}

T212_CANCEL_ORDER_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "t212_cancel_order",
        "description": (
            "Cancel a pending Trading 212 order after explicit user confirmation. "
            "This is state-changing and must only be enabled in an execution toolbox."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "integer",
                    "description": "Trading 212 pending order id to cancel.",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "Must be true only after explicit user confirmation.",
                },
                "reason": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Optional short reason from the user or workflow.",
                },
            },
            "required": ["order_id", "confirmed", "reason"],
            "additionalProperties": False,
        },
    },
}


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


@traceable(
    name="t212_get_portfolio_snapshot",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
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
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
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
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def t212_get_order(*, order_id: int, runtime: Trading212ToolRuntime) -> ToolResult:
    set_trace_metadata(provider="trading212", tool_name="t212_get_order")
    order = runtime.service.get_order(str(order_id))
    return ToolResult(
        status="ok",
        output=f"Retrieved Trading 212 order {order_id}.",
        data=order.model_dump(by_alias=True, exclude_none=True, mode="json"),
    )


@traceable(
    name="t212_prepare_order",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
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
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
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
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
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
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
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
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
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


def _instrument_resolution_tool_error(exc: BrokerInstrumentResolutionError) -> ToolResult:
    return _tool_error(
        str(exc),
        code="invalid_order_request",
        hint=(
            "Use one of error.details.resolution.candidates[].ticker values "
            "and prepare the order again."
        ),
        details=exc.details(),
    )


def _tool_error(
    message: str,
    *,
    code: str,
    hint: str | None = None,
    details: dict[str, Any] | None = None,
) -> ToolResult:
    return ToolResult(
        status="error",
        error=ToolError(
            message=message,
            code=code,
            hint=hint,
            retryable=False,
            details=details,
        ),
    )


def _tool_exception(
    exc: Exception,
    *,
    operation: str,
    message: str,
    hint: str,
) -> ToolResult:
    details: dict[str, Any] = {
        "operation": operation,
        "error_type": exc.__class__.__name__,
        "error": str(exc),
    }
    for attr in ("status_code", "body"):
        value = getattr(exc, attr, None)
        if value:
            details[attr] = _truncate(str(value), 600)
    rate_limit = getattr(exc, "rate_limit", None)
    if rate_limit is not None and hasattr(rate_limit, "__dict__"):
        details["rate_limit"] = {
            key: value
            for key, value in rate_limit.__dict__.items()
            if value is not None
        }

    return ToolResult(
        status="error",
        error=ToolError(
            message=f"{message} Reason: {exc}",
            code="broker_snapshot_failed",
            type=exc.__class__.__name__,
            hint=hint,
            retryable=True,
            details=details,
        ),
    )


def _format_portfolio_snapshot_output(snapshot: PortfolioSnapshot) -> str:
    account = snapshot.account
    cash = account.cash
    investments = account.investments
    lines = [
        "Trading 212 portfolio snapshot.",
        "Authority: broker-authoritative for account, positions, cash, and pending orders.",
        f"As of: {_format_value(snapshot.as_of)}.",
        (
            "Account: "
            f"id={_format_value(account.id)}, "
            f"currency={_format_value(account.currency)}, "
            f"total_value={_format_money(account.total_value, account.currency)}."
        ),
    ]
    if cash:
        lines.append(
            "Cash: "
            f"available_to_trade={_format_money(cash.available_to_trade, account.currency)}, "
            f"reserved_for_orders={_format_money(cash.reserved_for_orders, account.currency)}, "
            f"in_pies={_format_money(cash.in_pies, account.currency)}."
        )
    if investments:
        lines.append(
            "Investments: "
            f"current_value={_format_money(investments.current_value, account.currency)}, "
            f"total_cost={_format_money(investments.total_cost, account.currency)}, "
            "unrealized_pnl="
            f"{_format_money(investments.unrealized_profit_loss, account.currency)}, "
            f"realized_pnl={_format_money(investments.realized_profit_loss, account.currency)}."
        )

    lines.extend(_format_positions(snapshot.positions))
    lines.extend(_format_pending_orders(snapshot.pending_orders))
    lines.append(
        "Decision note: use this as the source of truth for broker state, but fetch fresh "
        "market/news context before making recommendations that depend on current prices "
        "or external events."
    )
    return "\n".join(lines)


def _format_positions(positions: list[Position]) -> list[str]:
    if not positions:
        return ["Positions: no open positions returned by Trading 212."]

    lines = [f"Positions: {len(positions)} open position(s)."]
    for position in positions:
        instrument = position.instrument
        wallet = position.wallet_impact
        ticker = position.ticker if hasattr(position, "ticker") else None
        ticker = ticker or (instrument.ticker if instrument else None)
        name = instrument.name if instrument else None
        currency = (wallet.currency if wallet else None) or (
            instrument.currency if instrument else None
        )
        lines.append(
            "- "
            f"{_format_value(ticker)}"
            f"{f' ({name})' if name else ''}: "
            f"quantity={_format_value(position.quantity)}, "
            f"available={_format_value(position.quantity_available_for_trading)}, "
            f"in_pies={_format_value(position.quantity_in_pies)}, "
            f"avg_price={_format_money(position.average_price_paid, currency)}, "
            f"current_price={_format_money(position.current_price, currency)}, "
            f"current_value={_format_money(wallet.current_value if wallet else None, currency)}, "
            f"total_cost={_format_money(wallet.total_cost if wallet else None, currency)}, "
            "unrealized_pnl="
            f"{_format_money(wallet.unrealized_profit_loss if wallet else None, currency)}, "
            f"fx_impact={_format_money(wallet.fx_impact if wallet else None, currency)}."
        )
    return lines


def _format_pending_orders(orders: list[Order]) -> list[str]:
    if not orders:
        return ["Pending orders: no active/pending orders returned by Trading 212."]

    lines = [f"Pending orders: {len(orders)} active/pending order(s)."]
    for order in orders:
        lines.append(
            "- "
            f"id={_format_value(order.id)}, "
            f"ticker={_format_value(order.ticker)}, "
            f"type={_format_value(order.type)}, "
            f"side={_format_value(order.side)}, "
            f"status={_format_value(order.status)}, "
            f"quantity={_format_value(order.quantity)}, "
            f"filled_quantity={_format_value(order.filled_quantity)}, "
            f"limit_price={_format_money(order.limit_price, order.currency)}, "
            f"stop_price={_format_money(order.stop_price, order.currency)}, "
            f"time_in_force={_format_value(order.time_in_force)}, "
            f"created_at={_format_value(order.created_at)}."
        )
    return lines


def _format_money(value: Any, currency: str | None) -> str:
    formatted = _format_value(value)
    if formatted == "unknown" or not currency:
        return formatted
    return f"{formatted} {currency}"


def _format_value(value: Any) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        return value.isoformat()
    raw_value = getattr(value, "value", value)
    return str(raw_value)


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3] + "..."


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


def _format_prepared_order_action_summary(prepared) -> str:
    payload = prepared.request_payload
    return "\n".join(
        [
            "Prepared Trading 212 order action.",
            "",
            "Action:",
            f"- side: {_format_value(prepared.side)}",
            f"- ticker: {_format_value(prepared.ticker)}",
            f"- order_type: {_format_value(prepared.order_type)}",
            f"- signed_quantity: {_format_value(prepared.signed_quantity)}",
            f"- limit_price: {_format_value(payload.get('limitPrice'))}",
            f"- stop_price: {_format_value(payload.get('stopPrice'))}",
            f"- time_validity: {_format_value(payload.get('timeValidity'))}",
            f"- extended_hours: {_format_value(payload.get('extendedHours'))}",
            f"- order_fingerprint: {_format_value(prepared.order_fingerprint)}",
        ]
    )


def _format_cancel_action_summary(order: Order, *, reason: str | None) -> str:
    lines = [
        "Prepared Trading 212 cancellation action.",
        "",
        "Target order:",
        f"- id: {_format_value(order.id)}",
        f"- ticker: {_format_value(order.ticker)}",
        f"- type: {_format_value(order.type)}",
        f"- side: {_format_value(order.side)}",
        f"- status: {_format_value(order.status)}",
        f"- quantity: {_format_value(order.quantity)}",
        f"- limit_price: {_format_money(order.limit_price, order.currency)}",
        f"- stop_price: {_format_money(order.stop_price, order.currency)}",
        f"- created_at: {_format_value(order.created_at)}",
    ]
    if reason:
        lines.append(f"- reason: {reason}")
    return "\n".join(lines)


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
