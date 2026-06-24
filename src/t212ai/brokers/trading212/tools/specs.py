"""OpenAI tool specifications for Trading 212 tools."""

from __future__ import annotations

from typing import Any

from t212ai.genai.models import ToolSpec

T212_GET_PORTFOLIO_SNAPSHOT_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "t212_get_portfolio_snapshot",
        "description": (
            "Read-only Trading 212 portfolio snapshot. Returns account summary, "
            "open positions with order-management identifiers where available, "
            "and pending orders. Use top_positions_limit only to limit the "
            "position summary to the largest N open positions by current value."
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
                        "the top N open positions by current value/portfolio weight. Identifiers are "
                        "returned for open positions in the structured snapshot data."
                    ),
                },
            },
            "required": ["top_positions_limit"],
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
