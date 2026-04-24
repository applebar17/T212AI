"""Guideline memory models."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class GuidelineCategory(StrEnum):
    ORCHESTRATOR_RULE = "orchestrator_rule"
    AGENT_RULE = "agent_rule"
    SCHEDULED_RULE = "scheduled_rule"
    INVESTMENT_PREFERENCE = "investment_preference"


class GuidelineMutationAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    ARCHIVE = "archive"
    DELETE = "delete"
    LIST = "list"
    RENDER = "render"


class GuidelineMutationRequest(BaseModel):
    action: GuidelineMutationAction
    node_id: str | None = None
    category: GuidelineCategory | None = None
    title: str | None = None
    body: str | None = None
    priority: int | None = None
    tags: list[str] | None = None
    applies_to: list[str] | None = None
    source: str = "user"
    scopes: list[str] = Field(default_factory=list)
    categories: list[GuidelineCategory] = Field(default_factory=list)
    active_only: bool = True
    confirmed: bool = False
    reason: str | None = None
