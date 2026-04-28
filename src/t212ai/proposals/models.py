"""Proposal lifecycle domain models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ProposalActionKind(StrEnum):
    SUBMIT_ORDER = "submit_order"


class ProposalStatus(StrEnum):
    CREATED = "created"
    PREPARATION_FAILED = "preparation_failed"
    AWAITING_APPROVAL = "awaiting_approval"
    REJECTED = "rejected"
    SUBMITTED = "submitted"
    RECONCILED = "reconciled"
    CANCELLED = "cancelled"
    EXECUTION_FAILED = "execution_failed"


class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class ApprovalSource(StrEnum):
    BUTTON = "button"
    TEXT = "text"


class ExecutionAttemptStatus(StrEnum):
    SUBMITTED = "submitted"
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    FAILED = "failed"


class Proposal(BaseModel):
    proposal_id: str
    chat_id: str
    user_id: int | None = None
    intent_kind: str
    action_kind: ProposalActionKind
    original_user_message: str
    action_summary: str
    order_intent: dict[str, Any]
    thesis: str
    risks: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    status: ProposalStatus
    pending_action_id: str | None = None
    created_at: datetime
    updated_at: datetime
    last_error: str | None = None


class ApprovalEvent(BaseModel):
    event_id: str
    proposal_id: str
    pending_action_id: str | None = None
    decision: ApprovalDecision
    source: ApprovalSource
    chat_id: str
    user_id: int | None = None
    created_at: datetime


class ExecutionAttempt(BaseModel):
    attempt_id: str
    proposal_id: str
    pending_action_id: str | None = None
    broker_provider: str
    action_kind: ProposalActionKind
    status: ExecutionAttemptStatus
    broker_order_ref: str | None = None
    broker_response: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: datetime
    remote_status: dict[str, Any] | None = None
    reconciled_at: datetime | None = None

    @property
    def broker_order_id(self) -> int | str | None:
        if self.broker_order_ref is None:
            return None
        try:
            return int(self.broker_order_ref)
        except (TypeError, ValueError):
            return self.broker_order_ref


class ProposalDetail(BaseModel):
    proposal: Proposal
    latest_approval_event: ApprovalEvent | None = None
    latest_execution_attempt: ExecutionAttempt | None = None
