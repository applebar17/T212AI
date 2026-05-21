"""Runtime binding for scheduler management tools."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import partial
from typing import Callable

from t212ai.genai.models import ToolResult

from ..service import ScheduledProcessService
from .handlers import (
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
from .runtime import SchedulerManagementRuntime


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
    chat_id: str | None = None,
    user_id: int | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Callable[..., ToolResult]]:
    runtime = SchedulerManagementRuntime(
        service=service,
        default_timezone=default_timezone,
        default_poll_every_seconds=default_poll_every_seconds,
        clock=clock or (lambda: datetime.now(timezone.utc)),
        chat_id=chat_id,
        user_id=user_id,
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
        "scheduler_market_regime_monitor_create": partial(
            scheduler_market_regime_monitor_create,
            runtime=runtime,
        ),
        "scheduler_market_signal_capture_create": partial(
            scheduler_market_signal_capture_create,
            runtime=runtime,
        ),
        "scheduler_alpaca_news_monitor_create": partial(
            scheduler_alpaca_news_monitor_create,
            runtime=runtime,
        ),
        "scheduler_trade_setup_monitor_create": partial(
            scheduler_trade_setup_monitor_create,
            runtime=runtime,
        ),
        "scheduler_list_processes": partial(scheduler_list_processes, runtime=runtime),
        "scheduler_pause_process": partial(scheduler_pause_process, runtime=runtime),
        "scheduler_resume_process": partial(scheduler_resume_process, runtime=runtime),
        "scheduler_archive_process": partial(scheduler_archive_process, runtime=runtime),
    }
