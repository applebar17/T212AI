"""Deterministic scheduler management helpers.

These functions are intentionally narrow and typed so they can later be exposed
behind a bounded scheduler delegate without giving the main orchestrator direct
access to arbitrary scheduler internals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from functools import partial
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from t212ai.genai.models import ToolError, ToolResult, ToolSpec
from t212ai.genai.tools.base import ToolBox, build_tool_index
from t212ai.genai.tracing import set_trace_metadata, traceable

from .models import ScheduledProcess
from .service import ScheduledProcessService


@dataclass(slots=True)
class SchedulerManagementRuntime:
    service: ScheduledProcessService | None = None
    default_timezone: str = "UTC"
    default_poll_every_seconds: int = 300
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


INSTRUMENT_MONITOR_TRIGGER_TYPES = frozenset(
    {
        "below_price",
        "above_price",
        "percent_change_below",
        "percent_change_above",
        "period_low_breakdown",
        "period_high_breakout",
    }
)
COMPANY_EVENT_TYPES = frozenset(
    {
        "earnings_report",
        "guidance_update",
        "filing",
        "major_news",
        "company_event",
    }
)
COMPANY_EVENT_SCHEDULE_TYPES = frozenset({"one_shot", "recurring"})
COMPANY_EVENT_FREQUENCIES = frozenset({"daily", "weekdays", "weekly"})
THRESHOLD_TRIGGER_TYPES = frozenset(
    {
        "below_price",
        "above_price",
        "percent_change_below",
        "percent_change_above",
    }
)


SCHEDULER_CREATE_PROCESS_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "scheduler_create_process",
        "description": (
            "Create one validated scheduled process from an already-typed process "
            "spec. Use only with explicit user intent or a configured scheduler "
            "workflow. Direct broker execution is rejected by the scheduler service."
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
                    "description": "Validated action policy. Broker execution fields are rejected.",
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
                    "description": "Safety policy. brokerActionsAllowed must remain false in v1.",
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
            "language scheduling intent. This tool creates only kind=instrument_monitor, "
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
                    "description": "Must be false. Broker/order execution is not supported.",
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
            "creates only kind=company_event_analyst, executionMode=llm_assisted, "
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
                    "description": "Must be false. Broker/order execution is not supported.",
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


def build_scheduler_management_tool_mapping(
    service: ScheduledProcessService | None,
) -> dict[str, Callable[..., ToolResult]]:
    runtime = SchedulerManagementRuntime(service=service)
    return {
        "scheduler_create_process": partial(scheduler_create_process, runtime=runtime),
        "scheduler_list_processes": partial(scheduler_list_processes, runtime=runtime),
        "scheduler_pause_process": partial(scheduler_pause_process, runtime=runtime),
        "scheduler_resume_process": partial(scheduler_resume_process, runtime=runtime),
        "scheduler_archive_process": partial(scheduler_archive_process, runtime=runtime),
    }


def build_scheduler_agent_tool_mapping(
    service: ScheduledProcessService | None,
    *,
    default_timezone: str = "UTC",
    default_poll_every_seconds: int = 300,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Callable[..., ToolResult]]:
    runtime = SchedulerManagementRuntime(
        service=service,
        default_timezone=default_timezone,
        default_poll_every_seconds=default_poll_every_seconds,
        clock=clock or (lambda: datetime.now(timezone.utc)),
    )
    return {
        "scheduler_instrument_monitor_create": partial(
            scheduler_instrument_monitor_create,
            runtime=runtime,
        ),
        "scheduler_company_event_analyst_create": partial(
            scheduler_company_event_analyst_create,
            runtime=runtime,
        ),
        "scheduler_list_processes": partial(scheduler_list_processes, runtime=runtime),
        "scheduler_pause_process": partial(scheduler_pause_process, runtime=runtime),
        "scheduler_resume_process": partial(scheduler_resume_process, runtime=runtime),
        "scheduler_archive_process": partial(scheduler_archive_process, runtime=runtime),
    }


@traceable(name="scheduler_create_process", run_type="tool")
def scheduler_create_process(
    *,
    title: str,
    description: str,
    kind: str,
    execution_mode: str,
    schedule: dict[str, Any],
    trigger: dict[str, Any],
    inputs: dict[str, Any],
    llm_scope: dict[str, Any],
    action: dict[str, Any],
    notification: dict[str, Any],
    lifecycle: dict[str, Any],
    safety: dict[str, Any],
    runtime: SchedulerManagementRuntime,
) -> ToolResult:
    set_trace_metadata(provider="scheduler", tool_name="scheduler_create_process")
    if runtime.service is None:
        return _missing_service()
    try:
        process = runtime.service.create_process(
            title=title,
            description=description,
            kind=kind,
            execution_mode=execution_mode,
            schedule=schedule,
            trigger=trigger,
            inputs=inputs,
            llm_scope=llm_scope,
            action=action,
            notification=notification,
            lifecycle=lifecycle,
            safety=safety,
        )
    except Exception as exc:
        return _tool_exception(exc, operation="create_process")
    return ToolResult(
        status="ok",
        output=(
            f"Created scheduled process {process.process_id}: {process.title}. "
            f"status={process.status.value} nextRunAt={process.next_run_at}."
        ),
        data={"process": _process_payload(process)},
    )


@traceable(name="scheduler_instrument_monitor_create", run_type="tool")
def scheduler_instrument_monitor_create(
    *,
    title: str | None,
    description: str,
    symbol: str,
    trigger_type: str,
    value: int | float | None,
    lookback_period: str,
    lookback_interval: str,
    auto_adjust: bool,
    poll_every_seconds: int | None,
    timezone: str | None,
    expires_at: str | None,
    notification_enabled: bool,
    broker_actions_allowed: bool,
    runtime: SchedulerManagementRuntime,
) -> ToolResult:
    set_trace_metadata(provider="scheduler", tool_name="scheduler_instrument_monitor_create")
    if runtime.service is None:
        return _missing_service()
    try:
        process = _create_instrument_monitor(
            title=title,
            description=description,
            symbol=symbol,
            trigger_type=trigger_type,
            value=value,
            lookback_period=lookback_period,
            lookback_interval=lookback_interval,
            auto_adjust=auto_adjust,
            poll_every_seconds=poll_every_seconds,
            timezone_name=timezone,
            expires_at=expires_at,
            notification_enabled=notification_enabled,
            broker_actions_allowed=broker_actions_allowed,
            runtime=runtime,
        )
    except Exception as exc:
        return _instrument_monitor_exception(exc)
    return ToolResult(
        status="ok",
        output=(
            f"Created instrument monitor {process.process_id}: {process.title}. "
            f"Schedule: polling every {process.schedule.poll_every_seconds} seconds. "
            f"Lifecycle: {process.lifecycle.completion_policy.value}, "
            f"expiresAt={process.lifecycle.expires_at}. "
            "No broker action was configured."
        ),
        data={"process": _process_payload(process)},
    )


@traceable(name="scheduler_company_event_analyst_create", run_type="tool")
def scheduler_company_event_analyst_create(
    *,
    title: str | None,
    description: str,
    symbol: str,
    event_type: str,
    schedule_type: str,
    run_at: str | None,
    frequency: str | None,
    time: str | None,
    timezone: str | None,
    days: list[str],
    include_market_analyst: bool,
    task_guidelines: str,
    disclosure_since_days: int,
    search_time_range: str,
    market_period: str,
    notification_enabled: bool,
    broker_actions_allowed: bool,
    runtime: SchedulerManagementRuntime,
) -> ToolResult:
    set_trace_metadata(
        provider="scheduler",
        tool_name="scheduler_company_event_analyst_create",
    )
    if runtime.service is None:
        return _missing_service()
    try:
        process = _create_company_event_analyst(
            title=title,
            description=description,
            symbol=symbol,
            event_type=event_type,
            schedule_type=schedule_type,
            run_at=run_at,
            frequency=frequency,
            time_value=time,
            timezone_name=timezone,
            days=days,
            include_market_analyst=include_market_analyst,
            task_guidelines=task_guidelines,
            disclosure_since_days=disclosure_since_days,
            search_time_range=search_time_range,
            market_period=market_period,
            notification_enabled=notification_enabled,
            broker_actions_allowed=broker_actions_allowed,
            runtime=runtime,
        )
    except Exception as exc:
        return _company_event_exception(exc)
    schedule_summary = (
        f"one-shot at {process.schedule.run_at}"
        if process.schedule.type.value == "one_shot"
        else (
            f"recurring {process.schedule.frequency} at {process.schedule.time} "
            f"{process.schedule.timezone}"
        )
    )
    return ToolResult(
        status="ok",
        output=(
            f"Created company-event analyst process {process.process_id}: "
            f"{process.title}. Schedule: {schedule_summary}. Lifecycle: "
            f"{process.lifecycle.completion_policy.value}. No broker action was configured."
        ),
        data={"process": _process_payload(process)},
    )


@traceable(name="scheduler_list_processes", run_type="tool")
def scheduler_list_processes(
    *,
    statuses: list[str] | None,
    kinds: list[str] | None,
    limit: int,
    runtime: SchedulerManagementRuntime,
) -> ToolResult:
    set_trace_metadata(provider="scheduler", tool_name="scheduler_list_processes")
    if runtime.service is None:
        return _missing_service()
    try:
        processes = runtime.service.list_processes(
            statuses=statuses,
            kinds=kinds,
            limit=limit,
        )
    except Exception as exc:
        return _tool_exception(exc, operation="list_processes")
    return ToolResult(
        status="ok",
        output=_list_output(processes),
        data={"count": len(processes), "processes": [_process_payload(item) for item in processes]},
    )


@traceable(name="scheduler_pause_process", run_type="tool")
def scheduler_pause_process(
    *,
    process_id: str,
    runtime: SchedulerManagementRuntime,
) -> ToolResult:
    return _lifecycle_tool(
        process_id,
        runtime=runtime,
        operation="pause_process",
        verb="Paused",
        action=lambda service, resolved_id: service.pause_process(resolved_id),
    )


@traceable(name="scheduler_resume_process", run_type="tool")
def scheduler_resume_process(
    *,
    process_id: str,
    runtime: SchedulerManagementRuntime,
) -> ToolResult:
    return _lifecycle_tool(
        process_id,
        runtime=runtime,
        operation="resume_process",
        verb="Resumed",
        action=lambda service, resolved_id: service.resume_process(resolved_id),
    )


@traceable(name="scheduler_archive_process", run_type="tool")
def scheduler_archive_process(
    *,
    process_id: str,
    runtime: SchedulerManagementRuntime,
) -> ToolResult:
    return _lifecycle_tool(
        process_id,
        runtime=runtime,
        operation="archive_process",
        verb="Archived",
        action=lambda service, resolved_id: service.archive_process(resolved_id),
    )


def _lifecycle_tool(
    process_id: str,
    *,
    runtime: SchedulerManagementRuntime,
    operation: str,
    verb: str,
    action: Callable[[ScheduledProcessService, str], ScheduledProcess],
) -> ToolResult:
    set_trace_metadata(provider="scheduler", tool_name=f"scheduler_{operation}")
    if runtime.service is None:
        return _missing_service()
    try:
        process = action(runtime.service, str(process_id).strip())
    except Exception as exc:
        return _tool_exception(exc, operation=operation)
    return ToolResult(
        status="ok",
        output=f"{verb} scheduled process {process.process_id}: {process.title}.",
        data={"process": _process_payload(process)},
    )


def _create_instrument_monitor(
    *,
    title: str | None,
    description: str,
    symbol: str,
    trigger_type: str,
    value: int | float | None,
    lookback_period: str,
    lookback_interval: str,
    auto_adjust: bool,
    poll_every_seconds: int | None,
    timezone_name: str | None,
    expires_at: str | None,
    notification_enabled: bool,
    broker_actions_allowed: bool,
    runtime: SchedulerManagementRuntime,
) -> ScheduledProcess:
    if broker_actions_allowed:
        raise ValueError("broker_actions_allowed must be false; broker actions are unsupported.")
    resolved_symbol = str(symbol or "").strip().upper()
    if not resolved_symbol:
        raise ValueError("symbol is required for instrument monitor creation.")
    resolved_trigger_type = str(trigger_type or "").strip()
    if resolved_trigger_type not in INSTRUMENT_MONITOR_TRIGGER_TYPES:
        raise ValueError(f"Unsupported instrument monitor trigger_type '{trigger_type}'.")
    trigger: dict[str, Any] = {
        "type": resolved_trigger_type,
        "symbol": resolved_symbol,
    }
    if resolved_trigger_type in THRESHOLD_TRIGGER_TYPES:
        if value is None:
            raise ValueError(f"value is required for trigger_type '{resolved_trigger_type}'.")
        trigger["value"] = float(value)
    else:
        trigger["lookbackPeriod"] = str(lookback_period or "1mo").strip() or "1mo"
        trigger["lookbackInterval"] = str(lookback_interval or "1d").strip() or "1d"
        trigger["autoAdjust"] = bool(auto_adjust)

    poll_seconds = _positive_int(
        poll_every_seconds,
        fallback=runtime.default_poll_every_seconds,
        field_name="poll_every_seconds",
    )
    tz_name = str(timezone_name or runtime.default_timezone or "UTC").strip() or "UTC"
    expiry = _resolve_expires_at(expires_at, timezone_name=tz_name, runtime=runtime)
    resolved_title = str(title or "").strip()
    if not resolved_title:
        resolved_title = f"{resolved_symbol} {resolved_trigger_type} monitor"

    return runtime.service.create_process(
        title=resolved_title,
        description=str(description or "").strip(),
        kind="instrument_monitor",
        execution_mode="deterministic",
        schedule={"type": "polling", "pollEverySeconds": poll_seconds},
        trigger=trigger,
        inputs={"symbols": [resolved_symbol]},
        llm_scope={},
        action={},
        notification={"enabled": bool(notification_enabled)},
        lifecycle={
            "completionPolicy": "complete_on_first_match",
            "expiresAt": expiry.isoformat(),
        },
        safety={"brokerActionsAllowed": False},
    )


def _create_company_event_analyst(
    *,
    title: str | None,
    description: str,
    symbol: str,
    event_type: str,
    schedule_type: str,
    run_at: str | None,
    frequency: str | None,
    time_value: str | None,
    timezone_name: str | None,
    days: list[str],
    include_market_analyst: bool,
    task_guidelines: str,
    disclosure_since_days: int,
    search_time_range: str,
    market_period: str,
    notification_enabled: bool,
    broker_actions_allowed: bool,
    runtime: SchedulerManagementRuntime,
) -> ScheduledProcess:
    if broker_actions_allowed:
        raise ValueError("broker_actions_allowed must be false; broker actions are unsupported.")
    resolved_symbol = str(symbol or "").strip().upper()
    if not resolved_symbol:
        raise ValueError("symbol is required for company-event analyst creation.")
    resolved_event_type = str(event_type or "company_event").strip()
    if resolved_event_type not in COMPANY_EVENT_TYPES:
        raise ValueError(f"Unsupported event_type '{event_type}'.")
    resolved_schedule_type = str(schedule_type or "").strip()
    if resolved_schedule_type not in COMPANY_EVENT_SCHEDULE_TYPES:
        raise ValueError("schedule_type must be one_shot or recurring.")

    tz_name = str(timezone_name or runtime.default_timezone or "UTC").strip() or "UTC"
    _zone_info(tz_name)
    if resolved_schedule_type == "one_shot":
        schedule = {
            "type": "one_shot",
            "runAt": _resolve_run_at(run_at, timezone_name=tz_name).isoformat(),
        }
        completion_policy = "complete_on_first_run"
    else:
        resolved_frequency = str(frequency or "").strip().lower()
        if resolved_frequency not in COMPANY_EVENT_FREQUENCIES:
            raise ValueError("recurring schedules require frequency daily, weekdays, or weekly.")
        resolved_time = str(time_value or "").strip()
        if not resolved_time:
            raise ValueError("recurring schedules require time.")
        schedule = {
            "type": "recurring",
            "frequency": resolved_frequency,
            "time": resolved_time,
            "timezone": tz_name,
            "days": list(days or []),
        }
        completion_policy = "keep_running"

    resolved_title = str(title or "").strip()
    if not resolved_title:
        resolved_title = f"{resolved_symbol} {resolved_event_type.replace('_', ' ')} analysis"

    return runtime.service.create_process(
        title=resolved_title,
        description=str(description or "").strip(),
        kind="company_event_analyst",
        execution_mode="llm_assisted",
        schedule=schedule,
        trigger={
            "type": "company_event",
            "symbol": resolved_symbol,
            "eventType": resolved_event_type,
        },
        inputs={
            "symbols": [resolved_symbol],
            "eventType": resolved_event_type,
            "disclosureSinceDays": _positive_int(
                disclosure_since_days,
                fallback=30,
                field_name="disclosure_since_days",
            ),
            "searchTimeRange": str(search_time_range or "week").strip() or "week",
            "marketPeriod": str(market_period or "1mo").strip() or "1mo",
        },
        llm_scope={
            "taskGuidelines": str(task_guidelines or "").strip(),
            "includeMarketAnalyst": bool(include_market_analyst),
        },
        action={"type": "notify_only"},
        notification={"enabled": bool(notification_enabled)},
        lifecycle={"completionPolicy": completion_policy},
        safety={"brokerActionsAllowed": False},
    )


def _resolve_run_at(run_at: str | None, *, timezone_name: str) -> datetime:
    raw = str(run_at or "").strip()
    if not raw:
        raise ValueError("one_shot schedules require run_at.")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("run_at must be a valid ISO-8601 datetime.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_zone_info(timezone_name))
    return parsed.astimezone(timezone.utc)


def _positive_int(value: int | None, *, fallback: int, field_name: str) -> int:
    resolved = fallback if value is None else value
    try:
        parsed = int(resolved)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a positive integer.") from exc
    if parsed <= 0:
        raise ValueError(f"{field_name} must be greater than zero.")
    return parsed


def _resolve_expires_at(
    expires_at: str | None,
    *,
    timezone_name: str,
    runtime: SchedulerManagementRuntime,
) -> datetime:
    tz = _zone_info(timezone_name)
    raw = str(expires_at or "").strip()
    if raw:
        normalized = raw.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError("expires_at must be a valid ISO-8601 datetime.") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        return parsed.astimezone(timezone.utc)

    now = runtime.clock()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local_now = now.astimezone(tz)
    end_of_day = datetime.combine(
        local_now.date(),
        time(hour=23, minute=59, second=59),
        tzinfo=tz,
    )
    return end_of_day.astimezone(timezone.utc)


def _zone_info(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"timezone must be a valid IANA timezone: {timezone_name}.") from exc


def _process_payload(process: ScheduledProcess) -> dict[str, Any]:
    return process.model_dump(by_alias=True, exclude_none=True, mode="json")


def _list_output(processes: list[ScheduledProcess]) -> str:
    if not processes:
        return "No scheduled processes matched the provided filters."
    lines = [f"Found {len(processes)} scheduled process(es)."]
    for process in processes:
        lines.append(
            "- "
            + " | ".join(
                [
                    process.process_id,
                    process.kind.value,
                    process.status.value,
                    f"title={process.title}",
                    f"nextRunAt={process.next_run_at}",
                ]
            )
        )
    return "\n".join(lines)


def _missing_service() -> ToolResult:
    return ToolResult(
        status="error",
        output="Scheduled processes are not configured.",
        error=ToolError(
            message="Scheduled processes are not configured.",
            code="scheduled_processes_unavailable",
            hint="Configure DATABASE_URL and ensure the scheduler database schema is available.",
            retryable=False,
        ),
    )


def _tool_exception(exc: Exception, *, operation: str) -> ToolResult:
    return ToolResult(
        status="error",
        output=f"Scheduler {operation} failed. Reason: {exc}.",
        error=ToolError(
            message=str(exc),
            code="scheduler_management_error",
            type=exc.__class__.__name__,
            hint=(
                "Use an exact process id for lifecycle operations, and for creation "
                "provide a supported kind, schedule, lifecycle, and safe action policy."
            ),
            retryable=False,
            details={"operation": operation},
        ),
    )


def _instrument_monitor_exception(exc: Exception) -> ToolResult:
    return ToolResult(
        status="error",
        output=f"Instrument monitor creation failed. Reason: {exc}.",
        error=ToolError(
            message=str(exc),
            code="invalid_instrument_monitor_spec",
            type=exc.__class__.__name__,
            hint=(
                "Provide symbol, a supported trigger_type, value for price or "
                "percent-change triggers, positive poll_every_seconds if supplied, "
                "and keep broker_actions_allowed=false."
            ),
            retryable=False,
        ),
    )


def _company_event_exception(exc: Exception) -> ToolResult:
    return ToolResult(
        status="error",
        output=f"Company-event analyst creation failed. Reason: {exc}.",
        error=ToolError(
            message=str(exc),
            code="invalid_company_event_analyst_spec",
            type=exc.__class__.__name__,
            hint=(
                "Provide symbol and a supported one_shot or recurring schedule. "
                "one_shot requires run_at; recurring requires frequency, time, and "
                "timezone. Keep broker_actions_allowed=false."
            ),
            retryable=False,
        ),
    )
