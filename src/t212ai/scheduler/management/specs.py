"""Tool specifications and toolboxes for scheduler management."""

from __future__ import annotations

from t212ai.genai.models import ToolSpec
from t212ai.genai.tools.base import ToolBox, build_tool_index

from .constants import (
    COMPANY_EVENT_SCHEDULE_TYPES,
    COMPANY_EVENT_TYPES,
    INSTRUMENT_MONITOR_TRIGGER_TYPES,
    MARKET_SIGNAL_CAPTURE_SCHEDULE_TYPES,
    MIN_MARKET_SIGNAL_CAPTURE_POLL_SECONDS,
    TRADE_SETUP_ORDER_TYPES,
    TRADE_SETUP_SIDES,
)


SCHEDULER_CREATE_PROCESS_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "scheduler_create_process",
        "description": (
            "Create one validated scheduled process from an already-typed process "
            "spec for explicit user intent or a configured scheduler workflow. "
            "Scheduler v1 supports notify/proposal workflows and leaves broker "
            "execution outside the scheduled-process spec."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string", "default": ""},
                "kind": {
                    "type": "string",
                    "enum": [
                        "instrument_monitor",
                        "company_event_analyst",
                        "market_regime_monitor",
                        "trade_setup_monitor",
                        "market_signal_capture",
                        "watchlist_briefing",
                        "filing_or_insider_monitor",
                        "portfolio_attention_monitor",
                        "alpaca_news_monitor",
                    ],
                },
                "execution_mode": {
                    "type": "string",
                    "enum": ["deterministic", "llm_assisted", "llm_planned"],
                },
                "schedule": {
                    "type": "object",
                    "description": "Validated schedule spec object.",
                },
                "trigger": {
                    "type": "object",
                    "default": {},
                    "description": "Process-specific trigger configuration.",
                },
                "inputs": {
                    "type": "object",
                    "default": {},
                    "description": "Process-specific input payload.",
                },
                "llm_scope": {
                    "type": "object",
                    "default": {},
                    "description": "Optional bounded LLM scope for later LLM-assisted adapters.",
                },
                "action": {
                    "type": "object",
                    "default": {},
                    "description": "Validated action policy for notify/proposal workflows.",
                },
                "notification": {
                    "type": "object",
                    "default": {},
                    "description": "Notification preference/configuration for the process.",
                },
                "lifecycle": {
                    "type": "object",
                    "description": "Validated lifecycle spec object.",
                },
                "safety": {
                    "type": "object",
                    "default": {},
                    "description": "Safety policy for scheduler v1 broker-action status.",
                },
            },
            "required": [
                "title",
                "description",
                "kind",
                "execution_mode",
                "schedule",
                "trigger",
                "inputs",
                "llm_scope",
                "action",
                "notification",
                "lifecycle",
                "safety",
            ],
            "additionalProperties": False,
        },
    },
}

SCHEDULER_LIST_PROCESSES_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "scheduler_list_processes",
        "description": (
            "List scheduled processes with optional status/kind filters. Prefer broad "
            "listing before pausing or archiving when the exact process id is unknown."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "statuses": {
                    "type": ["array", "null"],
                    "items": {
                        "type": "string",
                        "enum": ["active", "paused", "completed", "expired", "archived", "failed"],
                    },
                    "default": None,
                },
                "kinds": {
                    "type": ["array", "null"],
                    "items": {
                        "type": "string",
                        "enum": [
                            "instrument_monitor",
                            "company_event_analyst",
                            "market_regime_monitor",
                            "trade_setup_monitor",
                            "market_signal_capture",
                            "watchlist_briefing",
                            "filing_or_insider_monitor",
                            "portfolio_attention_monitor",
                            "alpaca_news_monitor",
                        ],
                    },
                    "default": None,
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
            },
            "required": ["statuses", "kinds", "limit"],
            "additionalProperties": False,
        },
    },
}

SCHEDULER_INSTRUMENT_MONITOR_CREATE_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "scheduler_instrument_monitor_create",
        "description": (
            "Create one executable deterministic instrument monitor from natural "
            "language scheduling intent. This tool creates kind=instrument_monitor, "
            "executionMode=deterministic, polling schedules, and safety.brokerActionsAllowed=false. "
            "Use it for alerts such as price thresholds, percent-change thresholds, "
            "period-low breakdowns, or period-high breakouts. Ask a concise "
            "clarification question instead of calling this tool when symbol, trigger "
            "direction, or required threshold value is missing or ambiguous. This tool "
            "never configures broker or order actions."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Optional user-facing monitor title.",
                },
                "description": {
                    "type": "string",
                    "default": "",
                    "description": "Optional concise context for the monitor.",
                },
                "symbol": {
                    "type": "string",
                    "description": "Market-data symbol to monitor, such as TSLA or AAPL.",
                },
                "trigger_type": {
                    "type": "string",
                    "enum": sorted(INSTRUMENT_MONITOR_TRIGGER_TYPES),
                    "description": (
                        "Supported trigger type. Price and percent-change triggers "
                        "require value. Period high/low triggers use lookback fields."
                    ),
                },
                "value": {
                    "type": ["number", "null"],
                    "default": None,
                    "description": (
                        "Threshold value for price or percent-change triggers. "
                        "Percent changes use signed percentage points, such as -5."
                    ),
                },
                "lookback_period": {
                    "type": "string",
                    "default": "1mo",
                    "description": "Market-data lookback period for period high/low triggers.",
                },
                "lookback_interval": {
                    "type": "string",
                    "default": "1d",
                    "description": "Market-data lookback interval for period high/low triggers.",
                },
                "auto_adjust": {
                    "type": "boolean",
                    "default": False,
                    "description": "Whether to ask the market-data provider for adjusted history.",
                },
                "poll_every_seconds": {
                    "type": ["integer", "null"],
                    "minimum": 1,
                    "default": None,
                    "description": (
                        "Polling interval in seconds. Defaults to the configured "
                        "scheduler default, normally 300."
                    ),
                },
                "timezone": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": (
                        "IANA timezone used only for default end-of-day expiry. "
                        "Defaults to configured scheduler timezone."
                    ),
                },
                "expires_at": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": (
                        "Optional ISO-8601 expiry. If omitted, defaults to the end "
                        "of the current day in the selected timezone."
                    ),
                },
                "notification_enabled": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether a matching trigger should notify the user.",
                },
                "broker_actions_allowed": {
                    "type": "boolean",
                    "default": False,
                    "description": "Scheduler v1 broker-action flag; use false for notify-only monitors.",
                },
            },
            "required": [
                "title",
                "description",
                "symbol",
                "trigger_type",
                "value",
                "lookback_period",
                "lookback_interval",
                "auto_adjust",
                "poll_every_seconds",
                "timezone",
                "expires_at",
                "notification_enabled",
                "broker_actions_allowed",
            ],
            "additionalProperties": False,
        },
    },
}

SCHEDULER_COMPANY_EVENT_ANALYST_CREATE_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "scheduler_company_event_analyst_create",
        "description": (
            "Create one safe LLM-assisted company-event analysis process. This tool "
            "creates kind=company_event_analyst, executionMode=llm_assisted, "
            "notify-only action, and safety.brokerActionsAllowed=false. Use it for "
            "scheduled earnings, guidance, filing, major-news, or company-event "
            "analysis. Ask a concise clarification question instead of calling this "
            "tool when the symbol or schedule is missing or ambiguous. It never "
            "configures broker/order actions."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Optional user-facing process title.",
                },
                "description": {
                    "type": "string",
                    "default": "",
                    "description": "Optional concise process description.",
                },
                "symbol": {
                    "type": "string",
                    "description": "Company or ETF symbol to analyze, such as MSFT.",
                },
                "event_type": {
                    "type": "string",
                    "enum": sorted(COMPANY_EVENT_TYPES),
                    "default": "company_event",
                    "description": "Company-event category to analyze.",
                },
                "schedule_type": {
                    "type": "string",
                    "enum": sorted(COMPANY_EVENT_SCHEDULE_TYPES),
                    "description": "one_shot requires run_at; recurring requires frequency/time/timezone.",
                },
                "run_at": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "ISO-8601 datetime for one_shot schedules.",
                },
                "frequency": {
                    "type": ["string", "null"],
                    "enum": ["daily", "weekdays", "weekly", None],
                    "default": None,
                    "description": "Recurring frequency.",
                },
                "time": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Recurring local HH:MM time.",
                },
                "timezone": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "IANA timezone. Defaults to configured scheduler timezone.",
                },
                "days": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                    "description": "Weekly day names for weekly recurring schedules.",
                },
                "include_market_analyst": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Set true only when the user asks for broader market impact, "
                        "reaction, or context."
                    ),
                },
                "task_guidelines": {
                    "type": "string",
                    "default": "",
                    "description": "Optional bounded LLM guidance for the analysis.",
                },
                "disclosure_since_days": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 30,
                    "description": "SEC/disclosure lookback window in days.",
                },
                "search_time_range": {
                    "type": "string",
                    "default": "week",
                    "description": "Search time filter such as day, week, month, or year.",
                },
                "market_period": {
                    "type": "string",
                    "default": "1mo",
                    "description": "Market-data context period.",
                },
                "notification_enabled": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether completed analysis should notify the user.",
                },
                "broker_actions_allowed": {
                    "type": "boolean",
                    "default": False,
                    "description": "Scheduler v1 broker-action flag; use false for notify-only analysis.",
                },
            },
            "required": [
                "title",
                "description",
                "symbol",
                "event_type",
                "schedule_type",
                "run_at",
                "frequency",
                "time",
                "timezone",
                "days",
                "include_market_analyst",
                "task_guidelines",
                "disclosure_since_days",
                "search_time_range",
                "market_period",
                "notification_enabled",
                "broker_actions_allowed",
            ],
            "additionalProperties": False,
        },
    },
}

SCHEDULER_MARKET_REGIME_MONITOR_CREATE_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "scheduler_market_regime_monitor_create",
        "description": (
            "Create one safe LLM-assisted market-regime stress monitor. This tool "
            "creates kind=market_regime_monitor, executionMode=llm_assisted, "
            "polling schedule, notify-only action, and safety.brokerActionsAllowed=false. "
            "Use it for broad market stress/crash monitoring. If the user says market, "
            "S&P, Nasdaq, Dow, Russell, or small caps, map to the configured ETF proxy. "
            "If the request is vague, apply percent_change_below=-3 and "
            "drawdown_from_high_pct=5, and state those defaults. Ask a concise "
            "clarification question when the target market/proxy is ambiguous."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Optional user-facing monitor title.",
                },
                "description": {
                    "type": "string",
                    "default": "",
                    "description": "Optional concise context for the monitor.",
                },
                "market_label": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": (
                        "Broad market label such as market, S&P 500, Nasdaq, Dow, "
                        "Russell, or small caps."
                    ),
                },
                "proxy_symbol": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Explicit ETF/index proxy symbol. Used when market_label is absent.",
                },
                "percent_change_below": {
                    "type": ["number", "null"],
                    "default": None,
                    "description": (
                        "Signed percentage threshold, such as -3. If both thresholds "
                        "are omitted, defaults to -3."
                    ),
                },
                "drawdown_from_high_pct": {
                    "type": ["number", "null"],
                    "default": None,
                    "description": (
                        "Drawdown threshold from lookback high, such as 5. If both "
                        "thresholds are omitted, defaults to 5."
                    ),
                },
                "lookback_period": {
                    "type": "string",
                    "default": "1mo",
                    "description": "Market-data lookback period for drawdown evaluation.",
                },
                "lookback_interval": {
                    "type": "string",
                    "default": "1d",
                    "description": "Market-data lookback interval for drawdown evaluation.",
                },
                "auto_adjust": {
                    "type": "boolean",
                    "default": False,
                    "description": "Whether to ask the market-data provider for adjusted history.",
                },
                "poll_every_seconds": {
                    "type": ["integer", "null"],
                    "minimum": 1,
                    "default": None,
                    "description": "Polling interval in seconds. Defaults to scheduler default.",
                },
                "timezone": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "IANA timezone for default end-of-day expiry.",
                },
                "expires_at": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": (
                        "Optional ISO-8601 expiry. If omitted, defaults to end of "
                        "current day in the selected timezone."
                    ),
                },
                "search_time_range": {
                    "type": "string",
                    "default": "day",
                    "description": "Search time filter used after trigger match.",
                },
                "task_guidelines": {
                    "type": "string",
                    "default": "",
                    "description": "Optional bounded LLM guidance for matched stress explanation.",
                },
                "notification_enabled": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether a matching stress trigger should notify the user.",
                },
                "broker_actions_allowed": {
                    "type": "boolean",
                    "default": False,
                    "description": "Scheduler v1 broker-action flag; use false for notify-only monitors.",
                },
            },
            "required": [
                "title",
                "description",
                "market_label",
                "proxy_symbol",
                "percent_change_below",
                "drawdown_from_high_pct",
                "lookback_period",
                "lookback_interval",
                "auto_adjust",
                "poll_every_seconds",
                "timezone",
                "expires_at",
                "search_time_range",
                "task_guidelines",
                "notification_enabled",
                "broker_actions_allowed",
            ],
            "additionalProperties": False,
        },
    },
}

SCHEDULER_MARKET_SIGNAL_CAPTURE_CREATE_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "scheduler_market_signal_capture_create",
        "description": (
            "Create one safe LLM-assisted market-signal capture process. This tool "
            "creates kind=market_signal_capture, executionMode=llm_assisted, "
            "recurring or polling schedules, notify-only action, and "
            "safety.brokerActionsAllowed=false. Use it to scan a bounded topic, "
            "symbol list, sector list, or tag list and save only durable advisory "
            "market signals into memory. Ask a concise clarification question instead "
            "of calling this tool when the scan scope or schedule is missing or "
            "ambiguous. Market signals are advisory context, not fresh market data or "
            "broker-authoritative state."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Optional user-facing process title.",
                },
                "description": {
                    "type": "string",
                    "default": "",
                    "description": "Optional concise process description.",
                },
                "query": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Broad research query or theme to scan.",
                },
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                    "description": "Optional public symbols to scan.",
                },
                "sectors": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                    "description": "Optional sectors or market themes.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                    "description": "Optional flexible memory tags.",
                },
                "schedule_type": {
                    "type": "string",
                    "enum": sorted(MARKET_SIGNAL_CAPTURE_SCHEDULE_TYPES),
                    "description": "polling requires poll_every_seconds; recurring requires frequency and time.",
                },
                "poll_every_seconds": {
                    "type": ["integer", "null"],
                    "minimum": MIN_MARKET_SIGNAL_CAPTURE_POLL_SECONDS,
                    "default": None,
                    "description": (
                        "Polling interval in seconds. Defaults to 3600 and must be "
                        "at least 900 for this LLM-assisted process."
                    ),
                },
                "frequency": {
                    "type": ["string", "null"],
                    "enum": ["daily", "weekdays", "weekly", None],
                    "default": None,
                    "description": "Recurring frequency.",
                },
                "time": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Recurring local HH:MM time.",
                },
                "timezone": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "IANA timezone. Defaults to configured scheduler timezone.",
                },
                "days": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                    "description": "Weekly day names for weekly recurring schedules.",
                },
                "task_guidelines": {
                    "type": "string",
                    "default": "",
                    "description": "Optional bounded LLM guidance for the capture run.",
                },
                "max_signals": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 3,
                    "default": 3,
                    "description": "Maximum market signals to create per run.",
                },
                "search_time_range": {
                    "type": "string",
                    "default": "day",
                    "description": "Search time filter such as day, week, month, or year.",
                },
                "community_time_range": {
                    "type": "string",
                    "default": "week",
                    "description": "Community research time filter when configured.",
                },
                "market_period": {
                    "type": "string",
                    "default": "1mo",
                    "description": "Market-data context period when symbols are provided.",
                },
                "disclosure_since_days": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 30,
                    "description": "SEC/disclosure lookback window in days.",
                },
                "notification_enabled": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether newly saved signals should notify the user.",
                },
                "broker_actions_allowed": {
                    "type": "boolean",
                    "default": False,
                    "description": "Scheduler v1 broker-action flag; use false for notify-only capture.",
                },
            },
            "required": [
                "title",
                "description",
                "query",
                "symbols",
                "sectors",
                "tags",
                "schedule_type",
                "poll_every_seconds",
                "frequency",
                "time",
                "timezone",
                "days",
                "task_guidelines",
                "max_signals",
                "search_time_range",
                "community_time_range",
                "market_period",
                "disclosure_since_days",
                "notification_enabled",
                "broker_actions_allowed",
            ],
            "additionalProperties": False,
        },
    },
}

SCHEDULER_ALPACA_NEWS_MONITOR_CREATE_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "scheduler_alpaca_news_monitor_create",
        "description": (
            "Create one bounded Alpaca real-time news stream monitor. This creates "
            "kind=alpaca_news_monitor, executionMode=llm_assisted, manual schedule, "
            "and a stream worker that invokes the News Ingestion Judge for each "
            "received news event in scope. Provide either end_at or duration_minutes. "
            "If the user does not specify ticker symbols, do not ask for clarification; "
            "set symbols=['*'] to monitor all Alpaca news. Broker order proposals may "
            "be prepared by downstream agents, but any execution still requires "
            "Telegram approval buttons."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Optional user-facing monitor title.",
                },
                "description": {
                    "type": "string",
                    "default": "",
                    "description": "Optional concise monitor description.",
                },
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": ["*"],
                    "description": (
                        "Ticker symbols to subscribe/filter for the stream. "
                        "If the user omitted ticker symbols, use ['*'] to cover all news."
                    ),
                },
                "start_at": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": (
                        "Optional ISO-8601 start datetime. If omitted, monitoring "
                        "starts as soon as the supervisor sees the process."
                    ),
                },
                "end_at": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Optional ISO-8601 end datetime for the stream window.",
                },
                "duration_minutes": {
                    "type": ["integer", "null"],
                    "minimum": 1,
                    "default": None,
                    "description": (
                        "Alternative bounded duration in minutes. Required when "
                        "end_at is omitted."
                    ),
                },
                "timezone": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": (
                        "IANA timezone for naive start/end datetimes. For relative windows "
                        "such as next hour, pass null and duration_minutes; the tool uses the "
                        "configured scheduler timezone. Do not pass abbreviations like CET or CEST."
                    ),
                },
                "task_guidelines": {
                    "type": "string",
                    "default": "",
                    "description": "Optional user guidance for judging streamed news.",
                },
                "order_proposals_enabled": {
                    "type": "boolean",
                    "default": True,
                    "description": (
                        "Whether the News Judge may ask the order agent to prepare "
                        "order proposals when market relevance supports it."
                    ),
                },
                "max_events_per_minute": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 120,
                    "default": 30,
                    "description": "Per-process cap on news events sent to the LLM judge.",
                },
                "notification_enabled": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether user-visible judge results should notify Telegram.",
                },
                "broker_actions_allowed": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Scheduler safety flag. Use false; execution remains approval-gated."
                    ),
                },
            },
            "required": [
                "title",
                "description",
                "symbols",
                "start_at",
                "end_at",
                "duration_minutes",
                "timezone",
                "task_guidelines",
                "order_proposals_enabled",
                "max_events_per_minute",
                "notification_enabled",
                "broker_actions_allowed",
            ],
            "additionalProperties": False,
        },
    },
}

SCHEDULER_TRADE_SETUP_MONITOR_CREATE_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "scheduler_trade_setup_monitor_create",
        "description": (
            "Create one guarded LLM-assisted trade setup monitor. This tool creates "
            "kind=trade_setup_monitor, executionMode=llm_assisted, polling "
            "schedule, notify/proposal action, and safety.brokerActionsAllowed=false. "
            "Use it when the user explicitly asks to monitor a setup and, if "
            "proposal creation is enabled, explicitly provides or accepts risk caps. "
            "The scheduler never submits orders; any created pending action still "
            "requires Telegram button approval. Ask a concise clarification question "
            "when trigger, proposal permission, risk caps, or approval chat target is missing."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": ["string", "null"], "default": None},
                "description": {"type": "string", "default": ""},
                "symbol": {
                    "type": "string",
                    "description": "Market-data symbol and default allowed order symbol.",
                },
                "trigger_type": {
                    "type": "string",
                    "enum": sorted(INSTRUMENT_MONITOR_TRIGGER_TYPES),
                },
                "value": {
                    "type": ["number", "null"],
                    "default": None,
                    "description": "Threshold value for price or percent-change triggers.",
                },
                "lookback_period": {"type": "string", "default": "1mo"},
                "lookback_interval": {"type": "string", "default": "1d"},
                "auto_adjust": {"type": "boolean", "default": False},
                "proposal_creation_allowed": {
                    "type": "boolean",
                    "default": False,
                    "description": "Must be true to create pending order proposals.",
                },
                "allowed_symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                    "description": "Allowed order tickers. Defaults to symbol when omitted.",
                },
                "allowed_sides": {
                    "type": "array",
                    "items": {"type": "string", "enum": sorted(TRADE_SETUP_SIDES)},
                    "default": [],
                },
                "allowed_order_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": sorted(TRADE_SETUP_ORDER_TYPES)},
                    "default": [],
                },
                "max_notional_amount": {
                    "type": ["number", "null"],
                    "default": None,
                    "description": "Maximum notional order size when notional sizing is allowed.",
                },
                "notional_currency": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Currency required with max_notional_amount.",
                },
                "max_quantity": {
                    "type": ["number", "null"],
                    "default": None,
                    "description": "Maximum share quantity when quantity sizing is allowed.",
                },
                "allow_extended_hours": {"type": "boolean", "default": False},
                "approval_chat_id": {
                    "type": ["integer", "null"],
                    "default": None,
                    "description": "Telegram chat id for approval buttons. Defaults to invoking chat when available.",
                },
                "approval_user_id": {
                    "type": ["integer", "null"],
                    "default": None,
                    "description": "Optional Telegram user id bound to the pending action.",
                },
                "poll_every_seconds": {
                    "type": ["integer", "null"],
                    "minimum": 1,
                    "default": None,
                },
                "timezone": {"type": ["string", "null"], "default": None},
                "expires_at": {"type": ["string", "null"], "default": None},
                "task_guidelines": {"type": "string", "default": ""},
                "notification_enabled": {"type": "boolean", "default": True},
                "broker_actions_allowed": {
                    "type": "boolean",
                    "default": False,
                    "description": "Scheduler v1 broker-action flag; use false for notify/proposal monitors.",
                },
            },
            "required": [
                "title",
                "description",
                "symbol",
                "trigger_type",
                "value",
                "lookback_period",
                "lookback_interval",
                "auto_adjust",
                "proposal_creation_allowed",
                "allowed_symbols",
                "allowed_sides",
                "allowed_order_types",
                "max_notional_amount",
                "notional_currency",
                "max_quantity",
                "allow_extended_hours",
                "approval_chat_id",
                "approval_user_id",
                "poll_every_seconds",
                "timezone",
                "expires_at",
                "task_guidelines",
                "notification_enabled",
                "broker_actions_allowed",
            ],
            "additionalProperties": False,
        },
    },
}


def _process_id_tool(name: str, description: str) -> ToolSpec:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "process_id": {
                        "type": "string",
                        "description": "Exact scheduled process id, such as sched_...",
                    }
                },
                "required": ["process_id"],
                "additionalProperties": False,
            },
        },
    }


SCHEDULER_PAUSE_PROCESS_TOOL = _process_id_tool(
    "scheduler_pause_process",
    "Pause one explicit scheduled process id. This keeps the spec and audit history.",
)
SCHEDULER_RESUME_PROCESS_TOOL = _process_id_tool(
    "scheduler_resume_process",
    "Resume one explicit paused scheduled process id and recompute its next run.",
)
SCHEDULER_ARCHIVE_PROCESS_TOOL = _process_id_tool(
    "scheduler_archive_process",
    "Archive one explicit scheduled process id. Archive never deletes process records.",
)

SCHEDULER_MANAGEMENT_TOOLS: list[ToolSpec] = [
    SCHEDULER_CREATE_PROCESS_TOOL,
    SCHEDULER_LIST_PROCESSES_TOOL,
    SCHEDULER_PAUSE_PROCESS_TOOL,
    SCHEDULER_RESUME_PROCESS_TOOL,
    SCHEDULER_ARCHIVE_PROCESS_TOOL,
]
SCHEDULER_AGENT_TOOLS: list[ToolSpec] = [
    SCHEDULER_INSTRUMENT_MONITOR_CREATE_TOOL,
    SCHEDULER_COMPANY_EVENT_ANALYST_CREATE_TOOL,
    SCHEDULER_MARKET_REGIME_MONITOR_CREATE_TOOL,
    SCHEDULER_MARKET_SIGNAL_CAPTURE_CREATE_TOOL,
    SCHEDULER_ALPACA_NEWS_MONITOR_CREATE_TOOL,
    SCHEDULER_TRADE_SETUP_MONITOR_CREATE_TOOL,
    SCHEDULER_LIST_PROCESSES_TOOL,
    SCHEDULER_PAUSE_PROCESS_TOOL,
    SCHEDULER_RESUME_PROCESS_TOOL,
    SCHEDULER_ARCHIVE_PROCESS_TOOL,
]

SCHEDULER_MANAGEMENT_TOOLBOX = ToolBox(
    name="scheduler_management",
    tools=SCHEDULER_MANAGEMENT_TOOLS,
    tools_by_name=build_tool_index(SCHEDULER_MANAGEMENT_TOOLS),
)
SCHEDULER_AGENT_TOOLBOX = ToolBox(
    name="scheduler_agent",
    tools=SCHEDULER_AGENT_TOOLS,
    tools_by_name=build_tool_index(SCHEDULER_AGENT_TOOLS),
)
