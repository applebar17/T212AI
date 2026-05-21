"""Schemas and dependency bundle for the news ingestion judge."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from t212ai.capabilities.protocols import BrokerReadService
from t212ai.market_signals import MarketSignalService

from ..base import BaseAgent


class NewsJudgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relevant: bool
    user_visible: bool = Field(alias="userVisible")
    summary: str
    actions_taken: list[str] = Field(default_factory=list, alias="actionsTaken")
    outcome: str
    confidence: str = Field(pattern="^(low|medium|high)$")


@dataclass(slots=True)
class NewsJudgeDependencies:
    market_agent: BaseAgent | None = None
    order_agent: BaseAgent | None = None
    market_signal_service: MarketSignalService | None = None
    broker_read_service: BrokerReadService | None = None
