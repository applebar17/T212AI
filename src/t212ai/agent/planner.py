"""Action planning primitives for bounded tool use."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .intents import AgentIntent


class ActionStep(BaseModel):
    tool_name: str
    purpose: str
    depends_on: list[str] = Field(default_factory=list)


class ActionPlan(BaseModel):
    intent: AgentIntent
    steps: list[ActionStep] = Field(default_factory=list)
    requires_approval: bool = False

