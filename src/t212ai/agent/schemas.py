"""Shared structured-output schemas for agent flows."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    source: str
    summary: str
    timestamp: str | None = None
    url: str | None = None
    relevance: float = Field(default=0.0, ge=0.0, le=1.0)


class TradeProposal(BaseModel):
    proposal_id: str
    action: str
    ticker: str
    order_type: str
    thesis: str
    risks: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    requires_approval: bool = True

