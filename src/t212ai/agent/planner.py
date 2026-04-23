"""Action planning primitives for bounded tool use."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from .intents import AgentIntent


class TaskComplexity(StrEnum):
    EASY = "easy"
    COMPLEX = "complex"
    CRITICAL = "critical"
    REASONING = "reasoning"


class ActionStep(BaseModel):
    tool_name: str
    purpose: str
    depends_on: list[str] = Field(default_factory=list)


class ActionPlan(BaseModel):
    intent: AgentIntent
    steps: list[ActionStep] = Field(default_factory=list)
    requires_approval: bool = False


class ToolStep(BaseModel):
    tool_name: str
    purpose: str
    input_summary: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    risk_class: str = "read_only"


class AgentPlan(BaseModel):
    intent: AgentIntent
    summary: str
    required_context: list[str] = Field(default_factory=list)
    tool_steps: list[ToolStep] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    task_complexity: TaskComplexity = TaskComplexity.EASY
