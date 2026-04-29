"""Shared structured-output schemas for agent flows."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .history import ChatHistoryWindow
from .intents import AgentIntent, IntentKind, StructuredIntentEntity
from .planner import AgentPlan


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


class AgentRequest(BaseModel):
    user_message: str
    chat_id: str | None = None
    trigger_type: str = "user"
    history: ChatHistoryWindow | None = None
    orchestrator_guidance: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class AgentCritique(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    summary: str
    missing_context: list[str] = Field(default_factory=list)
    safety_concerns: list[str] = Field(default_factory=list)
    suggested_fixes: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class OrchestratorDelegationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_brief: str
    expected_output: str
    intent_kind: IntentKind
    entities: list[StructuredIntentEntity] = Field(default_factory=list)

    def to_agent_intent(self) -> AgentIntent:
        entities: dict[str, str] = {}
        for item in self.entities:
            key = str(item.key).strip()
            if key:
                entities[key] = str(item.value)
        return AgentIntent(kind=self.intent_kind, entities=entities)


class AgentResponse(BaseModel):
    final_answer: str
    selected_agent: str
    plan: AgentPlan | None = None
    critique: AgentCritique | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    artifacts: dict[str, Any] = Field(default_factory=dict)
