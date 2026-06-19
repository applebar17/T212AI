"""Public scheduler management tool handlers."""

from __future__ import annotations

from typing import Callable

from t212ai.genai.models import ToolResult
from t212ai.genai.tracing import set_trace_metadata, traceable

from ..models import ScheduledProcess
from ..service import ScheduledProcessService
from .creators import (
    _create_alpaca_news_monitor,
    _create_company_event_analyst,
    _create_instrument_monitor,
    _create_market_regime_monitor,
    _create_market_signal_capture,
    _create_trade_setup_monitor,
)
from .runtime import SchedulerManagementRuntime
from .utils import (
    _alpaca_news_monitor_exception,
    _company_event_exception,
    _instrument_monitor_exception,
    _list_output,
    _market_regime_exception,
    _market_signal_capture_exception,
    _missing_service,
    _process_payload,
    _tool_exception,
    _trade_setup_exception,
)


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


@traceable(name="scheduler_market_regime_monitor_create", run_type="tool")
def scheduler_market_regime_monitor_create(
    *,
    title: str | None,
    description: str,
    market_label: str | None,
    proxy_symbol: str | None,
    percent_change_below: int | float | None,
    drawdown_from_high_pct: int | float | None,
    lookback_period: str,
    lookback_interval: str,
    auto_adjust: bool,
    poll_every_seconds: int | None,
    timezone: str | None,
    expires_at: str | None,
    search_time_range: str,
    task_guidelines: str,
    notification_enabled: bool,
    broker_actions_allowed: bool,
    runtime: SchedulerManagementRuntime,
) -> ToolResult:
    set_trace_metadata(
        provider="scheduler",
        tool_name="scheduler_market_regime_monitor_create",
    )
    if runtime.service is None:
        return _missing_service()
    try:
        process = _create_market_regime_monitor(
            title=title,
            description=description,
            market_label=market_label,
            proxy_symbol=proxy_symbol,
            percent_change_below=percent_change_below,
            drawdown_from_high_pct=drawdown_from_high_pct,
            lookback_period=lookback_period,
            lookback_interval=lookback_interval,
            auto_adjust=auto_adjust,
            poll_every_seconds=poll_every_seconds,
            timezone_name=timezone,
            expires_at=expires_at,
            search_time_range=search_time_range,
            task_guidelines=task_guidelines,
            notification_enabled=notification_enabled,
            broker_actions_allowed=broker_actions_allowed,
            runtime=runtime,
        )
    except Exception as exc:
        return _market_regime_exception(exc)
    return ToolResult(
        status="ok",
        output=(
            f"Created market-regime monitor {process.process_id}: {process.title}. "
            f"Proxy: {process.inputs.get('proxyLabel')} ({process.inputs.get('proxySymbol')}). "
            f"Schedule: polling every {process.schedule.poll_every_seconds} seconds. "
            f"Lifecycle: {process.lifecycle.completion_policy.value}, "
            f"expiresAt={process.lifecycle.expires_at}. "
            "No broker action was configured."
        ),
        data={"process": _process_payload(process)},
    )


@traceable(name="scheduler_market_signal_capture_create", run_type="tool")
def scheduler_market_signal_capture_create(
    *,
    title: str | None,
    description: str,
    query: str | None,
    symbols: list[str],
    sectors: list[str],
    tags: list[str],
    schedule_type: str,
    poll_every_seconds: int | None,
    frequency: str | None,
    time: str | None,
    timezone: str | None,
    days: list[str],
    task_guidelines: str,
    max_signals: int,
    search_time_range: str,
    community_time_range: str,
    market_period: str,
    disclosure_since_days: int,
    notification_enabled: bool,
    broker_actions_allowed: bool,
    runtime: SchedulerManagementRuntime,
) -> ToolResult:
    set_trace_metadata(
        provider="scheduler",
        tool_name="scheduler_market_signal_capture_create",
    )
    if runtime.service is None:
        return _missing_service()
    try:
        process = _create_market_signal_capture(
            title=title,
            description=description,
            query=query,
            symbols=symbols,
            sectors=sectors,
            tags=tags,
            schedule_type=schedule_type,
            poll_every_seconds=poll_every_seconds,
            frequency=frequency,
            time_value=time,
            timezone_name=timezone,
            days=days,
            task_guidelines=task_guidelines,
            max_signals=max_signals,
            search_time_range=search_time_range,
            community_time_range=community_time_range,
            market_period=market_period,
            disclosure_since_days=disclosure_since_days,
            notification_enabled=notification_enabled,
            broker_actions_allowed=broker_actions_allowed,
            runtime=runtime,
        )
    except Exception as exc:
        return _market_signal_capture_exception(exc)
    schedule_summary = (
        f"polling every {process.schedule.poll_every_seconds} seconds"
        if process.schedule.type.value == "polling"
        else (
            f"recurring {process.schedule.frequency} at {process.schedule.time} "
            f"{process.schedule.timezone}"
        )
    )
    return ToolResult(
        status="ok",
        output=(
            f"Created market-signal capture process {process.process_id}: "
            f"{process.title}. Schedule: {schedule_summary}. Lifecycle: "
            f"{process.lifecycle.completion_policy.value}. Max signals per run: "
            f"{process.inputs.get('maxSignals')}. No broker action was configured. "
            "Saved market signals are advisory memory only."
        ),
        data={"process": _process_payload(process)},
    )


@traceable(name="scheduler_alpaca_news_monitor_create", run_type="tool")
def scheduler_alpaca_news_monitor_create(
    *,
    title: str | None,
    description: str,
    symbols: list[str] | None = None,
    start_at: str | None,
    end_at: str | None,
    duration_minutes: int | None,
    timezone: str | None,
    task_guidelines: str,
    order_proposals_enabled: bool,
    max_events_per_minute: int,
    notification_enabled: bool,
    broker_actions_allowed: bool,
    runtime: SchedulerManagementRuntime,
) -> ToolResult:
    set_trace_metadata(
        provider="scheduler",
        tool_name="scheduler_alpaca_news_monitor_create",
    )
    if runtime.service is None:
        return _missing_service()
    try:
        process = _create_alpaca_news_monitor(
            title=title,
            description=description,
            symbols=symbols,
            start_at=start_at,
            end_at=end_at,
            duration_minutes=duration_minutes,
            timezone_name=timezone,
            task_guidelines=task_guidelines,
            order_proposals_enabled=order_proposals_enabled,
            max_events_per_minute=max_events_per_minute,
            notification_enabled=notification_enabled,
            broker_actions_allowed=broker_actions_allowed,
            runtime=runtime,
        )
    except Exception as exc:
        return _alpaca_news_monitor_exception(exc)
    inputs = process.inputs
    symbols_label = ", ".join(inputs.get("symbols") or [])
    return ToolResult(
        status="ok",
        output=(
            f"Created Alpaca news monitor {process.process_id}: {process.title}. "
            f"Symbols: {symbols_label}. Window: {inputs.get('startAt')} to "
            f"{inputs.get('endAt')} UTC. Notifications: "
            f"{'enabled' if process.notification.get('enabled') else 'disabled'}. "
            "Broker execution remains approval-button gated."
        ),
        data={"process": _process_payload(process)},
    )


@traceable(name="scheduler_trade_setup_monitor_create", run_type="tool")
def scheduler_trade_setup_monitor_create(
    *,
    title: str | None,
    description: str,
    symbol: str,
    trigger_type: str,
    value: int | float | None,
    lookback_period: str,
    lookback_interval: str,
    auto_adjust: bool,
    proposal_creation_allowed: bool,
    allowed_symbols: list[str],
    allowed_sides: list[str],
    allowed_order_types: list[str],
    max_notional_amount: int | float | None,
    notional_currency: str | None,
    max_quantity: int | float | None,
    allow_extended_hours: bool,
    approval_chat_id: int | None,
    approval_user_id: int | None,
    poll_every_seconds: int | None,
    timezone: str | None,
    expires_at: str | None,
    task_guidelines: str,
    notification_enabled: bool,
    broker_actions_allowed: bool,
    runtime: SchedulerManagementRuntime,
) -> ToolResult:
    set_trace_metadata(
        provider="scheduler",
        tool_name="scheduler_trade_setup_monitor_create",
    )
    if runtime.service is None:
        return _missing_service()
    try:
        process = _create_trade_setup_monitor(
            title=title,
            description=description,
            symbol=symbol,
            trigger_type=trigger_type,
            value=value,
            lookback_period=lookback_period,
            lookback_interval=lookback_interval,
            auto_adjust=auto_adjust,
            proposal_creation_allowed=proposal_creation_allowed,
            allowed_symbols=allowed_symbols,
            allowed_sides=allowed_sides,
            allowed_order_types=allowed_order_types,
            max_notional_amount=max_notional_amount,
            notional_currency=notional_currency,
            max_quantity=max_quantity,
            allow_extended_hours=allow_extended_hours,
            approval_chat_id=approval_chat_id,
            approval_user_id=approval_user_id,
            poll_every_seconds=poll_every_seconds,
            timezone_name=timezone,
            expires_at=expires_at,
            task_guidelines=task_guidelines,
            notification_enabled=notification_enabled,
            broker_actions_allowed=broker_actions_allowed,
            runtime=runtime,
        )
    except Exception as exc:
        return _trade_setup_exception(exc)
    return ToolResult(
        status="ok",
        output=(
            f"Created trade setup monitor {process.process_id}: {process.title}. "
            f"Trigger: {process.trigger.get('type')} for {process.trigger.get('symbol')}. "
            f"Schedule: polling every {process.schedule.poll_every_seconds} seconds. "
            f"Lifecycle: {process.lifecycle.completion_policy.value}, "
            f"expiresAt={process.lifecycle.expires_at}. "
            f"Proposal creation allowed: {process.action.get('proposalCreationAllowed')}. "
            "No broker action was configured; any future proposal requires Telegram button approval."
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
