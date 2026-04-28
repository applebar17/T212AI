"""Pending-action domain models for deterministic approval flows."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from t212ai.brokers.models import (
    BrokerCancelTargetSelector,
    BrokerOrderAction,
    BrokerOrderActionRequest,
)


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
    CANCELLED = "cancelled"
    RECONCILED = "reconciled"


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
    target_order_ref: str | None = None
    original_user_message: str
    approval_message_id: int | None = None
    expires_at: datetime
    created_at: datetime
    updated_at: datetime
    broker_result: dict[str, Any] | None = None
    error_message: str | None = None
    remote_status: dict[str, Any] | None = None
    last_reconciled_at: datetime | None = None

    @property
    def target_order_id(self) -> int | str | None:
        if self.target_order_ref is None:
            return None
        try:
            return int(self.target_order_ref)
        except (TypeError, ValueError):
            return self.target_order_ref


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


CancelTargetSelector = BrokerCancelTargetSelector
BrokerOrderActionRequestModel = BrokerOrderActionRequest
BrokerOrderActionEnum = BrokerOrderAction
Trading212OrderActionRequest = BrokerOrderActionRequest
Trading212OrderAction = BrokerOrderAction
