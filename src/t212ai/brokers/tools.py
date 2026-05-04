"""Generic broker tool facade for capability-backed broker operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any, Callable

from t212ai.capabilities.protocols import BrokerExecutionService, BrokerReadService, MarketDataService
from t212ai.genai.models import ToolError, ToolResult, ToolSpec
from t212ai.genai.tools.base import ToolBox, build_tool_index
from t212ai.genai.tracing import (
    set_trace_metadata,
    traceable,
)
from t212ai.pending_actions import PendingActionKind, PendingActionService, approval_expiry

from .exceptions import BrokerInstrumentResolutionError
from .models import BrokerOrder, PreparedBrokerOrder
from .references import (
    BrokerReferenceKind,
    BrokerReferenceMap,
    UnknownBrokerPublicReference,
)


@dataclass(slots=True)
class BrokerToolRuntime:
    broker_read_service: BrokerReadService | None = None
    broker_execution_service: BrokerExecutionService | None = None
    broker_provider: str = "broker"
    allow_state_changes: bool = False
    pending_action_service: PendingActionService | None = None
    market_data_service: MarketDataService | None = None
    chat_id: str | None = None
    user_id: int | None = None
    user_message: str | None = None
    reference_map: BrokerReferenceMap | None = None


@dataclass(frozen=True, slots=True)
class _SizingContext:
    notional_amount: Decimal
    notional_currency: str | None
    price: Decimal
    source: str
    quantity: Decimal


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
        "description": (
            "Read-only lookup for one broker order. Prefer the ORDER_000001-style "
            "public reference returned by broker_list_pending_orders; broker-native "
            "refs are still accepted for compatibility."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "order_ref": {
                    "type": "string",
                    "description": "Public ORDER_000001 reference or broker-native order reference.",
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

BROKER_GET_INSTRUMENT_SNAPSHOT_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "broker_get_instrument_snapshot",
        "description": (
            "Read-only broker-authoritative instrument metadata snapshot for a "
            "ticker, symbol, ISIN, or company name. Use this when order planning "
            "needs tradability, broker-native ticker, currency, instrument type, "
            "or provider-specific instrument constraints."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Ticker, broker-native ticker, ISIN, or instrument/company name.",
                },
            },
            "required": ["ticker"],
            "additionalProperties": False,
        },
    },
}

BROKER_RESOLVE_INSTRUMENT_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "broker_resolve_instrument",
        "description": (
            "Resolve a user-facing ticker, public symbol, ISIN, or instrument name "
            "into broker-native tradable instrument candidates. Use this before "
            "preparing orders when the broker may require its own instrument id "
            "(for example Trading 212 tickers from /metadata/instruments). "
            "Inspect resolution.status: only use resolvedTicker when status is "
            "resolved; if ambiguous or not_found, do not guess."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Ticker, broker ticker, ISIN, or instrument/company name.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 8,
                    "description": "Maximum number of candidates to return.",
                },
            },
            "required": ["query", "limit"],
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
            "description": (
                "Broker-native instrument ticker or symbol. For Trading 212, resolve "
                "public symbols with broker_resolve_instrument first when needed, "
                "and pass only a resolved broker-native ticker into order preparation."
            ),
        },
        "quantity": {
            "type": ["number", "null"],
            "default": None,
            "description": (
                "Resolved positive share quantity before side is applied. Must be a "
                "decimal-compatible value only, not a natural-language amount, formula, "
                "percentage, or broker-state reference. Use null when the user specified "
                "a resolved cash/notional amount instead."
            ),
        },
        "notional_amount": {
            "type": ["number", "null"],
            "default": None,
            "description": (
                "Resolved numeric cash amount to convert into share quantity, for example "
                "200 for 'around 200 euros'. Must be decimal-compatible only. Do not pass "
                "phrases such as 'half available cash', percentages, formulas, or broker-state "
                "references. If the value depends on broker state, first fetch that state, "
                "calculate the decimal amount, then call this tool with the resolved value."
            ),
        },
        "notional_currency": {
            "type": ["string", "null"],
            "default": None,
            "description": (
                "Currency of a resolved numeric notional_amount, for example EUR or USD."
            ),
        },
        "limit_price": {
            "type": ["number", "null"],
            "default": None,
            "description": "Resolved numeric limit price only. Must be decimal-compatible.",
        },
        "stop_price": {
            "type": ["number", "null"],
            "default": None,
            "description": "Resolved numeric stop price only. Must be decimal-compatible.",
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
        "notional_amount",
        "notional_currency",
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
                    "description": (
                        "Explicit ORDER_000001 public reference from broker_list_pending_orders, "
                        "or a broker-native pending order reference."
                    ),
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
                    "description": (
                        "ORDER_000001 public reference from broker_list_pending_orders, "
                        "or a broker-native pending order reference."
                    ),
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


@traceable(
    name="broker_get_portfolio_snapshot",
    run_type="tool"
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


@traceable(
    name="broker_prepare_order",
    run_type="tool"
)
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


def _prepare_order_or_error(
    *,
    runtime: BrokerToolRuntime,
    order_type: str,
    side: str,
    ticker: str,
    quantity: str | int | float | None,
    notional_amount: str | int | float | None,
    notional_currency: str | None,
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
    sizing_context: _SizingContext | None = None
    try:
        resolved_quantity: str | int | float | None = quantity
        if not _missing_value(resolved_quantity) and not _missing_value(notional_amount):
            raise ValueError(
                "Provide either quantity or notional_amount, not both. "
                "Use quantity for explicit share counts and notional_amount for cash-sized orders."
            )
        if _missing_value(resolved_quantity):
            sizing_context = _resolve_notional_quantity(
                runtime=runtime,
                order_type=order_type,
                side=side,
                ticker=ticker,
                notional_amount=notional_amount,
                notional_currency=notional_currency,
                limit_price=limit_price,
                stop_price=stop_price,
            )
            resolved_quantity = str(sizing_context.quantity)
        return runtime.broker_execution_service.prepare_order(
            order_type=order_type,
            side=side,
            ticker=ticker,
            quantity=resolved_quantity,
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force=time_in_force,
            extended_hours=extended_hours,
        ).model_copy(
            update=(
                {
                    "requested_notional_amount": sizing_context.notional_amount,
                    "requested_notional_currency": sizing_context.notional_currency,
                    "sizing_price": sizing_context.price,
                    "sizing_price_source": sizing_context.source,
                }
                if sizing_context is not None
                else {}
            )
        )
    except BrokerInstrumentResolutionError as exc:
        return _instrument_resolution_tool_error(exc)
    except ValueError as exc:
        error_text = str(exc)
        return _tool_error(
            error_text,
            code="invalid_order_request",
            hint=(
                "Provide either a share quantity or a notional_amount. For cash-sized "
                "market buy orders, ensure market data is configured; for sell market "
                "orders, ensure broker portfolio read access is available."
                if "notional" in error_text or "quantity" in error_text
                else (
                    "Resolve the instrument with broker_resolve_instrument and prepare "
                    "the order again using the broker-native ticker."
                )
            ),
        )
    except Exception as exc:
        return _tool_exception(
            exc,
            runtime=runtime,
            operation="prepare_order",
            message="Unable to prepare broker order.",
        )


def _resolve_notional_quantity(
    *,
    runtime: BrokerToolRuntime,
    order_type: str,
    side: str,
    ticker: str,
    notional_amount: str | int | float | None,
    notional_currency: str | None,
    limit_price: str | int | float | None,
    stop_price: str | int | float | None,
) -> _SizingContext:
    if _missing_value(notional_amount):
        raise ValueError(
            "quantity is required unless notional_amount is provided. "
            "For cash-sized orders, provide notional_amount and notional_currency."
        )
    amount = _positive_decimal(notional_amount, "notional_amount")
    currency = _normalize_currency(notional_currency)
    explicit_price = _explicit_sizing_price(
        order_type=order_type,
        limit_price=limit_price,
        stop_price=stop_price,
    )
    if explicit_price is not None:
        price, source = explicit_price
        return _sizing_context(amount=amount, currency=currency, price=price, source=source)

    if str(side or "").strip().upper() == "SELL":
        price, price_currency, source = _portfolio_sizing_price(runtime=runtime, ticker=ticker)
        _validate_sizing_currency(currency, price_currency, source=source)
        return _sizing_context(
            amount=amount,
            currency=currency or price_currency,
            price=price,
            source=source,
        )

    price, price_currency, source = _market_sizing_price(runtime=runtime, ticker=ticker)
    _validate_sizing_currency(currency, price_currency, source=source)
    return _sizing_context(
        amount=amount,
        currency=currency or price_currency,
        price=price,
        source=source,
    )


def _explicit_sizing_price(
    *,
    order_type: str,
    limit_price: str | int | float | None,
    stop_price: str | int | float | None,
) -> tuple[Decimal, str] | None:
    resolved_type = str(order_type or "").strip().upper()
    if resolved_type in {"LIMIT", "STOP_LIMIT"} and not _missing_value(limit_price):
        return _positive_decimal(limit_price, "limit_price"), "explicit_limit_price"
    if resolved_type == "STOP" and not _missing_value(stop_price):
        return _positive_decimal(stop_price, "stop_price"), "explicit_stop_price"
    return None


def _portfolio_sizing_price(
    *,
    runtime: BrokerToolRuntime,
    ticker: str,
) -> tuple[Decimal, str | None, str]:
    if runtime.broker_read_service is None:
        raise ValueError(
            "Cannot size sell order from notional_amount because broker portfolio "
            "read access is unavailable and no explicit limit/stop price was provided."
        )
    snapshot = runtime.broker_read_service.get_portfolio_snapshot()
    requested = str(ticker or "").strip()
    matched = None
    for position in snapshot.positions:
        instrument = position.instrument
        position_ticker = str(instrument.ticker or "").strip() if instrument else ""
        if position_ticker == requested:
            matched = position
            break
    if matched is None:
        for position in snapshot.positions:
            instrument = position.instrument
            position_ticker = str(instrument.ticker or "").strip() if instrument else ""
            if position_ticker.upper() == requested.upper():
                matched = position
                break
    if matched is None:
        holdings = _portfolio_holdings_for_sizing_error(snapshot.positions)
        raise ValueError(
            "Cannot size sell order from notional_amount because the prepared ticker "
            f"{requested!r} did not match a current portfolio holding. Current holdings: {holdings}"
        )
    price = _positive_decimal(matched.current_price, "currentPrice")
    instrument = matched.instrument
    wallet = matched.wallet_impact
    currency = (
        str(instrument.currency or "").strip().upper()
        if instrument and instrument.currency
        else None
    ) or (
        str(wallet.currency or "").strip().upper()
        if wallet and wallet.currency
        else None
    )
    return price, currency, "portfolio_current_price"


def _market_sizing_price(
    *,
    runtime: BrokerToolRuntime,
    ticker: str,
) -> tuple[Decimal, str | None, str]:
    if runtime.market_data_service is None:
        raise ValueError(
            "Cannot size buy market order from notional_amount because no explicit "
            "limit/stop price was provided and market data is unavailable."
        )
    symbols = _market_data_symbols(runtime=runtime, ticker=ticker)
    if not symbols:
        raise ValueError(
            "Cannot size buy market order from notional_amount because no market-data "
            "symbol could be derived from the requested broker ticker."
        )
    quotes = runtime.market_data_service.get_quote_snapshot(symbols)
    for symbol in symbols:
        quote = quotes.quotes.get(symbol) or quotes.quotes.get(symbol.upper())
        if not quote:
            continue
        try:
            price = _positive_decimal(quote.get("price"), "market price")
        except ValueError:
            continue
        currency = _normalize_currency(quote.get("currency"))
        return price, currency, f"market_data_quote:{symbol}"
    raise ValueError(
        "Cannot size buy market order from notional_amount because market data did "
        f"not return a usable price for {', '.join(symbols)}."
    )


def _market_data_symbols(*, runtime: BrokerToolRuntime, ticker: str) -> list[str]:
    symbols: list[str] = []

    def add(value: Any) -> None:
        raw = str(value or "").strip()
        if raw and raw not in symbols:
            symbols.append(raw)

    add(ticker)
    add(str(ticker or "").split("_", 1)[0])
    resolver = runtime.broker_read_service or runtime.broker_execution_service
    try:
        resolution = resolver.resolve_instrument(ticker, limit=3) if resolver is not None else None
    except Exception:
        resolution = None
    if resolution is not None:
        add(resolution.resolved_ticker)
        if resolution.resolved_ticker:
            add(str(resolution.resolved_ticker).split("_", 1)[0])
        for candidate in resolution.candidates:
            add(candidate.ticker)
            add(str(candidate.ticker).split("_", 1)[0])
        search = getattr(runtime.market_data_service, "search_symbols", None)
        if callable(search):
            for candidate in resolution.candidates[:2]:
                for query in (candidate.name, candidate.short_name):
                    if not query:
                        continue
                    try:
                        result = search(str(query), quotes_count=5, news_count=0)
                    except Exception:
                        continue
                    for market_candidate in result.candidates:
                        add(market_candidate.get("symbol"))
    return symbols


def _sizing_context(
    *,
    amount: Decimal,
    currency: str | None,
    price: Decimal,
    source: str,
) -> _SizingContext:
    quantity = (amount / price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    if quantity <= 0:
        raise ValueError(
            "notional_amount is too small to produce a positive share quantity "
            f"at sizing price {price}."
        )
    return _SizingContext(
        notional_amount=amount,
        notional_currency=currency,
        price=price,
        source=source,
        quantity=quantity,
    )


def _validate_sizing_currency(
    requested_currency: str | None,
    price_currency: str | None,
    *,
    source: str,
) -> None:
    if not requested_currency or not price_currency:
        return
    if requested_currency != price_currency:
        raise ValueError(
            "Cannot size order from notional_amount because the requested currency "
            f"{requested_currency} does not match the sizing price currency "
            f"{price_currency} from {source}."
        )


def _portfolio_holdings_for_sizing_error(positions) -> str:
    if not positions:
        return "none"
    parts = []
    for position in positions:
        instrument = position.instrument
        parts.append(
            "{"
            f"name={_format_value(instrument.name if instrument else None)}, "
            f"ticker={_format_value(instrument.ticker if instrument else None)}, "
            f"quantityAvailableForTrading={_format_value(position.quantity_available_for_trading)}, "
            f"currentPrice={_format_value(position.current_price)}"
            "}"
        )
    return "; ".join(parts)


def _missing_value(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _positive_decimal(value: Any, field_name: str) -> Decimal:
    if _missing_value(value):
        raise ValueError(f"{field_name} is required.")
    try:
        resolved = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} must be a valid decimal number.") from exc
    if resolved <= 0:
        raise ValueError(f"{field_name} must be greater than zero.")
    return resolved


def _normalize_currency(value: Any) -> str | None:
    raw = str(value or "").strip().upper()
    return raw or None


def _reference_map(runtime: BrokerToolRuntime) -> BrokerReferenceMap:
    if runtime.reference_map is None:
        runtime.reference_map = BrokerReferenceMap()
    return runtime.reference_map


def _resolve_order_ref(
    order_ref: str | None,
    *,
    runtime: BrokerToolRuntime,
) -> str | None | ToolResult:
    if order_ref is None:
        return None
    raw = str(order_ref).strip()
    if not raw:
        return None
    if _looks_like_public_ref(raw, BrokerReferenceKind.ORDER):
        try:
            return _reference_map(runtime).resolve(
                BrokerReferenceKind.ORDER,
                raw,
                provider=runtime.broker_provider,
            ).true_ref
        except UnknownBrokerPublicReference:
            return _unknown_public_reference_error(
                raw,
                kind=BrokerReferenceKind.ORDER,
            )
    return raw


def _looks_like_public_ref(value: str | None, kind: BrokerReferenceKind) -> bool:
    raw = str(value or "").strip().upper()
    return raw.startswith(f"{kind.value}_")


def _unknown_public_reference_error(
    public_ref: str,
    *,
    kind: BrokerReferenceKind,
) -> ToolResult:
    return _tool_error(
        f"Unknown {kind.value.lower()} public reference {public_ref!r}.",
        code="unknown_public_reference",
        hint=(
            "Call broker_list_pending_orders again for order references, or "
            "broker_get_portfolio_snapshot again for position references. "
            "Public references are scoped to one agent interaction and are not durable."
        ),
        details={"kind": kind.value, "public_ref": public_ref},
    )


def _register_order_public_ref(
    order: BrokerOrder,
    *,
    runtime: BrokerToolRuntime,
    fallback_true_ref: str | None = None,
) -> str | None:
    true_ref = _order_true_ref(order) or _non_empty_str(fallback_true_ref)
    if true_ref is None:
        return None
    return _reference_map(runtime).register(
        BrokerReferenceKind.ORDER,
        provider=runtime.broker_provider,
        true_ref=true_ref,
    )


def _dump_order_with_public_ref(
    order: BrokerOrder,
    *,
    runtime: BrokerToolRuntime,
    fallback_true_ref: str | None = None,
) -> dict[str, Any]:
    payload = order.model_dump(by_alias=True, exclude_none=True, mode="json")
    true_ref = _order_true_ref(order) or _non_empty_str(fallback_true_ref)
    if true_ref is not None:
        payload["brokerOrderRef"] = true_ref
        public_ref = _register_order_public_ref(
            order,
            runtime=runtime,
            fallback_true_ref=true_ref,
        )
        if public_ref is not None:
            payload["publicOrderRef"] = public_ref
    return payload


def _dump_snapshot_with_public_refs(snapshot, *, runtime: BrokerToolRuntime) -> dict[str, Any]:
    payload = snapshot.model_dump(by_alias=True, exclude_none=True, mode="json")
    positions_payload = payload.get("positions")
    if isinstance(positions_payload, list):
        for index, position in enumerate(snapshot.positions):
            public_ref = _register_position_public_ref(
                position,
                index=index,
                runtime=runtime,
            )
            if public_ref is not None and index < len(positions_payload):
                positions_payload[index]["publicPositionRef"] = public_ref
            broker_position_ref = _native_position_ref(position)
            if broker_position_ref is not None and index < len(positions_payload):
                positions_payload[index]["brokerPositionRef"] = broker_position_ref

    pending_orders_payload = payload.get("pendingOrders")
    if isinstance(pending_orders_payload, list):
        for index, order in enumerate(snapshot.pending_orders):
            if index >= len(pending_orders_payload):
                continue
            pending_orders_payload[index].update(
                _dump_order_with_public_ref(order, runtime=runtime)
            )
    return payload


def _register_position_public_ref(
    position,
    *,
    index: int,
    runtime: BrokerToolRuntime,
) -> str | None:
    true_ref = _position_true_ref(position, index=index, provider=runtime.broker_provider)
    if true_ref is None:
        return None
    return _reference_map(runtime).register(
        BrokerReferenceKind.POSITION,
        provider=runtime.broker_provider,
        true_ref=true_ref,
    )


def _order_true_ref(order: BrokerOrder) -> str | None:
    return _non_empty_str(order.id)


def _position_true_ref(position, *, index: int, provider: str) -> str | None:
    native_ref = _native_position_ref(position)
    if native_ref is not None:
        return native_ref
    instrument = getattr(position, "instrument", None)
    ticker = _non_empty_str(getattr(instrument, "ticker", None)) if instrument else None
    isin = _non_empty_str(getattr(instrument, "isin", None)) if instrument else None
    name = _non_empty_str(getattr(instrument, "name", None)) if instrument else None
    currency = _non_empty_str(getattr(instrument, "currency", None)) if instrument else None
    if any((ticker, isin, name, currency)):
        return (
            f"derived-position:{provider}:"
            f"ticker={ticker or ''}:isin={isin or ''}:name={name or ''}:currency={currency or ''}"
        )
    return f"derived-position:{provider}:index={index}"


def _native_position_ref(position) -> str | None:
    for attr in ("id", "position_id", "positionId"):
        value = getattr(position, attr, None)
        if value is not None:
            resolved = _non_empty_str(value)
            if resolved is not None:
                return resolved
    raw_payload = getattr(position, "raw_provider_payload", None)
    if isinstance(raw_payload, dict):
        for key in ("id", "position_id", "positionId"):
            resolved = _non_empty_str(raw_payload.get(key))
            if resolved is not None:
                return resolved
    return None


def _non_empty_str(value: Any) -> str | None:
    raw = str(value or "").strip()
    return raw or None


def _tool_error(
    message: str,
    *,
    code: str,
    hint: str | None = None,
    details: dict[str, Any] | None = None,
) -> ToolResult:
    return ToolResult(
        status="error",
        output=_format_tool_error_output(
            message,
            code=code,
            hint=hint,
            details=details,
        ),
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
        output=_format_tool_error_output(
            f"{message} Reason: {exc}",
            code="broker_provider_request_failed",
            hint=_broker_provider_failure_hint(runtime.broker_provider),
            details=details,
        ),
        error=ToolError(
            message=f"{message} Reason: {exc}",
            code="broker_provider_request_failed",
            type=exc.__class__.__name__,
            hint=_broker_provider_failure_hint(runtime.broker_provider),
            retryable=True,
            details=details,
        ),
    )


def _instrument_resolution_tool_error(exc: BrokerInstrumentResolutionError) -> ToolResult:
    code = _instrument_resolution_error_code(exc)
    hint = _instrument_resolution_error_hint(exc)
    return ToolResult(
        status="error",
        output=_format_instrument_resolution_failure_output(
            exc,
            code=code,
            hint=hint,
        ),
        error=ToolError(
            message=str(exc),
            code=code,
            hint=hint,
            retryable=False,
            details=exc.details(),
        ),
    )


def _instrument_resolution_error_code(exc: BrokerInstrumentResolutionError) -> str:
    status = _enum_value(getattr(exc.resolution, "status", ""))
    if status == "ambiguous":
        return "ambiguous_broker_instrument"
    if status == "not_found":
        return "broker_instrument_not_found"
    if status == "resolved":
        return "broker_instrument_mismatch"
    return "instrument_resolution_failed"


def _instrument_resolution_error_hint(exc: BrokerInstrumentResolutionError) -> str:
    status = _enum_value(getattr(exc.resolution, "status", ""))
    if status == "ambiguous":
        return (
            "Do not guess. Ask the user to confirm one candidate, or retry "
            "broker_resolve_instrument with an ISIN, company name, exchange, or currency. "
            "Then prepare the order again with the exact broker-native ticker."
        )
    if status == "not_found":
        return (
            "Retry broker_resolve_instrument with a broader company name, ISIN, or "
            "more precise exchange/currency context. If no candidate is returned, "
            "explain that no order was prepared and ask the user for a tradable broker ticker."
        )
    if status == "resolved":
        return (
            "Use the resolvedTicker returned by the broker resolver and prepare the "
            "order again so the approved order matches the broker-native instrument."
        )
    return (
        "Resolve the instrument with broker_resolve_instrument, inspect "
        "resolution.status and candidates, then prepare the order again only with "
        "a confirmed broker-native ticker."
    )


def _format_instrument_resolution_failure_output(
    exc: BrokerInstrumentResolutionError,
    *,
    code: str,
    hint: str,
) -> str:
    resolution = exc.resolution
    query = str(getattr(resolution, "query", "") or "").strip() or "unknown"
    lines = [
        "No broker order was prepared or submitted.",
        (
            "The configured broker could not confirm a unique tradable "
            f"instrument for {query!r}."
        ),
        f"Resolution status: {_enum_value(getattr(resolution, 'status', 'unknown'))}.",
        f"Code: {code}.",
    ]
    resolved_ticker = getattr(resolution, "resolved_ticker", None)
    if resolved_ticker:
        lines.append(f"Broker resolver suggested: {resolved_ticker}.")
    candidates = list(getattr(resolution, "candidates", []) or [])
    if candidates:
        lines.append("Candidate broker-native tickers:")
        for candidate in candidates[:5]:
            parts = [_format_value(getattr(candidate, "ticker", None))]
            name = getattr(candidate, "name", None) or getattr(candidate, "short_name", None)
            currency = getattr(candidate, "currency", None)
            score = getattr(candidate, "score", None)
            reason = getattr(candidate, "match_reason", None)
            if name:
                parts.append(str(name))
            if currency:
                parts.append(str(currency))
            if score is not None:
                parts.append(f"score={score}")
            if reason:
                parts.append(f"match={reason}")
            lines.append(f"- {' | '.join(parts)}")
    else:
        lines.append("No candidate broker-native tickers were returned.")
    if getattr(resolution, "hint", None):
        lines.append(f"Broker hint: {resolution.hint}")
    lines.append(f"Next step: {hint}")
    return "\n".join(lines)


def _format_tool_error_output(
    message: str,
    *,
    code: str,
    hint: str | None = None,
    details: dict[str, Any] | None = None,
) -> str:
    lines = [str(message or "Tool execution failed.").strip()]
    if code:
        lines.append(f"Code: {code}.")
    resolution = details.get("resolution") if isinstance(details, dict) else None
    if isinstance(resolution, dict):
        query = resolution.get("query")
        status = resolution.get("status")
        if query or status:
            lines.append(
                "Instrument resolution: "
                f"query={_format_value(query)}, status={_format_value(status)}."
            )
        candidates = resolution.get("candidates")
        if isinstance(candidates, list) and candidates:
            rendered: list[str] = []
            for candidate in candidates[:5]:
                if not isinstance(candidate, dict):
                    continue
                parts = [_format_value(candidate.get("ticker"))]
                for key in ("name", "shortName", "currency", "score", "matchReason"):
                    value = candidate.get(key)
                    if value is not None:
                        parts.append(f"{key}={value}")
                rendered.append(" | ".join(parts))
            if rendered:
                lines.append("Candidate broker-native tickers: " + "; ".join(rendered) + ".")
    if hint:
        lines.append(f"Hint: {hint}")
    return "\n".join(line for line in lines if line)


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


def _broker_provider_failure_hint(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized == "trading212":
        return (
            "Check BROKER_PROVIDER=trading212, T212_ENVIRONMENT, the active Trading 212 key pair "
            "(T212_DEMO_API_KEY/T212_DEMO_API_SECRET or T212_LIVE_API_KEY/T212_LIVE_API_SECRET), "
            "legacy fallback vars T212_API_KEY/T212_API_SECRET if you still use them, API scopes "
            "for account/portfolio/orders/history, IP restrictions, and rate limits."
        )
    if normalized == "alpaca":
        return (
            "Check BROKER_PROVIDER=alpaca, ALPACA_ENVIRONMENT, the active Alpaca key pair "
            "(ALPACA_PAPER_API_KEY/ALPACA_PAPER_API_SECRET or ALPACA_LIVE_API_KEY/ALPACA_LIVE_API_SECRET), "
            "legacy fallback vars ALPACA_API_KEY/ALPACA_API_SECRET if you still use them, "
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


def _format_pending_orders_output(
    orders: list[BrokerOrder],
    *,
    runtime: BrokerToolRuntime,
) -> str:
    provider_name = _display_broker_name(runtime.broker_provider)
    lines = [f"Retrieved {len(orders)} pending {provider_name} orders."]
    for order in orders:
        public_ref = _register_order_public_ref(order, runtime=runtime)
        if public_ref is None:
            continue
        lines.append(
            f"- {public_ref}: "
            f"{_format_value(order.side)} {_format_value(order.ticker)}, "
            f"type={_format_value(order.type)}, "
            f"status={_format_value(order.status)}, "
            f"quantity={_format_value(order.quantity)}"
        )
    return "\n".join(lines)


def _format_instrument_snapshot_output(snapshot: Any, *, provider: str) -> str:
    provider_name = _display_broker_name(provider)
    instrument = getattr(snapshot, "instrument", None)
    resolution = getattr(snapshot, "resolution", None)
    lines = [
        (
            f"{provider_name} instrument snapshot for "
            f"{_format_value(getattr(snapshot, 'query', None))}."
        ),
        f"Resolution status: {_enum_value(getattr(snapshot, 'status', None)) or 'unknown'}.",
    ]
    if instrument is not None:
        lines.append(
            "Instrument: "
            f"ticker={_format_value(getattr(instrument, 'ticker', None))}, "
            f"name={_format_value(getattr(instrument, 'name', None))}, "
            f"currency={_format_value(getattr(instrument, 'currency', None))}, "
            f"isin={_format_value(getattr(instrument, 'isin', None))}."
        )
    else:
        lines.append("Instrument: no unique broker instrument snapshot was returned.")
    lines.append(
        "Tradability: "
        f"tradable={_format_value(getattr(snapshot, 'tradable', None))}, "
        f"orderable={_format_value(getattr(snapshot, 'orderable', None))}, "
        f"fractional={_format_value(getattr(snapshot, 'fractional', None))}, "
        f"shortable={_format_value(getattr(snapshot, 'shortable', None))}, "
        f"extended_hours={_format_value(getattr(snapshot, 'extended_hours', None))}."
    )
    lines.append(
        "Metadata: "
        f"asset_class={_format_value(getattr(snapshot, 'asset_class', None))}, "
        f"exchange={_format_value(getattr(snapshot, 'exchange', None))}, "
        f"broker_status={_format_value(getattr(snapshot, 'broker_status', None))}, "
        f"source={_format_value(getattr(snapshot, 'snapshot_source', None))}."
    )
    if resolution is not None and getattr(resolution, "candidates", None):
        candidates = []
        for candidate in resolution.candidates[:5]:
            candidates.append(
                f"{candidate.ticker}"
                f"({_format_value(candidate.currency)}, "
                f"score={_format_value(candidate.score)})"
            )
        if candidates:
            lines.append("Candidates: " + "; ".join(candidates) + ".")
    if getattr(snapshot, "hint", None):
        lines.append(f"Hint: {snapshot.hint}")
    return "\n".join(lines)


def _format_portfolio_snapshot_output(
    snapshot,
    *,
    provider: str,
    runtime: BrokerToolRuntime,
) -> str:
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
        for index, position in enumerate(snapshot.positions):
            instrument = position.instrument
            public_ref = _register_position_public_ref(
                position,
                index=index,
                runtime=runtime,
            )
            if public_ref is None:
                continue
            lines.append(
                f"- {public_ref}: "
                f"{_format_value(instrument.ticker if instrument else None)}, "
                f"quantity={_format_value(position.quantity)}, "
                f"available={_format_value(position.quantity_available_for_trading)}, "
                f"current_price={_format_money(position.current_price, instrument.currency if instrument else None)}"
            )
    else:
        lines.append(f"Positions: no open positions returned by {provider_name}.")
    if snapshot.pending_orders:
        lines.append(f"Pending orders: {len(snapshot.pending_orders)} active/pending order(s).")
        for order in snapshot.pending_orders:
            public_ref = _register_order_public_ref(order, runtime=runtime)
            if public_ref is None:
                continue
            lines.append(
                f"- {public_ref}: "
                f"{_format_value(order.side)} {_format_value(order.ticker)}, "
                f"type={_format_value(order.type)}, "
                f"status={_format_value(order.status)}, "
                f"quantity={_format_value(order.quantity)}"
            )
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
    lines = [
        f"Prepared {provider_name} order action.",
        "",
    ]
    if prepared.requested_notional_amount is not None:
        lines.extend(
            [
                "Sizing:",
                "- requested_notional: "
                f"{_format_money(prepared.requested_notional_amount, prepared.requested_notional_currency)}",
                f"- sizing_price: {_format_money(prepared.sizing_price, prepared.requested_notional_currency)}",
                f"- sizing_price_source: {_format_value(prepared.sizing_price_source)}",
                f"- estimated_quantity: {_format_value(prepared.quantity)}",
                "",
            ]
        )
    lines.extend(
        [
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
    return "\n".join(lines)


def _format_cancel_action_summary(
    order: BrokerOrder,
    *,
    provider: str,
    reason: str | None,
    runtime: BrokerToolRuntime | None = None,
) -> str:
    provider_name = _display_broker_name(provider)
    public_ref = (
        _register_order_public_ref(order, runtime=runtime)
        if runtime is not None
        else None
    )
    lines = [
        f"Prepared {provider_name} cancellation action.",
        "",
        "Target order:",
        f"- public_ref: {_format_value(public_ref)}",
        f"- broker_order_ref: {_format_value(order.id)}",
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
