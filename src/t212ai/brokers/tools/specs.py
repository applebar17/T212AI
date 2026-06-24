"""OpenAI tool specifications for generic broker tools."""

from __future__ import annotations

from typing import Any

from t212ai.genai.models import ToolSpec


BROKER_GET_PORTFOLIO_SNAPSHOT_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "broker_get_portfolio_snapshot",
        "description": (
            "Read-only broker portfolio snapshot. Returns account summary, "
            "open positions with broker/order-management identifiers where available, "
            "and pending orders from the configured broker. Use top_positions_limit only "
            "to limit the human-readable position summary to the largest N open positions "
            "by current value; it does not limit the broker API fetch or the structured snapshot data."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "top_positions_limit": {
                    "type": ["integer", "null"],
                    "minimum": 1,
                    "default": None,
                    "description": (
                        "Optional display limit for summarizing open positions. Pass null to "
                        "show all open positions. Pass a positive integer N to summarize only "
                        "the top N open positions by current value/portfolio weight. This is "
                        "a presentation limit, not an API fetch limit; identifiers are still "
                        "returned for open positions in the structured snapshot data."
                    ),
                },
            },
            "required": ["top_positions_limit"],
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
