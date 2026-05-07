"""Market signal domain models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class MarketSignalModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class MarketSignalDirection(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class MarketSignalHorizon(StrEnum):
    INTRADAY = "intraday"
    SHORT_TERM = "short_term"
    MEDIUM_TERM = "medium_term"
    LONG_TERM = "long_term"
    UNKNOWN = "unknown"


class MarketSignalSource(StrEnum):
    USER = "user"
    AGENT = "agent"
    SCHEDULED_JOB = "scheduled_job"
    SEARCH = "search"
    SEC_EDGAR = "sec_edgar"
    REDDIT = "reddit"
    MARKET_DATA = "market_data"
    BROKER_CONTEXT = "broker_context"
    OTHER = "other"


class MarketSignalStatus(StrEnum):
    ACTIVE = "active"
    STALE = "stale"
    ARCHIVED = "archived"


class MarketSignalType(StrEnum):
    CATALYST = "catalyst"
    MACRO = "macro"
    EARNINGS = "earnings"
    SENTIMENT = "sentiment"
    TECHNICAL = "technical"
    VALUATION = "valuation"
    RISK = "risk"
    POSITIONING = "positioning"
    NEWS = "news"
    REGULATORY = "regulatory"
    PORTFOLIO = "portfolio"
    OTHER = "other"


class MarketSignal(MarketSignalModel):
    signal_id: str = Field(alias="signalId")
    title: str
    summary: str
    symbols: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    signal_type: MarketSignalType = Field(alias="signalType")
    direction: MarketSignalDirection
    impact_horizon: MarketSignalHorizon = Field(alias="impactHorizon")
    source: MarketSignalSource
    source_refs: list[str] = Field(default_factory=list, alias="sourceRefs")
    status: MarketSignalStatus
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    expires_at: datetime | None = Field(default=None, alias="expiresAt")


class MarketSignalSearchMatch(MarketSignalModel):
    signal: MarketSignal
    matched_fields: list[str] = Field(default_factory=list, alias="matchedFields")
