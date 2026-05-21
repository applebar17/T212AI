"""Intent models for natural-language routing."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class IntentKind(StrEnum):
    PORTFOLIO_SUMMARY = "portfolio_summary"
    PORTFOLIO_ATTENTION_SCAN = "portfolio_attention_scan"
    ANALYZE_INSTRUMENT = "analyze_instrument"
    PROPOSE_TRADE = "propose_trade"
    PLACE_ORDER = "place_order"
    CANCEL_ORDER = "cancel_order"
    REVIEW_PENDING_ORDERS = "review_pending_orders"
    REBALANCE = "rebalance"
    CALCULATE = "calculate"
    MANAGE_GUIDELINES = "manage_guidelines"
    MANAGE_SCHEDULED_PROCESSES = "manage_scheduled_processes"
    DEBUG_LOGS = "debug_logs"
    SOCIAL_RESEARCH = "social_research"
    HELP = "help"
    UNKNOWN = "unknown"


class AgentIntent(BaseModel):
    kind: IntentKind
    entities: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class StructuredIntentEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    value: str


class StructuredAgentIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: IntentKind
    entities: list[StructuredIntentEntity] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    def to_agent_intent(self) -> AgentIntent:
        entities: dict[str, str] = {}
        for item in self.entities:
            key = str(item.key).strip()
            if key:
                entities[key] = str(item.value)
        return AgentIntent(
            kind=self.kind,
            entities=entities,
            confidence=self.confidence,
        )
