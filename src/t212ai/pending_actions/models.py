"""Pending-action domain models for deterministic approval flows."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PendingActionKind(StrEnum):
    SUBMIT_ORDER = "submit_order"
    CANCEL_ORDER = "cancel_order"


class PendingActionState(StrEnum):
    PREPARED = "prepared"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    SUBMITTED = "submitted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    FAILED = "failed"


class PendingAction(BaseModel):
    action_id: str
    chat_id: str
    user_id: int | None = None
    kind: PendingActionKind
    state: PendingActionState
    broker_provider: str
    summary_text: str
    fingerprint: str | None = None
    prepared_order_payload: dict[str, Any] | None = None
    target_order_id: int | None = None
    original_user_message: str
    approval_message_id: int | None = None
    expires_at: datetime
    created_at: datetime
    updated_at: datetime
    broker_result: dict[str, Any] | None = None
    error_message: str | None = None


class PendingActionDecisionStatus(StrEnum):
    SUBMITTED = "submitted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    FAILED = "failed"
    ALREADY_FINALIZED = "already_finalized"
    NOT_FOUND = "not_found"
    UNAUTHORIZED = "unauthorized"


class PendingActionDecisionResult(BaseModel):
    status: PendingActionDecisionStatus
    message: str
    action: PendingAction | None = None
    edit_text: str | None = None


class CancelTargetSelector(StrEnum):
    LATEST = "latest"
    OLDEST = "oldest"
    ONLY = "only"


class Trading212OrderAction(StrEnum):
    PREPARE_SUBMIT_ORDER = "prepare_submit_order"
    PREPARE_CANCEL_ORDER = "prepare_cancel_order"


class Trading212OrderActionRequest(BaseModel):
    action: Trading212OrderAction
    order_type: str | None = None
    side: str | None = None
    ticker: str | None = None
    quantity: str | int | float | None = None
    limit_price: str | int | float | None = None
    stop_price: str | int | float | None = None
    time_validity: str = "DAY"
    extended_hours: bool = False
    target_order_id: int | None = None
    cancel_selector: CancelTargetSelector | None = None
    reason: str | None = None
    thesis: str | None = None
    risks: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
