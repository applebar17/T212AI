"""Intent models for natural-language routing."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


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
    HELP = "help"
    UNKNOWN = "unknown"


class AgentIntent(BaseModel):
    kind: IntentKind
    entities: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
