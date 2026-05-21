"""Runtime context for generic broker tools."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from t212ai.capabilities.protocols import BrokerExecutionService, BrokerReadService, MarketDataService
from t212ai.pending_actions import PendingActionService

from ..references import BrokerReferenceMap


@dataclass(slots=True)
class BrokerToolRuntime:
    broker_read_service: BrokerReadService | None = None
    broker_execution_service: BrokerExecutionService | None = None
    broker_provider: str = "broker"
    allow_state_changes: bool = False
    pending_action_service: PendingActionService | None = None
    market_data_service: MarketDataService | None = None
    chat_id: str | None = None
    user_id: int | None = None
    user_message: str | None = None
    reference_map: BrokerReferenceMap | None = None


@dataclass(frozen=True, slots=True)
class _SizingContext:
    notional_amount: Decimal
    notional_currency: str | None
    price: Decimal
    source: str
    quantity: Decimal
