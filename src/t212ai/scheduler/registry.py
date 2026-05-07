"""Scheduler adapter registry builders."""

from __future__ import annotations

from t212ai.capabilities import MarketDataService

from .instrument_monitor import InstrumentMonitorAdapter
from .models import ScheduledProcessKind
from .worker import ScheduledProcessAdapter


def build_scheduler_adapter_registry(
    *,
    market_data_service: MarketDataService | None = None,
) -> dict[str, ScheduledProcessAdapter]:
    return {
        ScheduledProcessKind.INSTRUMENT_MONITOR.value: InstrumentMonitorAdapter(
            market_data_service=market_data_service,
        )
    }
