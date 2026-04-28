"""Persistent pending-action service."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Iterator
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from t212ai.brokers.models import (
    BrokerOrder,
    BrokerOrderActionResult,
    PreparedBrokerOrder,
)
from t212ai.capabilities.protocols import BrokerExecutionService

from .models import (
    PendingAction,
    PendingActionDecisionResult,
    PendingActionDecisionStatus,
    PendingActionKind,
    PendingActionState,
)
from .orm import PendingActionRow


class _Unset:
    pass


_UNSET = _Unset()


class PendingActionService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        broker_service: BrokerExecutionService | None = None,
        broker_services_by_provider: dict[str, BrokerExecutionService] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.broker_service = broker_service
        self.broker_services_by_provider = dict(broker_services_by_provider or {})

    def create_submit_action(
        self,
        *,
        chat_id: str,
        user_id: int | None,
        prepared_order: PreparedBrokerOrder,
        original_user_message: str,
        summary_text: str,
        expires_at: datetime,
        broker_provider: str | None = None,
    ) -> PendingAction:
        normalized_prepared_order = _coerce_prepared_order(prepared_order)
        resolved_provider = (
            str(broker_provider or getattr(normalized_prepared_order, "broker_provider", "") or "").strip()
            or "unknown"
        )
        action_id = _new_action_id()
        row = PendingActionRow(
            action_id=action_id,
            chat_id=str(chat_id),
            user_id=user_id,
            kind=PendingActionKind.SUBMIT_ORDER.value,
            state=PendingActionState.AWAITING_APPROVAL.value,
            broker_provider=resolved_provider,
            summary_text=summary_text,
            fingerprint=normalized_prepared_order.order_fingerprint,
            prepared_order_payload_json=json.dumps(
                normalized_prepared_order.model_dump(mode="json", by_alias=True, exclude_none=True),
                ensure_ascii=True,
                sort_keys=True,
            ),
            target_order_ref=None,
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
        target_order: BrokerOrder,
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
            target_order_ref=(str(target_order.id) if target_order.id is not None else None),
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

    def list_actions_for_reconciliation(
        self,
        *,
        limit: int = 100,
        broker_provider: str | None = None,
    ) -> list[PendingAction]:
        with self._session_scope() as session:
            query = select(PendingActionRow).where(
                PendingActionRow.state == PendingActionState.SUBMITTED.value
            )
            if broker_provider:
                query = query.where(
                    PendingActionRow.broker_provider == str(broker_provider).strip().lower()
                )
            query = query.order_by(PendingActionRow.updated_at.asc()).limit(max(1, int(limit)))
            rows = list(session.scalars(query).all())
            return [_to_model(row) for row in rows]

    def apply_reconciliation(
        self,
        action_id: str,
        *,
        state: PendingActionState | None = None,
        remote_status: dict[str, object] | None = None,
        error_message: str | None | object = _UNSET,
    ) -> PendingAction | None:
        with self._session_scope() as session:
            row = session.get(PendingActionRow, str(action_id))
            if row is None:
                return None
            if state is not None:
                row.state = state.value
            if remote_status is not None:
                row.remote_status_json = json.dumps(
                    remote_status,
                    ensure_ascii=True,
                    sort_keys=True,
                )
            if error_message is not _UNSET:
                row.error_message = str(error_message) if error_message is not None else None
            row.last_reconciled_at = _utc_now()
            row.updated_at = _utc_now()
            session.flush()
            return _to_model(row)

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
            broker_service = self._resolve_broker_service(row.broker_provider)
            if broker_service is None:
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
                broker_result = self._execute_row(row, broker_service=broker_service)
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
            broker_name = _display_broker_name(action.broker_provider)
            if action.kind == PendingActionKind.SUBMIT_ORDER:
                message = f"The prepared order was approved and submitted to {broker_name}."
                edit_suffix = "Approved and submitted."
            else:
                message = f"The cancellation request was approved and sent to {broker_name}."
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

    def _execute_row(
        self,
        row: PendingActionRow,
        *,
        broker_service: BrokerExecutionService,
    ) -> BrokerOrderActionResult:
        if row.kind == PendingActionKind.SUBMIT_ORDER.value:
            prepared = PreparedBrokerOrder.model_validate(
                json.loads(row.prepared_order_payload_json or "{}")
            )
            return broker_service.submit_prepared_order(prepared)
        if row.target_order_ref is None:
            raise RuntimeError("Cancellation target order reference is missing.")
        return broker_service.cancel_order(str(row.target_order_ref))

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

    def _resolve_broker_service(self, broker_provider: str) -> BrokerExecutionService | None:
        provider_key = str(broker_provider or "").strip().lower()
        if provider_key and provider_key in self.broker_services_by_provider:
            return self.broker_services_by_provider[provider_key]
        return self.broker_service

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
    remote_status = None
    if row.remote_status_json:
        remote_status = json.loads(row.remote_status_json)
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
        target_order_ref=(
            str(row.target_order_ref) if row.target_order_ref is not None else None
        ),
        original_user_message=row.original_user_message,
        approval_message_id=row.approval_message_id,
        expires_at=_ensure_aware(row.expires_at),
        created_at=_ensure_aware(row.created_at),
        updated_at=_ensure_aware(row.updated_at),
        broker_result=broker_result,
        error_message=row.error_message,
        remote_status=remote_status,
        last_reconciled_at=(
            _ensure_aware(row.last_reconciled_at)
            if row.last_reconciled_at is not None
            else None
        ),
    )


def _finalized_text(action: PendingAction, suffix: str) -> str:
    return f"{action.summary_text}\n\nStatus: {suffix}"


def _new_action_id() -> str:
    return f"pa_{uuid4().hex[:12]}"


def _cancel_fingerprint(order: BrokerOrder) -> str:
    payload = f"{order.id}:{order.ticker}:{order.created_at}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _coerce_prepared_order(prepared_order: PreparedBrokerOrder | Any) -> PreparedBrokerOrder:
    if isinstance(prepared_order, PreparedBrokerOrder):
        return prepared_order
    payload = prepared_order.request_payload or {}
    return PreparedBrokerOrder(
        broker_provider="trading212",
        order_type=str(prepared_order.order_type.value),
        side=str(prepared_order.side.value),
        ticker=prepared_order.ticker,
        quantity=abs(prepared_order.signed_quantity),
        signed_quantity=prepared_order.signed_quantity,
        limit_price=payload.get("limitPrice"),
        stop_price=payload.get("stopPrice"),
        time_in_force=payload.get("timeValidity") or "DAY",
        extended_hours=bool(payload.get("extendedHours") or False),
        request_payload=payload,
        order_fingerprint=prepared_order.order_fingerprint,
        warnings=list(prepared_order.warnings),
    )


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _display_broker_name(provider: str) -> str:
    if str(provider).strip().lower() == "trading212":
        return "Trading 212"
    return str(provider or "broker").replace("_", " ").strip().title() or "Broker"
