from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from t212ai.persistence.database import build_engine, build_session_factory, ensure_schema
from t212ai.scheduler import (
    SCHEDULER_AGENT_TOOLBOX,
    ScheduledProcessService,
    SchedulerManagementRuntime,
    build_scheduler_agent_tool_mapping,
    build_scheduler_management_tool_mapping,
    scheduler_alpaca_news_monitor_create,
    scheduler_archive_process,
    scheduler_company_event_analyst_create,
    scheduler_create_process,
    scheduler_instrument_monitor_create,
    scheduler_list_processes,
    scheduler_market_regime_monitor_create,
    scheduler_market_signal_capture_create,
    scheduler_pause_process,
    scheduler_resume_process,
    scheduler_trade_setup_monitor_create,
)


def _service(tmp_path: Path) -> ScheduledProcessService:
    engine = build_engine(f"sqlite:///{tmp_path / 'scheduler-management.db'}")
    ensure_schema(engine)
    return ScheduledProcessService(build_session_factory(engine))


def test_scheduler_management_tools_create_list_pause_resume_and_archive(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    runtime = SchedulerManagementRuntime(service=service)

    created = scheduler_create_process(
        title="TSLA threshold monitor",
        description="Watch a threshold.",
        kind="instrument_monitor",
        execution_mode="deterministic",
        schedule={"type": "polling", "pollEverySeconds": 60},
        trigger={"type": "below_price", "symbol": "TSLA", "value": 180},
        inputs={"symbols": ["TSLA"]},
        llm_scope={},
        action={},
        notification={"mode": "telegram"},
        lifecycle={"completionPolicy": "keep_running"},
        safety={},
        runtime=runtime,
    )

    assert created.status == "ok"
    process_id = created.data["process"]["processId"]
    assert process_id.startswith("sched_")

    listed = scheduler_list_processes(
        statuses=["active"],
        kinds=["instrument_monitor"],
        limit=10,
        runtime=runtime,
    )
    assert listed.status == "ok"
    assert listed.data["count"] == 1
    assert process_id in listed.output

    paused = scheduler_pause_process(process_id=process_id, runtime=runtime)
    assert paused.status == "ok"
    assert paused.data["process"]["status"] == "paused"

    resumed = scheduler_resume_process(process_id=process_id, runtime=runtime)
    assert resumed.status == "ok"
    assert resumed.data["process"]["status"] == "active"

    archived = scheduler_archive_process(process_id=process_id, runtime=runtime)
    assert archived.status == "ok"
    assert archived.data["process"]["status"] == "archived"
    assert service.get_process(process_id) is not None


def test_scheduler_management_tools_return_verbose_errors(tmp_path: Path) -> None:
    runtime = SchedulerManagementRuntime(service=_service(tmp_path))

    result = scheduler_pause_process(process_id="sched_missing", runtime=runtime)

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "scheduler_management_error"
    assert "exact process id" in result.error.hint


def test_scheduler_management_tools_report_missing_service() -> None:
    runtime = SchedulerManagementRuntime(service=None)

    result = scheduler_list_processes(
        statuses=None,
        kinds=None,
        limit=10,
        runtime=runtime,
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "scheduled_processes_unavailable"


def test_scheduler_management_tool_mapping_exposes_expected_handlers(
    tmp_path: Path,
) -> None:
    mapping = build_scheduler_management_tool_mapping(_service(tmp_path))

    assert set(mapping) == {
        "scheduler_create_process",
        "scheduler_list_processes",
        "scheduler_pause_process",
        "scheduler_resume_process",
        "scheduler_archive_process",
    }


def test_scheduler_instrument_monitor_create_applies_defaults(tmp_path: Path) -> None:
    service = _service(tmp_path)
    runtime = SchedulerManagementRuntime(
        service=service,
        default_timezone="UTC",
        default_poll_every_seconds=300,
        clock=lambda: datetime(2026, 5, 7, 10, 30, tzinfo=UTC),
    )

    result = scheduler_instrument_monitor_create(
        title=None,
        description="Alert on downside threshold.",
        symbol="tsla",
        trigger_type="below_price",
        value=180,
        lookback_period="1mo",
        lookback_interval="1d",
        auto_adjust=False,
        poll_every_seconds=None,
        timezone=None,
        expires_at=None,
        notification_enabled=True,
        broker_actions_allowed=False,
        runtime=runtime,
    )

    assert result.status == "ok"
    assert "No broker action" in result.output
    process_id = result.data["process"]["processId"]
    process = service.get_process(process_id)
    assert process is not None
    assert process.kind.value == "instrument_monitor"
    assert process.execution_mode.value == "deterministic"
    assert process.status.value == "active"
    assert process.schedule.type.value == "polling"
    assert process.schedule.poll_every_seconds == 300
    assert process.trigger == {"type": "below_price", "symbol": "TSLA", "value": 180.0}
    assert process.lifecycle.completion_policy.value == "complete_on_first_match"
    assert process.lifecycle.expires_at == datetime(2026, 5, 7, 23, 59, 59, tzinfo=UTC)
    assert process.notification == {"enabled": True}
    assert process.safety.broker_actions_allowed is False


def test_scheduler_instrument_monitor_create_rejects_invalid_inputs(tmp_path: Path) -> None:
    runtime = SchedulerManagementRuntime(service=_service(tmp_path))

    missing_value = scheduler_instrument_monitor_create(
        title=None,
        description="",
        symbol="TSLA",
        trigger_type="above_price",
        value=None,
        lookback_period="1mo",
        lookback_interval="1d",
        auto_adjust=False,
        poll_every_seconds=None,
        timezone=None,
        expires_at=None,
        notification_enabled=True,
        broker_actions_allowed=False,
        runtime=runtime,
    )
    missing_symbol = scheduler_instrument_monitor_create(
        title=None,
        description="",
        symbol="",
        trigger_type="above_price",
        value=200,
        lookback_period="1mo",
        lookback_interval="1d",
        auto_adjust=False,
        poll_every_seconds=None,
        timezone=None,
        expires_at=None,
        notification_enabled=True,
        broker_actions_allowed=False,
        runtime=runtime,
    )
    unsupported = scheduler_instrument_monitor_create(
        title=None,
        description="",
        symbol="TSLA",
        trigger_type="unsupported",
        value=200,
        lookback_period="1mo",
        lookback_interval="1d",
        auto_adjust=False,
        poll_every_seconds=None,
        timezone=None,
        expires_at=None,
        notification_enabled=True,
        broker_actions_allowed=False,
        runtime=runtime,
    )
    unsafe = scheduler_instrument_monitor_create(
        title=None,
        description="",
        symbol="TSLA",
        trigger_type="above_price",
        value=200,
        lookback_period="1mo",
        lookback_interval="1d",
        auto_adjust=False,
        poll_every_seconds=None,
        timezone=None,
        expires_at=None,
        notification_enabled=True,
        broker_actions_allowed=True,
        runtime=runtime,
    )

    for result in (missing_value, missing_symbol, unsupported, unsafe):
        assert result.status == "error"
        assert result.error is not None
        assert result.error.code == "invalid_instrument_monitor_spec"


def test_scheduler_company_event_analyst_create_one_shot_applies_defaults(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    runtime = SchedulerManagementRuntime(
        service=service,
        default_timezone="UTC",
    )

    result = scheduler_company_event_analyst_create(
        title=None,
        description="Analyze the quarterly report after publication.",
        symbol="msft",
        event_type="earnings_report",
        schedule_type="one_shot",
        run_at="2026-05-07T22:00:00Z",
        frequency=None,
        time=None,
        timezone=None,
        days=[],
        include_market_analyst=True,
        task_guidelines="Focus on Azure, guidance, risks, and thesis impact.",
        disclosure_since_days=30,
        search_time_range="week",
        market_period="1mo",
        notification_enabled=True,
        broker_actions_allowed=False,
        runtime=runtime,
    )

    assert result.status == "ok"
    assert "No broker action" in result.output
    process_id = result.data["process"]["processId"]
    process = service.get_process(process_id)
    assert process is not None
    assert process.kind.value == "company_event_analyst"
    assert process.execution_mode.value == "llm_assisted"
    assert process.schedule.type.value == "one_shot"
    assert process.schedule.run_at == datetime(2026, 5, 7, 22, 0, tzinfo=UTC)
    assert process.trigger == {
        "type": "company_event",
        "symbol": "MSFT",
        "eventType": "earnings_report",
    }
    assert process.inputs["disclosureSinceDays"] == 30
    assert process.inputs["searchTimeRange"] == "week"
    assert process.inputs["marketPeriod"] == "1mo"
    assert process.llm_scope["includeMarketAnalyst"] is True
    assert process.action == {"type": "notify_only"}
    assert process.lifecycle.completion_policy.value == "complete_on_first_run"
    assert process.notification == {"enabled": True}
    assert process.safety.broker_actions_allowed is False


def test_scheduler_company_event_analyst_create_recurring_applies_defaults(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    runtime = SchedulerManagementRuntime(
        service=service,
        default_timezone="Europe/Rome",
    )

    result = scheduler_company_event_analyst_create(
        title="AAPL weekly filing review",
        description="Weekly company-event scan.",
        symbol="AAPL",
        event_type="filing",
        schedule_type="recurring",
        run_at=None,
        frequency="weekdays",
        time="22:00",
        timezone=None,
        days=[],
        include_market_analyst=False,
        task_guidelines="Summarize only material changes.",
        disclosure_since_days=15,
        search_time_range="month",
        market_period="3mo",
        notification_enabled=False,
        broker_actions_allowed=False,
        runtime=runtime,
    )

    assert result.status == "ok"
    process = service.get_process(result.data["process"]["processId"])
    assert process is not None
    assert process.schedule.type.value == "recurring"
    assert process.schedule.frequency == "weekdays"
    assert process.schedule.time == "22:00"
    assert process.schedule.timezone == "Europe/Rome"
    assert process.lifecycle.completion_policy.value == "keep_running"
    assert process.llm_scope["includeMarketAnalyst"] is False
    assert process.notification == {"enabled": False}


def test_scheduler_company_event_analyst_create_rejects_invalid_inputs(
    tmp_path: Path,
) -> None:
    runtime = SchedulerManagementRuntime(service=_service(tmp_path))
    base = {
        "title": None,
        "description": "",
        "symbol": "MSFT",
        "event_type": "company_event",
        "schedule_type": "one_shot",
        "run_at": "2026-05-07T22:00:00Z",
        "frequency": None,
        "time": None,
        "timezone": None,
        "days": [],
        "include_market_analyst": False,
        "task_guidelines": "",
        "disclosure_since_days": 30,
        "search_time_range": "week",
        "market_period": "1mo",
        "notification_enabled": True,
        "broker_actions_allowed": False,
        "runtime": runtime,
    }

    missing_symbol = scheduler_company_event_analyst_create(**{**base, "symbol": ""})
    missing_run_at = scheduler_company_event_analyst_create(**{**base, "run_at": None})
    unsupported_event = scheduler_company_event_analyst_create(
        **{**base, "event_type": "arbitrary_prompt"}
    )
    unsafe = scheduler_company_event_analyst_create(
        **{**base, "broker_actions_allowed": True}
    )

    for result in (missing_symbol, missing_run_at, unsupported_event, unsafe):
        assert result.status == "error"
        assert result.error is not None
        assert result.error.code == "invalid_company_event_analyst_spec"


def test_scheduler_market_regime_monitor_create_applies_defaults_and_proxy_mapping(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    runtime = SchedulerManagementRuntime(
        service=service,
        default_timezone="UTC",
        default_poll_every_seconds=300,
        clock=lambda: datetime(2026, 5, 7, 10, 30, tzinfo=UTC),
    )

    result = scheduler_market_regime_monitor_create(
        title=None,
        description="Monitor a vague Nasdaq crash/stress request.",
        market_label="nasdaq",
        proxy_symbol=None,
        percent_change_below=None,
        drawdown_from_high_pct=None,
        lookback_period="1mo",
        lookback_interval="1d",
        auto_adjust=False,
        poll_every_seconds=None,
        timezone=None,
        expires_at=None,
        search_time_range="day",
        task_guidelines="Explain likely drivers if stress matches.",
        notification_enabled=True,
        broker_actions_allowed=False,
        runtime=runtime,
    )

    assert result.status == "ok"
    assert "No broker action" in result.output
    process = service.get_process(result.data["process"]["processId"])
    assert process is not None
    assert process.kind.value == "market_regime_monitor"
    assert process.execution_mode.value == "llm_assisted"
    assert process.schedule.type.value == "polling"
    assert process.schedule.poll_every_seconds == 300
    assert process.trigger["type"] == "market_regime_stress"
    assert process.trigger["proxySymbol"] == "QQQ"
    assert process.trigger["proxyLabel"] == "Nasdaq"
    assert process.trigger["conditions"] == [
        {"type": "percent_change_below", "value": -3.0},
        {
            "type": "drawdown_from_high_pct",
            "value": 5.0,
            "lookbackPeriod": "1mo",
            "lookbackInterval": "1d",
            "autoAdjust": False,
        },
    ]
    assert process.inputs["searchTimeRange"] == "day"
    assert process.action == {"type": "notify_only"}
    assert process.lifecycle.completion_policy.value == "complete_on_first_match"
    assert process.lifecycle.expires_at == datetime(2026, 5, 7, 23, 59, 59, tzinfo=UTC)
    assert process.notification == {"enabled": True}
    assert process.safety.broker_actions_allowed is False


def test_scheduler_market_regime_monitor_create_accepts_explicit_proxy_and_threshold(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    runtime = SchedulerManagementRuntime(service=service)

    result = scheduler_market_regime_monitor_create(
        title="Custom proxy stress monitor",
        description="Monitor an explicit proxy.",
        market_label=None,
        proxy_symbol="vixy",
        percent_change_below=-4,
        drawdown_from_high_pct=None,
        lookback_period="1mo",
        lookback_interval="1d",
        auto_adjust=False,
        poll_every_seconds=600,
        timezone=None,
        expires_at="2026-05-07T21:00:00Z",
        search_time_range="day",
        task_guidelines="Explain stress context.",
        notification_enabled=False,
        broker_actions_allowed=False,
        runtime=runtime,
    )

    assert result.status == "ok"
    process = service.get_process(result.data["process"]["processId"])
    assert process is not None
    assert process.trigger["proxySymbol"] == "VIXY"
    assert process.trigger["proxyLabel"] == "VIXY"
    assert process.trigger["conditions"] == [{"type": "percent_change_below", "value": -4.0}]
    assert process.notification == {"enabled": False}


def test_scheduler_market_regime_monitor_create_rejects_invalid_inputs(
    tmp_path: Path,
) -> None:
    runtime = SchedulerManagementRuntime(service=_service(tmp_path))
    base = {
        "title": None,
        "description": "",
        "market_label": "market",
        "proxy_symbol": None,
        "percent_change_below": -3,
        "drawdown_from_high_pct": None,
        "lookback_period": "1mo",
        "lookback_interval": "1d",
        "auto_adjust": False,
        "poll_every_seconds": None,
        "timezone": None,
        "expires_at": None,
        "search_time_range": "day",
        "task_guidelines": "",
        "notification_enabled": True,
        "broker_actions_allowed": False,
        "runtime": runtime,
    }

    missing_target = scheduler_market_regime_monitor_create(
        **{**base, "market_label": None, "proxy_symbol": None}
    )
    unsupported_label = scheduler_market_regime_monitor_create(
        **{**base, "market_label": "crypto", "proxy_symbol": None}
    )
    invalid_percent = scheduler_market_regime_monitor_create(
        **{**base, "percent_change_below": 3}
    )
    invalid_drawdown = scheduler_market_regime_monitor_create(
        **{**base, "percent_change_below": None, "drawdown_from_high_pct": -5}
    )
    unsafe = scheduler_market_regime_monitor_create(
        **{**base, "broker_actions_allowed": True}
    )

    for result in (
        missing_target,
        unsupported_label,
        invalid_percent,
        invalid_drawdown,
        unsafe,
    ):
        assert result.status == "error"
        assert result.error is not None
        assert result.error.code == "invalid_market_regime_monitor_spec"


def test_scheduler_market_signal_capture_create_polling_applies_defaults(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    runtime = SchedulerManagementRuntime(service=service)

    result = scheduler_market_signal_capture_create(
        title=None,
        description="Scan semiconductors for durable signals.",
        query="semiconductor AI capex risks",
        symbols=["nvda"],
        sectors=["Semiconductors"],
        tags=["AI capex"],
        schedule_type="polling",
        poll_every_seconds=None,
        frequency=None,
        time=None,
        timezone=None,
        days=[],
        task_guidelines="Save only durable, future-useful market signals.",
        max_signals=3,
        search_time_range="day",
        community_time_range="week",
        market_period="1mo",
        disclosure_since_days=30,
        notification_enabled=True,
        broker_actions_allowed=False,
        runtime=runtime,
    )

    assert result.status == "ok"
    assert "advisory memory" in result.output
    process = service.get_process(result.data["process"]["processId"])
    assert process is not None
    assert process.kind.value == "market_signal_capture"
    assert process.execution_mode.value == "llm_assisted"
    assert process.schedule.type.value == "polling"
    assert process.schedule.poll_every_seconds == 3600
    assert process.trigger["type"] == "market_signal_capture"
    assert process.inputs["query"] == "semiconductor AI capex risks"
    assert process.inputs["symbols"] == ["NVDA"]
    assert process.inputs["sectors"] == ["semiconductors"]
    assert process.inputs["tags"] == ["ai_capex"]
    assert process.inputs["maxSignals"] == 3
    assert process.inputs["searchTimeRange"] == "day"
    assert process.inputs["communityTimeRange"] == "week"
    assert process.inputs["marketPeriod"] == "1mo"
    assert process.inputs["disclosureSinceDays"] == 30
    assert process.action == {"type": "notify_only"}
    assert process.lifecycle.completion_policy.value == "keep_running"
    assert process.notification == {"enabled": True}
    assert process.safety.broker_actions_allowed is False


def test_scheduler_market_signal_capture_create_recurring_applies_schedule(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    runtime = SchedulerManagementRuntime(service=service, default_timezone="Europe/Rome")

    result = scheduler_market_signal_capture_create(
        title="Daily bank signal capture",
        description="Scan banks after close.",
        query=None,
        symbols=[],
        sectors=["banks"],
        tags=["rates"],
        schedule_type="recurring",
        poll_every_seconds=None,
        frequency="weekdays",
        time="22:00",
        timezone=None,
        days=[],
        task_guidelines="Focus on durable margin and credit signals.",
        max_signals=2,
        search_time_range="week",
        community_time_range="month",
        market_period="3mo",
        disclosure_since_days=45,
        notification_enabled=False,
        broker_actions_allowed=False,
        runtime=runtime,
    )

    assert result.status == "ok"
    process = service.get_process(result.data["process"]["processId"])
    assert process is not None
    assert process.schedule.type.value == "recurring"
    assert process.schedule.frequency == "weekdays"
    assert process.schedule.time == "22:00"
    assert process.schedule.timezone == "Europe/Rome"
    assert process.inputs["maxSignals"] == 2
    assert process.notification == {"enabled": False}


def test_scheduler_market_signal_capture_create_rejects_invalid_inputs(
    tmp_path: Path,
) -> None:
    runtime = SchedulerManagementRuntime(service=_service(tmp_path))
    base = {
        "title": None,
        "description": "",
        "query": "rates and banks",
        "symbols": [],
        "sectors": ["banks"],
        "tags": [],
        "schedule_type": "polling",
        "poll_every_seconds": None,
        "frequency": None,
        "time": None,
        "timezone": None,
        "days": [],
        "task_guidelines": "",
        "max_signals": 3,
        "search_time_range": "day",
        "community_time_range": "week",
        "market_period": "1mo",
        "disclosure_since_days": 30,
        "notification_enabled": True,
        "broker_actions_allowed": False,
        "runtime": runtime,
    }

    missing_scope = scheduler_market_signal_capture_create(
        **{**base, "query": None, "symbols": [], "sectors": [], "tags": []}
    )
    unsupported_schedule = scheduler_market_signal_capture_create(
        **{**base, "schedule_type": "one_shot"}
    )
    polling_too_fast = scheduler_market_signal_capture_create(
        **{**base, "poll_every_seconds": 300}
    )
    invalid_max = scheduler_market_signal_capture_create(**{**base, "max_signals": 4})
    missing_recurring_time = scheduler_market_signal_capture_create(
        **{**base, "schedule_type": "recurring", "frequency": "daily", "time": None}
    )
    unsafe = scheduler_market_signal_capture_create(
        **{**base, "broker_actions_allowed": True}
    )

    for result in (
        missing_scope,
        unsupported_schedule,
        polling_too_fast,
        invalid_max,
        missing_recurring_time,
        unsafe,
    ):
        assert result.status == "error"
        assert result.error is not None
        assert result.error.code == "invalid_market_signal_capture_spec"


def test_scheduler_trade_setup_monitor_create_defaults_to_notify_only(
    tmp_path: Path,
) -> None:
    runtime = SchedulerManagementRuntime(service=_service(tmp_path))

    result = scheduler_trade_setup_monitor_create(
        title=None,
        description="Evaluate a setup after the threshold.",
        symbol="tsla",
        trigger_type="below_price",
        value=180,
        lookback_period="1mo",
        lookback_interval="1d",
        auto_adjust=False,
        proposal_creation_allowed=False,
        allowed_symbols=[],
        allowed_sides=[],
        allowed_order_types=[],
        max_notional_amount=None,
        notional_currency=None,
        max_quantity=None,
        allow_extended_hours=False,
        approval_chat_id=None,
        approval_user_id=None,
        poll_every_seconds=None,
        timezone=None,
        expires_at=None,
        task_guidelines="Assess setup quality before proposing anything.",
        notification_enabled=True,
        broker_actions_allowed=False,
        runtime=runtime,
    )

    assert result.status == "ok"
    process = result.data["process"]
    assert process["kind"] == "trade_setup_monitor"
    assert process["executionMode"] == "llm_assisted"
    assert process["action"] == {
        "type": "notify_or_propose",
        "proposalCreationAllowed": False,
    }
    assert process["schedule"]["pollEverySeconds"] == 300
    assert process["safety"]["brokerActionsAllowed"] is False
    assert "Telegram button approval" in result.output


def test_scheduler_trade_setup_monitor_create_with_proposal_caps_and_chat_context(
    tmp_path: Path,
) -> None:
    runtime = SchedulerManagementRuntime(
        service=_service(tmp_path),
        chat_id="98765",
        user_id=321,
    )

    result = scheduler_trade_setup_monitor_create(
        title="TSLA guarded setup",
        description="Evaluate after threshold.",
        symbol="TSLA",
        trigger_type="below_price",
        value=180,
        lookback_period="1mo",
        lookback_interval="1d",
        auto_adjust=False,
        proposal_creation_allowed=True,
        allowed_symbols=[],
        allowed_sides=["buy"],
        allowed_order_types=["market", "limit"],
        max_notional_amount=1000,
        notional_currency="usd",
        max_quantity=None,
        allow_extended_hours=False,
        approval_chat_id=None,
        approval_user_id=None,
        poll_every_seconds=600,
        timezone="UTC",
        expires_at=None,
        task_guidelines="Only propose if risk/reward is attractive.",
        notification_enabled=True,
        broker_actions_allowed=False,
        runtime=runtime,
    )

    assert result.status == "ok"
    action = result.data["process"]["action"]
    assert action["proposalCreationAllowed"] is True
    assert action["orderPolicy"]["allowedSymbols"] == ["TSLA"]
    assert action["orderPolicy"]["allowedSides"] == ["BUY"]
    assert action["orderPolicy"]["allowedOrderTypes"] == ["MARKET", "LIMIT"]
    assert action["orderPolicy"]["maxNotionalAmount"] == "1000"
    assert action["orderPolicy"]["notionalCurrency"] == "USD"
    assert action["approval"] == {"chatId": 98765, "userId": 321}


def test_scheduler_trade_setup_monitor_create_rejects_missing_caps_or_unsafe_policy(
    tmp_path: Path,
) -> None:
    runtime = SchedulerManagementRuntime(service=_service(tmp_path))
    base = {
        "title": None,
        "description": "",
        "symbol": "TSLA",
        "trigger_type": "below_price",
        "value": 180,
        "lookback_period": "1mo",
        "lookback_interval": "1d",
        "auto_adjust": False,
        "proposal_creation_allowed": True,
        "allowed_symbols": ["TSLA"],
        "allowed_sides": ["BUY"],
        "allowed_order_types": ["MARKET"],
        "max_notional_amount": None,
        "notional_currency": None,
        "max_quantity": None,
        "allow_extended_hours": False,
        "approval_chat_id": 123,
        "approval_user_id": None,
        "poll_every_seconds": None,
        "timezone": None,
        "expires_at": None,
        "task_guidelines": "",
        "notification_enabled": True,
        "broker_actions_allowed": False,
        "runtime": runtime,
    }

    missing_cap = scheduler_trade_setup_monitor_create(**base)
    missing_value = scheduler_trade_setup_monitor_create(**{**base, "value": None})
    unsafe = scheduler_trade_setup_monitor_create(
        **{**base, "broker_actions_allowed": True}
    )
    unsupported_side = scheduler_trade_setup_monitor_create(
        **{**base, "allowed_sides": ["HOLD"], "max_quantity": 1}
    )
    missing_chat = scheduler_trade_setup_monitor_create(
        **{**base, "max_quantity": 1, "approval_chat_id": None}
    )

    for result in (missing_cap, missing_value, unsafe, unsupported_side, missing_chat):
        assert result.status == "error"
        assert result.error is not None
        assert result.error.code == "invalid_trade_setup_monitor_spec"


def test_scheduler_alpaca_news_monitor_create_builds_manual_monitor(tmp_path: Path) -> None:
    service = _service(tmp_path)
    runtime = SchedulerManagementRuntime(
        service=service,
        default_timezone="Europe/Rome",
        clock=lambda: datetime(2026, 5, 12, 9, 0, tzinfo=UTC),
        chat_id="5527868809",
        user_id=5527868809,
    )

    result = scheduler_alpaca_news_monitor_create(
        title=None,
        description="Monitor rare-earth names for material news.",
        symbols=["mp", "usar", "MP"],
        start_at=None,
        end_at=None,
        duration_minutes=90,
        timezone="Europe/Rome",
        task_guidelines="Focus on material company-specific catalysts only.",
        order_proposals_enabled=True,
        max_events_per_minute=12,
        notification_enabled=True,
        broker_actions_allowed=False,
        runtime=runtime,
    )

    assert result.status == "ok"
    process = service.get_process(result.data["process"]["processId"])
    assert process is not None
    assert process.kind.value == "alpaca_news_monitor"
    assert process.execution_mode.value == "llm_assisted"
    assert process.schedule.type.value == "manual"
    assert process.trigger == {"type": "alpaca_news_stream", "symbols": ["MP", "USAR"]}
    assert process.inputs["symbols"] == ["MP", "USAR"]
    assert process.inputs["timezone"] == "Europe/Rome"
    assert process.inputs["orderProposalsEnabled"] is True
    assert process.inputs["maxEventsPerMinute"] == 12
    assert process.inputs["chatId"] == "5527868809"
    assert process.inputs["userId"] == 5527868809
    assert process.notification == {"enabled": True, "chatId": "5527868809"}
    assert process.safety.broker_actions_allowed is False
    assert process.lifecycle.completion_policy.value == "complete_on_first_run"
    assert "Broker execution remains approval-button gated." in result.output


def test_scheduler_alpaca_news_monitor_create_rejects_missing_window_or_symbols(
    tmp_path: Path,
) -> None:
    runtime = SchedulerManagementRuntime(service=_service(tmp_path))
    base = {
        "title": None,
        "description": "",
        "symbols": ["MP"],
        "start_at": None,
        "end_at": None,
        "duration_minutes": 30,
        "timezone": None,
        "task_guidelines": "",
        "order_proposals_enabled": True,
        "max_events_per_minute": 10,
        "notification_enabled": True,
        "broker_actions_allowed": False,
        "runtime": runtime,
    }

    missing_symbols = scheduler_alpaca_news_monitor_create(**{**base, "symbols": []})
    missing_window = scheduler_alpaca_news_monitor_create(
        **{**base, "duration_minutes": None}
    )

    for result in (missing_symbols, missing_window):
        assert result.status == "error"
        assert result.error is not None
        assert result.error.code == "invalid_alpaca_news_monitor_spec"


def test_scheduler_agent_tool_mapping_is_constrained(tmp_path: Path) -> None:
    mapping = build_scheduler_agent_tool_mapping(_service(tmp_path))

    assert set(mapping) == {
        "scheduler_alpaca_news_monitor_create",
        "scheduler_instrument_monitor_create",
        "scheduler_company_event_analyst_create",
        "scheduler_market_regime_monitor_create",
        "scheduler_market_signal_capture_create",
        "scheduler_trade_setup_monitor_create",
        "scheduler_list_processes",
        "scheduler_pause_process",
        "scheduler_resume_process",
        "scheduler_archive_process",
    }
    assert "scheduler_create_process" not in SCHEDULER_AGENT_TOOLBOX.tools_by_name
    assert "scheduler_alpaca_news_monitor_create" in SCHEDULER_AGENT_TOOLBOX.tools_by_name
