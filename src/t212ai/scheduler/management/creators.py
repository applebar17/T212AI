"""Typed scheduled-process creation helpers."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from ..models import ScheduledProcess
from ..service import ScheduledProcessService
from .constants import (
    COMPANY_EVENT_FREQUENCIES,
    COMPANY_EVENT_SCHEDULE_TYPES,
    COMPANY_EVENT_TYPES,
    DEFAULT_MARKET_REGIME_DRAWDOWN_FROM_HIGH_PCT,
    DEFAULT_MARKET_REGIME_PERCENT_CHANGE_BELOW,
    DEFAULT_MARKET_SIGNAL_CAPTURE_POLL_SECONDS,
    INSTRUMENT_MONITOR_TRIGGER_TYPES,
    MARKET_REGIME_PROXY_LABELS,
    MARKET_SIGNAL_CAPTURE_FREQUENCIES,
    MARKET_SIGNAL_CAPTURE_SCHEDULE_TYPES,
    MIN_MARKET_SIGNAL_CAPTURE_POLL_SECONDS,
    THRESHOLD_TRIGGER_TYPES,
    TRADE_SETUP_ORDER_TYPES,
    TRADE_SETUP_SIDES,
)
from .runtime import SchedulerManagementRuntime
from .utils import (
    _clean_order_terms,
    _clean_symbols,
    _clean_terms,
    _dedupe_terms,
    _optional_decimal,
    _optional_float,
    _positive_int,
    _resolve_expires_at,
    _resolve_optional_datetime,
    _resolve_run_at,
    _resolve_stream_end_at,
    _zone_info,
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


def _create_market_regime_monitor(
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
    timezone_name: str | None,
    expires_at: str | None,
    search_time_range: str,
    task_guidelines: str,
    notification_enabled: bool,
    broker_actions_allowed: bool,
    runtime: SchedulerManagementRuntime,
) -> ScheduledProcess:
    if broker_actions_allowed:
        raise ValueError("broker_actions_allowed must be false; broker actions are unsupported.")
    resolved_proxy_symbol, resolved_label = _resolve_market_proxy(
        market_label=market_label,
        proxy_symbol=proxy_symbol,
    )
    resolved_percent = _optional_float(percent_change_below)
    resolved_drawdown = _optional_float(drawdown_from_high_pct)
    if resolved_percent is None and resolved_drawdown is None:
        resolved_percent = DEFAULT_MARKET_REGIME_PERCENT_CHANGE_BELOW
        resolved_drawdown = DEFAULT_MARKET_REGIME_DRAWDOWN_FROM_HIGH_PCT
    if resolved_percent is not None and resolved_percent >= 0:
        raise ValueError("percent_change_below must be a negative percentage value.")
    if resolved_drawdown is not None and resolved_drawdown <= 0:
        raise ValueError("drawdown_from_high_pct must be a positive percentage value.")

    poll_seconds = _positive_int(
        poll_every_seconds,
        fallback=runtime.default_poll_every_seconds,
        field_name="poll_every_seconds",
    )
    tz_name = str(timezone_name or runtime.default_timezone or "UTC").strip() or "UTC"
    expiry = _resolve_expires_at(expires_at, timezone_name=tz_name, runtime=runtime)
    resolved_lookback_period = str(lookback_period or "1mo").strip() or "1mo"
    resolved_lookback_interval = str(lookback_interval or "1d").strip() or "1d"
    conditions: list[dict[str, Any]] = []
    if resolved_percent is not None:
        conditions.append({"type": "percent_change_below", "value": resolved_percent})
    if resolved_drawdown is not None:
        conditions.append(
            {
                "type": "drawdown_from_high_pct",
                "value": resolved_drawdown,
                "lookbackPeriod": resolved_lookback_period,
                "lookbackInterval": resolved_lookback_interval,
                "autoAdjust": bool(auto_adjust),
            }
        )
    resolved_title = str(title or "").strip()
    if not resolved_title:
        resolved_title = f"{resolved_label} market-regime stress monitor"

    return runtime.service.create_process(
        title=resolved_title,
        description=str(description or "").strip(),
        kind="market_regime_monitor",
        execution_mode="llm_assisted",
        schedule={"type": "polling", "pollEverySeconds": poll_seconds},
        trigger={
            "type": "market_regime_stress",
            "proxySymbol": resolved_proxy_symbol,
            "proxyLabel": resolved_label,
            "conditions": conditions,
            "lookbackPeriod": resolved_lookback_period,
            "lookbackInterval": resolved_lookback_interval,
            "autoAdjust": bool(auto_adjust),
        },
        inputs={
            "proxySymbol": resolved_proxy_symbol,
            "proxyLabel": resolved_label,
            "searchTimeRange": str(search_time_range or "day").strip() or "day",
        },
        llm_scope={"taskGuidelines": str(task_guidelines or "").strip()},
        action={"type": "notify_only"},
        notification={"enabled": bool(notification_enabled)},
        lifecycle={
            "completionPolicy": "complete_on_first_match",
            "expiresAt": expiry.isoformat(),
        },
        safety={"brokerActionsAllowed": False},
    )


def _create_market_signal_capture(
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
    time_value: str | None,
    timezone_name: str | None,
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
) -> ScheduledProcess:
    if broker_actions_allowed:
        raise ValueError("broker_actions_allowed must be false; broker actions are unsupported.")
    resolved_query = str(query or "").strip()
    resolved_symbols = _clean_symbols(symbols)
    resolved_sectors = _clean_terms(sectors)
    resolved_tags = _clean_terms(tags)
    if not (resolved_query or resolved_symbols or resolved_sectors or resolved_tags):
        raise ValueError("query, symbols, sectors, or tags are required.")
    resolved_max_signals = _positive_int(
        max_signals,
        fallback=3,
        field_name="max_signals",
    )
    if resolved_max_signals < 1 or resolved_max_signals > 3:
        raise ValueError("max_signals must be between 1 and 3.")
    resolved_schedule_type = str(schedule_type or "").strip()
    if resolved_schedule_type not in MARKET_SIGNAL_CAPTURE_SCHEDULE_TYPES:
        raise ValueError("schedule_type must be polling or recurring.")
    tz_name = str(timezone_name or runtime.default_timezone or "UTC").strip() or "UTC"
    _zone_info(tz_name)
    if resolved_schedule_type == "polling":
        poll_seconds = _positive_int(
            poll_every_seconds,
            fallback=DEFAULT_MARKET_SIGNAL_CAPTURE_POLL_SECONDS,
            field_name="poll_every_seconds",
        )
        if poll_seconds < MIN_MARKET_SIGNAL_CAPTURE_POLL_SECONDS:
            raise ValueError("poll_every_seconds must be at least 900.")
        schedule = {"type": "polling", "pollEverySeconds": poll_seconds}
    else:
        resolved_frequency = str(frequency or "").strip().lower()
        if resolved_frequency not in MARKET_SIGNAL_CAPTURE_FREQUENCIES:
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

    resolved_title = str(title or "").strip()
    if not resolved_title:
        resolved_title = _market_signal_capture_title(
            query=resolved_query,
            symbols=resolved_symbols,
            sectors=resolved_sectors,
            tags=resolved_tags,
        )

    inputs = {
        "query": resolved_query or None,
        "symbols": resolved_symbols,
        "sectors": resolved_sectors,
        "tags": resolved_tags,
        "maxSignals": resolved_max_signals,
        "searchTimeRange": str(search_time_range or "day").strip() or "day",
        "communityTimeRange": str(community_time_range or "week").strip() or "week",
        "marketPeriod": str(market_period or "1mo").strip() or "1mo",
        "disclosureSinceDays": _positive_int(
            disclosure_since_days,
            fallback=30,
            field_name="disclosure_since_days",
        ),
    }

    return runtime.service.create_process(
        title=resolved_title,
        description=str(description or "").strip(),
        kind="market_signal_capture",
        execution_mode="llm_assisted",
        schedule=schedule,
        trigger={
            "type": "market_signal_capture",
            "query": resolved_query or None,
            "symbols": resolved_symbols,
            "sectors": resolved_sectors,
            "tags": resolved_tags,
        },
        inputs=inputs,
        llm_scope={"taskGuidelines": str(task_guidelines or "").strip()},
        action={"type": "notify_only"},
        notification={"enabled": bool(notification_enabled)},
        lifecycle={"completionPolicy": "keep_running"},
        safety={"brokerActionsAllowed": False},
    )


def _create_alpaca_news_monitor(
    *,
    title: str | None,
    description: str,
    symbols: list[str],
    start_at: str | None,
    end_at: str | None,
    duration_minutes: int | None,
    timezone_name: str | None,
    task_guidelines: str,
    order_proposals_enabled: bool,
    max_events_per_minute: int,
    notification_enabled: bool,
    broker_actions_allowed: bool,
    runtime: SchedulerManagementRuntime,
) -> ScheduledProcess:
    if broker_actions_allowed:
        raise ValueError(
            "broker_actions_allowed must be false; stream monitors may prepare "
            "approval-gated proposals but never execute broker actions."
        )
    resolved_symbols = _clean_symbols(symbols)
    if not resolved_symbols:
        raise ValueError("At least one symbol is required for Alpaca news monitoring.")
    tz_name = str(timezone_name or runtime.default_timezone or "UTC").strip() or "UTC"
    _zone_info(tz_name)
    start = _resolve_optional_datetime(
        start_at,
        timezone_name=tz_name,
        fallback=runtime.clock(),
        field_name="start_at",
    )
    end = _resolve_stream_end_at(
        end_at=end_at,
        duration_minutes=duration_minutes,
        timezone_name=tz_name,
        start=start,
    )
    if end <= start:
        raise ValueError("Alpaca news monitor end_at must be after start_at.")
    resolved_max_events = _positive_int(
        max_events_per_minute,
        fallback=30,
        field_name="max_events_per_minute",
    )
    if resolved_max_events > 120:
        raise ValueError("max_events_per_minute must be between 1 and 120.")
    resolved_title = str(title or "").strip()
    if not resolved_title:
        resolved_title = "Alpaca news monitor: " + ", ".join(resolved_symbols)

    return runtime.service.create_process(
        title=resolved_title,
        description=str(description or "").strip(),
        kind="alpaca_news_monitor",
        execution_mode="llm_assisted",
        schedule={"type": "manual"},
        trigger={"type": "alpaca_news_stream", "symbols": resolved_symbols},
        inputs={
            "symbols": resolved_symbols,
            "startAt": start.isoformat(),
            "endAt": end.isoformat(),
            "timezone": tz_name,
            "taskGuidelines": str(task_guidelines or "").strip(),
            "orderProposalsEnabled": bool(order_proposals_enabled),
            "maxEventsPerMinute": resolved_max_events,
            "chatId": runtime.chat_id,
            "userId": runtime.user_id,
        },
        llm_scope={
            "taskGuidelines": str(task_guidelines or "").strip(),
            "orderProposalsEnabled": bool(order_proposals_enabled),
        },
        action={
            "type": "judge_news",
            "orderProposalsEnabled": bool(order_proposals_enabled),
        },
        notification={"enabled": bool(notification_enabled), "chatId": runtime.chat_id},
        lifecycle={"completionPolicy": "complete_on_first_run", "expiresAt": end.isoformat()},
        safety={"brokerActionsAllowed": False},
    )


def _market_signal_capture_title(
    *,
    query: str,
    symbols: list[str],
    sectors: list[str],
    tags: list[str],
) -> str:
    if query:
        return f"Market signal capture: {query}"
    if symbols:
        return "Market signal capture: " + ", ".join(symbols)
    if sectors:
        return "Market signal capture: " + ", ".join(sectors)
    return "Market signal capture: " + ", ".join(tags)


def _create_trade_setup_monitor(
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
    timezone_name: str | None,
    expires_at: str | None,
    task_guidelines: str,
    notification_enabled: bool,
    broker_actions_allowed: bool,
    runtime: SchedulerManagementRuntime,
) -> ScheduledProcess:
    if broker_actions_allowed:
        raise ValueError("broker_actions_allowed must be false; broker actions are unsupported.")
    resolved_symbol = str(symbol or "").strip().upper()
    if not resolved_symbol:
        raise ValueError("symbol is required for trade setup monitor creation.")
    resolved_trigger_type = str(trigger_type or "").strip()
    if resolved_trigger_type not in INSTRUMENT_MONITOR_TRIGGER_TYPES:
        raise ValueError(f"Unsupported trigger_type '{trigger_type}'.")
    trigger: dict[str, Any] = {"type": resolved_trigger_type, "symbol": resolved_symbol}
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
    action: dict[str, Any] = {
        "type": "notify_or_propose",
        "proposalCreationAllowed": bool(proposal_creation_allowed),
    }
    if proposal_creation_allowed:
        policy_symbols = _clean_symbols(allowed_symbols) or [resolved_symbol]
        if resolved_symbol not in policy_symbols:
            policy_symbols.insert(0, resolved_symbol)
        policy_sides = _clean_order_terms(allowed_sides, allowed=TRADE_SETUP_SIDES, field_name="allowed_sides")
        policy_order_types = _clean_order_terms(
            allowed_order_types,
            allowed=TRADE_SETUP_ORDER_TYPES,
            field_name="allowed_order_types",
        )
        max_notional = _optional_decimal(max_notional_amount, field_name="max_notional_amount")
        max_qty = _optional_decimal(max_quantity, field_name="max_quantity")
        currency = str(notional_currency or "").strip().upper()
        if max_notional is None and max_qty is None:
            raise ValueError("proposal creation requires max_notional_amount or max_quantity.")
        if max_notional is not None and (max_notional <= 0 or not currency):
            raise ValueError("max_notional_amount requires a positive value and notional_currency.")
        if max_qty is not None and max_qty <= 0:
            raise ValueError("max_quantity must be positive.")
        resolved_chat_id = approval_chat_id
        if resolved_chat_id is None and str(runtime.chat_id or "").strip():
            resolved_chat_id = int(str(runtime.chat_id).strip())
        if resolved_chat_id is None:
            raise ValueError("proposal creation requires approval_chat_id or invoking chat context.")
        action["orderPolicy"] = {
            "allowedSymbols": policy_symbols,
            "allowedSides": policy_sides,
            "allowedOrderTypes": policy_order_types,
            "maxNotionalAmount": str(max_notional) if max_notional is not None else None,
            "notionalCurrency": currency or None,
            "maxQuantity": str(max_qty) if max_qty is not None else None,
            "allowExtendedHours": bool(allow_extended_hours),
        }
        action["approval"] = {
            "chatId": int(resolved_chat_id),
            "userId": approval_user_id if approval_user_id is not None else runtime.user_id,
        }

    resolved_title = str(title or "").strip()
    if not resolved_title:
        resolved_title = f"{resolved_symbol} trade setup monitor"
    return runtime.service.create_process(
        title=resolved_title,
        description=str(description or "").strip(),
        kind="trade_setup_monitor",
        execution_mode="llm_assisted",
        schedule={"type": "polling", "pollEverySeconds": poll_seconds},
        trigger=trigger,
        inputs={"symbol": resolved_symbol},
        llm_scope={"taskGuidelines": str(task_guidelines or "").strip()},
        action=action,
        notification={"enabled": bool(notification_enabled)},
        lifecycle={
            "completionPolicy": "complete_on_first_match",
            "expiresAt": expiry.isoformat(),
        },
        safety={"brokerActionsAllowed": False},
    )


def _resolve_market_proxy(
    *,
    market_label: str | None,
    proxy_symbol: str | None,
) -> tuple[str, str]:
    raw_label = str(market_label or "").strip()
    normalized_label = " ".join(raw_label.lower().replace("_", " ").split())
    explicit_proxy = str(proxy_symbol or "").strip().upper()
    if normalized_label:
        mapped = MARKET_REGIME_PROXY_LABELS.get(normalized_label)
        if mapped is not None:
            return mapped
        if not explicit_proxy:
            allowed = ", ".join(
                ["market", "S&P 500", "Nasdaq", "Dow", "Russell 2000", "small caps"]
            )
            raise ValueError(
                f"Unsupported market_label '{market_label}'. Use one of: {allowed}; "
                "or provide proxy_symbol explicitly."
            )
    if explicit_proxy:
        return explicit_proxy, raw_label or explicit_proxy
    raise ValueError("Provide either proxy_symbol or a known market_label.")
