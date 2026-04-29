"""Generic broker tool facade for capability-backed broker operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable

from t212ai.capabilities.protocols import BrokerExecutionService, BrokerReadService
from t212ai.genai.models import ToolError, ToolResult, ToolSpec
from t212ai.genai.tools.base import ToolBox, build_tool_index
from t212ai.genai.tracing import (
    _trace_tool_function_inputs,
    _trace_tool_function_outputs,
    set_trace_metadata,
    traceable,
)
from t212ai.pending_actions import PendingActionKind, PendingActionService, approval_expiry

from .models import BrokerOrder, PreparedBrokerOrder


@dataclass(slots=True)
class BrokerToolRuntime:
    broker_read_service: BrokerReadService | None = None
    broker_execution_service: BrokerExecutionService | None = None
    broker_provider: str = "broker"
    allow_state_changes: bool = False
    pending_action_service: PendingActionService | None = None
    chat_id: str | None = None
    user_id: int | None = None
    user_message: str | None = None


BROKER_GET_PORTFOLIO_SNAPSHOT_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "broker_get_portfolio_snapshot",
        "description": (
            "Read-only broker portfolio snapshot. Returns account summary, "
            "open positions, and pending orders from the configured broker."
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

BROKER_LIST_PENDING_ORDERS_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "broker_list_pending_orders",
        "description": "Read-only list of active or pending orders from the configured broker.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
}

BROKER_GET_ORDER_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "broker_get_order",
        "description": "Read-only lookup for one broker order by broker-native order reference.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "order_ref": {
                    "type": "string",
                    "description": "Broker-native order reference.",
                },
            },
            "required": ["order_ref"],
            "additionalProperties": False,
        },
    },
}

BROKER_LIST_HISTORICAL_ORDERS_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "broker_list_historical_orders",
        "description": (
            "Read-only recent broker historical orders page. Useful for reconciliation "
            "or direct order-history review."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "cursor": {
                    "type": ["string", "integer", "null"],
                    "default": None,
                },
                "ticker": {
                    "type": ["string", "null"],
                    "default": None,
                },
                "limit": {
                    "type": ["integer", "null"],
                    "default": None,
                },
            },
            "required": ["cursor", "ticker", "limit"],
            "additionalProperties": False,
        },
    },
}

_BROKER_ORDER_ARGUMENTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "order_type": {
            "type": "string",
            "enum": ["MARKET", "LIMIT", "STOP", "STOP_LIMIT"],
            "description": "Broker order type.",
        },
        "side": {
            "type": "string",
            "enum": ["BUY", "SELL"],
            "description": "Trade direction.",
        },
        "ticker": {
            "type": "string",
            "description": "Broker instrument ticker or symbol.",
        },
        "quantity": {
            "type": ["number", "string"],
            "description": "Positive share quantity before side is applied.",
        },
        "limit_price": {
            "type": ["number", "string", "null"],
            "default": None,
        },
        "stop_price": {
            "type": ["number", "string", "null"],
            "default": None,
        },
        "time_in_force": {
            "type": "string",
            "enum": ["DAY", "GOOD_TILL_CANCEL"],
            "default": "DAY",
        },
        "extended_hours": {
            "type": "boolean",
            "default": False,
        },
    },
    "required": [
        "order_type",
        "side",
        "ticker",
        "quantity",
        "limit_price",
        "stop_price",
        "time_in_force",
        "extended_hours",
    ],
    "additionalProperties": False,
}

BROKER_PREPARE_ORDER_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "broker_prepare_order",
        "description": (
            "Prepare a broker order without submitting it. Use this to validate "
            "a deterministic broker payload and fingerprint for confirmation."
        ),
        "strict": True,
        "parameters": _BROKER_ORDER_ARGUMENTS_SCHEMA,
    },
}

BROKER_PREPARE_ORDER_ACTION_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "broker_prepare_order_action",
        "description": (
            "Prepare a broker order action for user approval. This validates "
            "the order, persists a pending action, and returns approval metadata."
        ),
        "strict": True,
        "parameters": _BROKER_ORDER_ARGUMENTS_SCHEMA,
    },
}

BROKER_PREPARE_CANCEL_ACTION_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "broker_prepare_cancel_action",
        "description": "Prepare cancellation of a pending broker order for user approval.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "order_ref": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Explicit broker-native pending order reference to cancel.",
                },
                "selector": {
                    "type": ["string", "null"],
                    "enum": ["oldest", "latest", "only", None],
                    "default": None,
                },
                "reason": {
                    "type": ["string", "null"],
                    "default": None,
                },
            },
            "required": ["order_ref", "selector", "reason"],
            "additionalProperties": False,
        },
    },
}

BROKER_PLACE_ORDER_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "broker_place_order",
        "description": (
            "Submit a broker order after explicit user confirmation. This is "
            "state-changing and should only be enabled in an execution runtime."
        ),
        "strict": True,
        "parameters": {
            **_BROKER_ORDER_ARGUMENTS_SCHEMA,
            "properties": {
                **_BROKER_ORDER_ARGUMENTS_SCHEMA["properties"],
                "confirmed": {"type": "boolean"},
                "confirmation_reference": {
                    "type": ["string", "null"],
                    "default": None,
                },
            },
            "required": [
                *_BROKER_ORDER_ARGUMENTS_SCHEMA["required"],
                "confirmed",
                "confirmation_reference",
            ],
        },
    },
}

BROKER_CANCEL_ORDER_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "broker_cancel_order",
        "description": (
            "Cancel a pending broker order after explicit user confirmation. "
            "This is state-changing and should only be enabled in an execution runtime."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "order_ref": {
                    "type": "string",
                    "description": "Broker-native pending order reference to cancel.",
                },
                "confirmed": {"type": "boolean"},
                "reason": {
                    "type": ["string", "null"],
                    "default": None,
                },
            },
            "required": ["order_ref", "confirmed", "reason"],
            "additionalProperties": False,
        },
    },
}


def build_broker_read_toolbox() -> ToolBox:
    tools = [
        BROKER_GET_PORTFOLIO_SNAPSHOT_TOOL,
        BROKER_LIST_PENDING_ORDERS_TOOL,
        BROKER_GET_ORDER_TOOL,
        BROKER_LIST_HISTORICAL_ORDERS_TOOL,
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


def build_broker_order_action_toolbox() -> ToolBox:
    tools = [
        *build_broker_read_toolbox().tools,
        BROKER_PREPARE_ORDER_ACTION_TOOL,
        BROKER_PREPARE_CANCEL_ACTION_TOOL,
    ]
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


def build_broker_tool_mapping(runtime: BrokerToolRuntime) -> dict[str, Callable[..., ToolResult]]:
    return {
        "broker_get_portfolio_snapshot": lambda: broker_get_portfolio_snapshot(runtime=runtime),
        "broker_list_pending_orders": lambda: broker_list_pending_orders(runtime=runtime),
        "broker_get_order": lambda order_ref: broker_get_order(order_ref=order_ref, runtime=runtime),
        "broker_list_historical_orders": lambda **kwargs: broker_list_historical_orders(
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


@traceable(
    name="broker_get_portfolio_snapshot",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
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
        output=_format_portfolio_snapshot_output(snapshot, provider=runtime.broker_provider),
        data={
            "provider": runtime.broker_provider,
            "snapshot": snapshot.model_dump(by_alias=True, exclude_none=True, mode="json"),
        },
    )


@traceable(
    name="broker_list_pending_orders",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
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
        output=f"Retrieved {len(orders)} pending { _display_broker_name(runtime.broker_provider) } orders.",
        data={
            "provider": runtime.broker_provider,
            "orders": [order.model_dump(by_alias=True, exclude_none=True, mode="json") for order in orders],
        },
    )


@traceable(
    name="broker_get_order",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def broker_get_order(*, order_ref: str, runtime: BrokerToolRuntime) -> ToolResult:
    set_trace_metadata(provider=runtime.broker_provider, tool_name="broker_get_order")
    if runtime.broker_read_service is None:
        return _tool_error(
            "Broker read service is not configured.",
            code="broker_not_configured",
        )
    try:
        order = runtime.broker_read_service.get_order(str(order_ref))
    except Exception as exc:
        return _tool_exception(
            exc,
            runtime=runtime,
            operation="get_order",
            message=f"Unable to retrieve broker order {order_ref}.",
        )
    return ToolResult(
        status="ok",
        output=f"Retrieved { _display_broker_name(runtime.broker_provider) } order {order_ref}.",
        data={
            "provider": runtime.broker_provider,
            "order": order.model_dump(by_alias=True, exclude_none=True, mode="json"),
        },
    )


@traceable(
    name="broker_list_historical_orders",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
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
    name="broker_prepare_order",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def broker_prepare_order(
    *,
    order_type: str,
    side: str,
    ticker: str,
    quantity: str | int | float,
    limit_price: str | int | float | None,
    stop_price: str | int | float | None,
    time_in_force: str,
    extended_hours: bool,
    runtime: BrokerToolRuntime,
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
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def broker_prepare_order_action(
    *,
    order_type: str,
    side: str,
    ticker: str,
    quantity: str | int | float,
    limit_price: str | int | float | None,
    stop_price: str | int | float | None,
    time_in_force: str,
    extended_hours: bool,
    runtime: BrokerToolRuntime,
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
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
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
    try:
        target_order = _resolve_cancel_target(
            runtime.broker_read_service.list_pending_orders(),
            order_ref=order_ref,
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
        },
    )


@traceable(
    name="broker_place_order",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def broker_place_order(
    *,
    order_type: str,
    side: str,
    ticker: str,
    quantity: str | int | float,
    limit_price: str | int | float | None,
    stop_price: str | int | float | None,
    time_in_force: str,
    extended_hours: bool,
    confirmed: bool,
    confirmation_reference: str | None,
    runtime: BrokerToolRuntime,
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
    result = runtime.broker_execution_service.submit_prepared_order(prepared)
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
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
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
    result = runtime.broker_execution_service.cancel_order(str(order_ref))
    return ToolResult(
        status="ok",
        output=result.message or f"Cancellation requested for order {order_ref}.",
        data={
            "provider": runtime.broker_provider,
            "result": result.model_dump(by_alias=True, exclude_none=True, mode="json"),
        },
    )


def _prepare_order_or_error(
    *,
    runtime: BrokerToolRuntime,
    order_type: str,
    side: str,
    ticker: str,
    quantity: str | int | float,
    limit_price: str | int | float | None,
    stop_price: str | int | float | None,
    time_in_force: str,
    extended_hours: bool,
) -> PreparedBrokerOrder | ToolResult:
    if runtime.broker_execution_service is None:
        return _tool_error(
            "Broker execution service is not configured.",
            code="broker_not_configured",
        )
    try:
        return runtime.broker_execution_service.prepare_order(
            order_type=order_type,
            side=side,
            ticker=ticker,
            quantity=quantity,
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force=time_in_force,
            extended_hours=extended_hours,
        )
    except ValueError as exc:
        return _tool_error(str(exc), code="invalid_order_request")


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
    runtime: BrokerToolRuntime,
    operation: str,
    message: str,
) -> ToolResult:
    details: dict[str, Any] = {
        "operation": operation,
        "provider": runtime.broker_provider,
        "error_type": exc.__class__.__name__,
        "error": str(exc),
    }
    for attr in ("status_code", "body", "code"):
        value = getattr(exc, attr, None)
        if value is not None and str(value).strip():
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
            code="broker_provider_request_failed",
            type=exc.__class__.__name__,
            hint=_broker_provider_failure_hint(runtime.broker_provider),
            retryable=True,
            details=details,
        ),
    )


def _broker_provider_failure_hint(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized == "trading212":
        return (
            "Check BROKER_PROVIDER=trading212, T212_ENVIRONMENT, Trading 212 API key/secret, "
            "API scopes for account/portfolio/orders/history, IP restrictions, and rate limits."
        )
    if normalized == "alpaca":
        return (
            "Check BROKER_PROVIDER=alpaca, ALPACA_ENVIRONMENT, Alpaca API key/secret, "
            "paper/live account selection, account status, and rate limits."
        )
    return (
        "Check the selected broker provider credentials, account permissions, "
        "network access, and rate limits."
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
        "Approve with the Telegram buttons below, or reply yes/no, si/sì, "
        f"approve {action.action_id}, reject {action.action_id}."
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


def _format_portfolio_snapshot_output(snapshot, *, provider: str) -> str:
    account = snapshot.account
    cash = account.cash
    investments = account.investments
    provider_name = _display_broker_name(provider)
    lines = [
        f"{provider_name} portfolio snapshot.",
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
    if snapshot.positions:
        lines.append(f"Positions: {len(snapshot.positions)} open position(s).")
    else:
        lines.append(f"Positions: no open positions returned by {provider_name}.")
    if snapshot.pending_orders:
        lines.append(f"Pending orders: {len(snapshot.pending_orders)} active/pending order(s).")
    else:
        lines.append(f"Pending orders: no active/pending orders returned by {provider_name}.")
    return "\n".join(lines)


def _format_prepared_order_action_summary(
    prepared: PreparedBrokerOrder,
    *,
    provider: str,
) -> str:
    payload = prepared.request_payload
    provider_name = _display_broker_name(provider)
    return "\n".join(
        [
            f"Prepared {provider_name} order action.",
            "",
            "Action:",
            f"- side: {_format_value(prepared.side)}",
            f"- ticker: {_format_value(prepared.ticker)}",
            f"- order_type: {_format_value(prepared.order_type)}",
            f"- quantity: {_format_value(prepared.quantity)}",
            f"- signed_quantity: {_format_value(prepared.signed_quantity)}",
            f"- limit_price: {_format_value(payload.get('limitPrice'))}",
            f"- stop_price: {_format_value(payload.get('stopPrice'))}",
            f"- time_in_force: {_format_value(prepared.time_in_force)}",
            f"- extended_hours: {_format_value(prepared.extended_hours)}",
            f"- order_fingerprint: {_format_value(prepared.order_fingerprint)}",
        ]
    )


def _format_cancel_action_summary(
    order: BrokerOrder,
    *,
    provider: str,
    reason: str | None,
) -> str:
    provider_name = _display_broker_name(provider)
    lines = [
        f"Prepared {provider_name} cancellation action.",
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


def _display_broker_name(provider: str) -> str:
    if str(provider).strip().lower() == "trading212":
        return "Trading 212"
    return str(provider or "broker").replace("_", " ").strip().title() or "Broker"


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


# Compatibility-only static snapshots. Live runtime code should prefer the
# builder functions above so specialist tool exposure stays capability-driven.
BROKER_READ_TOOLBOX = build_broker_read_toolbox()
BROKER_ORDER_PLANNING_TOOLBOX = build_broker_order_planning_toolbox()
BROKER_ORDER_ACTION_TOOLBOX = build_broker_order_action_toolbox()
BROKER_EXECUTION_TOOLBOX = build_broker_execution_toolbox()
