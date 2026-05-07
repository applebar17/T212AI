"""Scheduler adapter registry builders."""

from __future__ import annotations

from typing import Any

from t212ai.capabilities import (
    BrokerReadService,
    DisclosureService,
    MarketDataService,
    SearchService,
)
from t212ai.market_signals import MarketSignalService

from .company_event_analyst import CompanyEventAnalystAdapter
from .instrument_monitor import InstrumentMonitorAdapter
from .models import ScheduledProcessKind
from .worker import ScheduledProcessAdapter


def build_scheduler_adapter_registry(
    *,
    company_agent: Any | None = None,
    market_agent: Any | None = None,
    market_data_service: MarketDataService | None = None,
    disclosure_service: DisclosureService | None = None,
    search_service: SearchService | None = None,
    market_signal_service: MarketSignalService | None = None,
    broker_read_service: BrokerReadService | None = None,
) -> dict[str, ScheduledProcessAdapter]:
    return {
        ScheduledProcessKind.INSTRUMENT_MONITOR.value: InstrumentMonitorAdapter(
            market_data_service=market_data_service,
        ),
        ScheduledProcessKind.COMPANY_EVENT_ANALYST.value: CompanyEventAnalystAdapter(
            company_agent=company_agent,
            market_agent=market_agent,
            market_data_service=market_data_service,
            disclosure_service=disclosure_service,
            search_service=search_service,
            market_signal_service=market_signal_service,
            broker_read_service=broker_read_service,
        ),
    }
