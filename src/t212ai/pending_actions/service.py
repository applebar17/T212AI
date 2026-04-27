"""Persistent pending-action service."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Iterator
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from t212ai.brokers.trading212.models import Order, OrderActionResult, PreparedOrder
from t212ai.brokers.trading212.protocols import Trading212AgentBrokerProtocol

from .models import (
    PendingAction,
    PendingActionDecisionResult,
    PendingActionDecisionStatus,
    PendingActionKind,
    PendingActionState,
)
from .orm import PendingActionRow


class PendingActionService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        broker_service: Trading212AgentBrokerProtocol | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.broker_service = broker_service

    def create_submit_action(
        self,
        *,
        chat_id: str,
        user_id: int | None,
        prepared_order: PreparedOrder,
        original_user_message: str,
        summary_text: str,
        expires_at: datetime,
        broker_provider: str = "trading212",
    ) -> PendingAction:
        action_id = _new_action_id()
        row = PendingActionRow(
            action_id=action_id,
            chat_id=str(chat_id),
            user_id=user_id,
            kind=PendingActionKind.SUBMIT_ORDER.value,
            state=PendingActionState.AWAITING_APPROVAL.value,
            broker_provider=broker_provider,
            summary_text=summary_text,
            fingerprint=prepared_order.order_fingerprint,
            prepared_order_payload_json=json.dumps(
                prepared_order.model_dump(mode="json", by_alias=True, exclude_none=True),
                ensure_ascii=True,
                sort_keys=True,
            ),
            target_order_id=None,
            original_user_message=original_user_message,
            expires_at=_ensure_aware(expires_at),
        )
        with self._session_scope() as session:
            session.add(row)
            session.flush()
            return _to_model(row)

    def create_cancel_action(
        self,
        *,
        chat_id: str,
        user_id: int | None,
        target_order: Order,
        original_user_message: str,
        summary_text: str,
        expires_at: datetime,
        broker_provider: str = "trading212",
    ) -> PendingAction:
        action_id = _new_action_id()
        row = PendingActionRow(
            action_id=action_id,
            chat_id=str(chat_id),
            user_id=user_id,
            kind=PendingActionKind.CANCEL_ORDER.value,
            state=PendingActionState.AWAITING_APPROVAL.value,
            broker_provider=broker_provider,
            summary_text=summary_text,
            fingerprint=_cancel_fingerprint(target_order),
            prepared_order_payload_json=None,
            target_order_id=target_order.id,
            original_user_message=original_user_message,
            expires_at=_ensure_aware(expires_at),
        )
        with self._session_scope() as session:
            session.add(row)
            session.flush()
            return _to_model(row)

    def get_action(self, action_id: str) -> PendingAction | None:
        with self._session_scope() as session:
            row = session.get(PendingActionRow, str(action_id))
            if row is None:
                return None
            self._expire_row_if_needed(row)
            session.flush()
            return _to_model(row)

    def attach_approval_message_id(self, action_id: str, message_id: int | None) -> PendingAction | None:
        if message_id is None:
            return self.get_action(action_id)
        with self._session_scope() as session:
            row = session.get(PendingActionRow, str(action_id))
            if row is None:
                return None
            row.approval_message_id = int(message_id)
            row.updated_at = _utc_now()
            session.flush()
            return _to_model(row)

    def get_awaiting_actions(
        self,
        *,
        chat_id: str,
        user_id: int | None = None,
    ) -> list[PendingAction]:
        with self._session_scope() as session:
            query = select(PendingActionRow).where(
                PendingActionRow.chat_id == str(chat_id),
                PendingActionRow.state == PendingActionState.AWAITING_APPROVAL.value,
            )
            if user_id is not None:
                query = query.where(
                    (PendingActionRow.user_id == user_id) | (PendingActionRow.user_id.is_(None))
                )
            rows = list(session.scalars(query).all())
            for row in rows:
                self._expire_row_if_needed(row)
            session.flush()
            return [
                _to_model(row)
                for row in rows
                if row.state == PendingActionState.AWAITING_APPROVAL.value
            ]

    def approve_and_execute(
        self,
        action_id: str,
        *,
        chat_id: str,
        user_id: int | None = None,
    ) -> PendingActionDecisionResult:
        with self._session_scope() as session:
            row = session.get(PendingActionRow, str(action_id))
            if row is None:
                return PendingActionDecisionResult(
                    status=PendingActionDecisionStatus.NOT_FOUND,
                    message="Pending action not found.",
                )
            unauthorized = self._authorization_error(row, chat_id=chat_id, user_id=user_id)
            if unauthorized is not None:
                return unauthorized
            if self._expire_row_if_needed(row):
                session.flush()
                action = _to_model(row)
                return PendingActionDecisionResult(
                    status=PendingActionDecisionStatus.EXPIRED,
                    message="This pending action expired and must be prepared again.",
                    action=action,
                    edit_text=_finalized_text(action, "Expired. This action must be prepared again."),
                )
            if row.state == PendingActionState.SUBMITTED.value:
                action = _to_model(row)
                return PendingActionDecisionResult(
                    status=PendingActionDecisionStatus.ALREADY_FINALIZED,
                    message="This pending action was already submitted.",
                    action=action,
                    edit_text=_finalized_text(action, "Approved and submitted."),
                )
            if row.state == PendingActionState.REJECTED.value:
                action = _to_model(row)
                return PendingActionDecisionResult(
                    status=PendingActionDecisionStatus.ALREADY_FINALIZED,
                    message="This pending action was already rejected.",
                    action=action,
                    edit_text=_finalized_text(action, "Rejected."),
                )
            if row.state == PendingActionState.EXPIRED.value:
                action = _to_model(row)
                return PendingActionDecisionResult(
                    status=PendingActionDecisionStatus.EXPIRED,
                    message="This pending action expired and must be prepared again.",
                    action=action,
                    edit_text=_finalized_text(action, "Expired. This action must be prepared again."),
                )
            if self.broker_service is None:
                row.state = PendingActionState.FAILED.value
                row.error_message = "Broker service is not configured."
                row.updated_at = _utc_now()
                session.flush()
                action = _to_model(row)
                return PendingActionDecisionResult(
                    status=PendingActionDecisionStatus.FAILED,
                    message="Broker service is not configured for execution.",
                    action=action,
                    edit_text=_finalized_text(action, "Execution failed: broker service unavailable."),
                )

            row.state = PendingActionState.APPROVED.value
            row.updated_at = _utc_now()
            try:
                broker_result = self._execute_row(row)
            except Exception as exc:
                row.state = PendingActionState.FAILED.value
                row.error_message = str(exc)
                row.updated_at = _utc_now()
                session.flush()
                action = _to_model(row)
                return PendingActionDecisionResult(
                    status=PendingActionDecisionStatus.FAILED,
                    message=f"Execution failed: {exc}",
                    action=action,
                    edit_text=_finalized_text(action, f"Execution failed: {exc}"),
                )

            row.state = PendingActionState.SUBMITTED.value
            row.broker_result_json = json.dumps(
                broker_result.model_dump(mode="json", by_alias=True, exclude_none=True),
                ensure_ascii=True,
                sort_keys=True,
            )
            row.updated_at = _utc_now()
            session.flush()
            action = _to_model(row)
            if action.kind == PendingActionKind.SUBMIT_ORDER:
                message = "The prepared order was approved and submitted to Trading 212."
                edit_suffix = "Approved and submitted."
            else:
                message = "The cancellation request was approved and sent to Trading 212."
                edit_suffix = "Approved and sent."
            return PendingActionDecisionResult(
                status=PendingActionDecisionStatus.SUBMITTED,
                message=message,
                action=action,
                edit_text=_finalized_text(action, edit_suffix),
            )

    def reject(
        self,
        action_id: str,
        *,
        chat_id: str,
        user_id: int | None = None,
    ) -> PendingActionDecisionResult:
        with self._session_scope() as session:
            row = session.get(PendingActionRow, str(action_id))
            if row is None:
                return PendingActionDecisionResult(
                    status=PendingActionDecisionStatus.NOT_FOUND,
                    message="Pending action not found.",
                )
            unauthorized = self._authorization_error(row, chat_id=chat_id, user_id=user_id)
            if unauthorized is not None:
                return unauthorized
            if self._expire_row_if_needed(row):
                session.flush()
                action = _to_model(row)
                return PendingActionDecisionResult(
                    status=PendingActionDecisionStatus.EXPIRED,
                    message="This pending action already expired.",
                    action=action,
                    edit_text=_finalized_text(action, "Expired. This action must be prepared again."),
                )
            if row.state == PendingActionState.REJECTED.value:
                action = _to_model(row)
                return PendingActionDecisionResult(
                    status=PendingActionDecisionStatus.ALREADY_FINALIZED,
                    message="This pending action was already rejected.",
                    action=action,
                    edit_text=_finalized_text(action, "Rejected."),
                )
            if row.state == PendingActionState.SUBMITTED.value:
                action = _to_model(row)
                return PendingActionDecisionResult(
                    status=PendingActionDecisionStatus.ALREADY_FINALIZED,
                    message="This pending action was already submitted.",
                    action=action,
                    edit_text=_finalized_text(action, "Approved and submitted."),
                )
            row.state = PendingActionState.REJECTED.value
            row.updated_at = _utc_now()
            session.flush()
            action = _to_model(row)
            return PendingActionDecisionResult(
                status=PendingActionDecisionStatus.REJECTED,
                message="The pending action was rejected and discarded.",
                action=action,
                edit_text=_finalized_text(action, "Rejected."),
            )

    def _execute_row(self, row: PendingActionRow) -> OrderActionResult:
        if row.kind == PendingActionKind.SUBMIT_ORDER.value:
            prepared = PreparedOrder.model_validate(json.loads(row.prepared_order_payload_json or "{}"))
            return self.broker_service.submit_prepared_order(prepared)  # type: ignore[union-attr]
        if row.target_order_id is None:
            raise RuntimeError("Cancellation target order id is missing.")
        return self.broker_service.cancel_order(int(row.target_order_id))  # type: ignore[union-attr]

    def _authorization_error(
        self,
        row: PendingActionRow,
        *,
        chat_id: str,
        user_id: int | None,
    ) -> PendingActionDecisionResult | None:
        if row.chat_id != str(chat_id):
            return PendingActionDecisionResult(
                status=PendingActionDecisionStatus.UNAUTHORIZED,
                message="This pending action does not belong to this chat.",
            )
        if row.user_id is not None and user_id is None:
            return PendingActionDecisionResult(
                status=PendingActionDecisionStatus.UNAUTHORIZED,
                message="This pending action belongs to a specific Telegram user.",
            )
        if row.user_id is not None and user_id is not None and row.user_id != int(user_id):
            return PendingActionDecisionResult(
                status=PendingActionDecisionStatus.UNAUTHORIZED,
                message="This pending action belongs to another Telegram user.",
            )
        return None

    def _expire_row_if_needed(self, row: PendingActionRow) -> bool:
        if (
            row.state == PendingActionState.AWAITING_APPROVAL.value
            and _ensure_aware(row.expires_at) <= _utc_now()
        ):
            row.state = PendingActionState.EXPIRED.value
            row.updated_at = _utc_now()
            return True
        return False

    @contextmanager
    def _session_scope(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def approval_ttl_minutes(*, kind: PendingActionKind, order_type: str | None = None) -> int:
    if kind == PendingActionKind.CANCEL_ORDER:
        return 60
    if str(order_type or "").upper() == "MARKET":
        return 10
    return 60


def approval_expiry(*, kind: PendingActionKind, order_type: str | None = None) -> datetime:
    return _utc_now() + timedelta(minutes=approval_ttl_minutes(kind=kind, order_type=order_type))


def _to_model(row: PendingActionRow) -> PendingAction:
    prepared_payload = None
    if row.prepared_order_payload_json:
        prepared_payload = json.loads(row.prepared_order_payload_json)
    broker_result = None
    if row.broker_result_json:
        broker_result = json.loads(row.broker_result_json)
    return PendingAction(
        action_id=row.action_id,
        chat_id=row.chat_id,
        user_id=row.user_id,
        kind=PendingActionKind(row.kind),
        state=PendingActionState(row.state),
        broker_provider=row.broker_provider,
        summary_text=row.summary_text,
        fingerprint=row.fingerprint,
        prepared_order_payload=prepared_payload,
        target_order_id=row.target_order_id,
        original_user_message=row.original_user_message,
        approval_message_id=row.approval_message_id,
        expires_at=_ensure_aware(row.expires_at),
        created_at=_ensure_aware(row.created_at),
        updated_at=_ensure_aware(row.updated_at),
        broker_result=broker_result,
        error_message=row.error_message,
    )


def _finalized_text(action: PendingAction, suffix: str) -> str:
    return f"{action.summary_text}\n\nStatus: {suffix}"


def _new_action_id() -> str:
    return f"pa_{uuid4().hex[:12]}"


def _cancel_fingerprint(order: Order) -> str:
    payload = f"{order.id}:{order.ticker}:{order.created_at}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
