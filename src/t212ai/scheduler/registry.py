"""Scheduler adapter registry builders."""

from __future__ import annotations

from typing import Any

from t212ai.capabilities import (
    BrokerExecutionService,
    BrokerReadService,
    CommunityResearchService,
    DisclosureService,
    MarketDataService,
    SearchService,
)
from t212ai.market_signals import MarketSignalService
from t212ai.pending_actions import PendingActionService
from t212ai.proposals import ProposalService

from .company_event_analyst import CompanyEventAnalystAdapter
from .instrument_monitor import InstrumentMonitorAdapter
from .market_signal_capture import MarketSignalCaptureAdapter
from .market_regime_monitor import MarketRegimeMonitorAdapter
from .models import ScheduledProcessKind
from .trade_setup_monitor import TradeSetupMonitorAdapter
from .worker import ScheduledProcessAdapter


def build_scheduler_adapter_registry(
    *,
    company_agent: Any | None = None,
    market_agent: Any | None = None,
    market_data_service: MarketDataService | None = None,
    community_research_service: CommunityResearchService | None = None,
    disclosure_service: DisclosureService | None = None,
    search_service: SearchService | None = None,
    market_signal_service: MarketSignalService | None = None,
    broker_read_service: BrokerReadService | None = None,
    broker_execution_service: BrokerExecutionService | None = None,
    pending_action_service: PendingActionService | None = None,
    proposal_service: ProposalService | None = None,
    broker_provider: str = "broker",
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
        ScheduledProcessKind.MARKET_REGIME_MONITOR.value: MarketRegimeMonitorAdapter(
            market_agent=market_agent,
            market_data_service=market_data_service,
            search_service=search_service,
        ),
        ScheduledProcessKind.MARKET_SIGNAL_CAPTURE.value: MarketSignalCaptureAdapter(
            market_agent=market_agent,
            market_signal_service=market_signal_service,
            search_service=search_service,
            community_research_service=community_research_service,
            disclosure_service=disclosure_service,
            market_data_service=market_data_service,
        ),
        ScheduledProcessKind.TRADE_SETUP_MONITOR.value: TradeSetupMonitorAdapter(
            market_agent=market_agent,
            market_data_service=market_data_service,
            broker_read_service=broker_read_service,
            broker_execution_service=broker_execution_service,
            pending_action_service=pending_action_service,
            proposal_service=proposal_service,
            market_signal_service=market_signal_service,
            broker_provider=broker_provider,
        ),
    }
