"""Proposal persistence and execution journaling service."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from typing import Any, Iterator
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, sessionmaker

from .models import (
    ApprovalDecision,
    ApprovalEvent,
    ApprovalSource,
    ExecutionAttempt,
    ExecutionAttemptStatus,
    Proposal,
    ProposalActionKind,
    ProposalDetail,
    ProposalStatus,
)
from .orm import ApprovalEventRow, ExecutionAttemptRow, ProposalRow


class _Unset:
    pass


_UNSET = _Unset()


class ProposalService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create_submit_order_proposal(
        self,
        *,
        chat_id: str,
        user_id: int | None,
        intent_kind: str,
        original_user_message: str,
        action_summary: str,
        order_intent: dict[str, Any],
        thesis: str,
        risks: list[str],
        confidence: float,
    ) -> Proposal:
        row = ProposalRow(
            proposal_id=_new_id("pr"),
            chat_id=str(chat_id),
            user_id=user_id,
            intent_kind=str(intent_kind),
            action_kind=ProposalActionKind.SUBMIT_ORDER.value,
            original_user_message=original_user_message,
            action_summary=action_summary,
            order_intent_json=json.dumps(order_intent, ensure_ascii=True, sort_keys=True),
            thesis=thesis,
            risks_json=json.dumps(risks, ensure_ascii=True),
            confidence=_bounded_confidence(confidence),
            status=ProposalStatus.CREATED.value,
        )
        with self._session_scope() as session:
            session.add(row)
            session.flush()
            return _proposal_model(row)

    def mark_preparation_failed(self, proposal_id: str, *, error: str) -> Proposal | None:
        return self._update_proposal(
            proposal_id,
            status=ProposalStatus.PREPARATION_FAILED,
            last_error=error,
        )

    def attach_pending_action(self, proposal_id: str, *, pending_action_id: str) -> Proposal | None:
        return self._update_proposal(
            proposal_id,
            status=ProposalStatus.AWAITING_APPROVAL,
            pending_action_id=pending_action_id,
            last_error=None,
        )

    def mark_rejected(self, proposal_id: str) -> Proposal | None:
        return self._update_proposal(
            proposal_id,
            status=ProposalStatus.REJECTED,
        )

    def mark_submitted(self, proposal_id: str) -> Proposal | None:
        return self._update_proposal(
            proposal_id,
            status=ProposalStatus.SUBMITTED,
            last_error=None,
        )

    def mark_reconciled(self, proposal_id: str) -> Proposal | None:
        return self._update_proposal(
            proposal_id,
            status=ProposalStatus.RECONCILED,
            last_error=None,
        )

    def mark_cancelled(self, proposal_id: str, *, reason: str | None = None) -> Proposal | None:
        return self._update_proposal(
            proposal_id,
            status=ProposalStatus.CANCELLED,
            last_error=reason,
        )

    def mark_execution_failed(self, proposal_id: str, *, error: str) -> Proposal | None:
        return self._update_proposal(
            proposal_id,
            status=ProposalStatus.EXECUTION_FAILED,
            last_error=error,
        )

    def get_proposal(self, proposal_id: str) -> ProposalDetail | None:
        with self._session_scope() as session:
            row = session.get(ProposalRow, str(proposal_id))
            if row is None:
                return None
            approval = self._latest_approval_event(session, proposal_id=row.proposal_id)
            execution = self._latest_execution_attempt(session, proposal_id=row.proposal_id)
            return ProposalDetail(
                proposal=_proposal_model(row),
                latest_approval_event=_approval_event_model(approval) if approval else None,
                latest_execution_attempt=_execution_attempt_model(execution) if execution else None,
            )

    def list_recent_proposals(
        self,
        *,
        chat_id: str,
        user_id: int | None = None,
        limit: int = 10,
    ) -> list[Proposal]:
        with self._session_scope() as session:
            query = select(ProposalRow).where(ProposalRow.chat_id == str(chat_id))
            if user_id is not None:
                query = query.where(
                    (ProposalRow.user_id == user_id) | (ProposalRow.user_id.is_(None))
                )
            query = query.order_by(desc(ProposalRow.created_at)).limit(max(1, int(limit)))
            return [_proposal_model(row) for row in session.scalars(query).all()]

    def get_by_pending_action_id(self, pending_action_id: str) -> Proposal | None:
        with self._session_scope() as session:
            row = session.scalar(
                select(ProposalRow).where(ProposalRow.pending_action_id == str(pending_action_id))
            )
            if row is None:
                return None
            return _proposal_model(row)

    def record_approval_event(
        self,
        *,
        proposal_id: str,
        pending_action_id: str | None,
        decision: ApprovalDecision,
        source: ApprovalSource,
        chat_id: str,
        user_id: int | None,
    ) -> ApprovalEvent:
        row = ApprovalEventRow(
            event_id=_new_id("ae"),
            proposal_id=str(proposal_id),
            pending_action_id=str(pending_action_id) if pending_action_id else None,
            decision=decision.value,
            source=source.value,
            chat_id=str(chat_id),
            user_id=user_id,
        )
        with self._session_scope() as session:
            session.add(row)
            session.flush()
            return _approval_event_model(row)

    def record_execution_attempt(
        self,
        *,
        proposal_id: str,
        pending_action_id: str | None,
        broker_provider: str,
        action_kind: ProposalActionKind,
        status: ExecutionAttemptStatus,
        broker_order_id: int | None = None,
        broker_response: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> ExecutionAttempt:
        row = ExecutionAttemptRow(
            attempt_id=_new_id("ea"),
            proposal_id=str(proposal_id),
            pending_action_id=str(pending_action_id) if pending_action_id else None,
            broker_provider=str(broker_provider),
            action_kind=action_kind.value,
            status=status.value,
            broker_order_id=broker_order_id,
            broker_response_json=(
                json.dumps(broker_response, ensure_ascii=True, sort_keys=True)
                if broker_response is not None
                else None
            ),
            error_message=error_message,
        )
        with self._session_scope() as session:
            session.add(row)
            session.flush()
            return _execution_attempt_model(row)

    def sync_execution_attempt(
        self,
        *,
        proposal_id: str,
        pending_action_id: str | None,
        broker_provider: str,
        action_kind: ProposalActionKind,
        status: ExecutionAttemptStatus,
        broker_order_id: int | None = None,
        broker_response: dict[str, Any] | None = None,
        remote_status: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> ExecutionAttempt:
        with self._session_scope() as session:
            row = session.scalar(
                select(ExecutionAttemptRow)
                .where(
                    ExecutionAttemptRow.proposal_id == str(proposal_id),
                    ExecutionAttemptRow.pending_action_id == (
                        str(pending_action_id) if pending_action_id else None
                    ),
                )
                .order_by(desc(ExecutionAttemptRow.created_at))
                .limit(1)
            )
            if row is None:
                row = ExecutionAttemptRow(
                    attempt_id=_new_id("ea"),
                    proposal_id=str(proposal_id),
                    pending_action_id=(
                        str(pending_action_id) if pending_action_id else None
                    ),
                    broker_provider=str(broker_provider),
                    action_kind=action_kind.value,
                    status=status.value,
                )
                session.add(row)
            row.broker_provider = str(broker_provider)
            row.action_kind = action_kind.value
            row.status = status.value
            if broker_order_id is not None:
                row.broker_order_id = broker_order_id
            if broker_response is not None:
                row.broker_response_json = json.dumps(
                    broker_response,
                    ensure_ascii=True,
                    sort_keys=True,
                )
            if remote_status is not None:
                row.remote_status_json = json.dumps(
                    remote_status,
                    ensure_ascii=True,
                    sort_keys=True,
                )
            row.error_message = error_message
            row.reconciled_at = _utc_now()
            session.flush()
            return _execution_attempt_model(row)

    def _update_proposal(
        self,
        proposal_id: str,
        *,
        status: ProposalStatus,
        pending_action_id: str | None = None,
        last_error: str | None | object = _UNSET,
    ) -> Proposal | None:
        with self._session_scope() as session:
            row = session.get(ProposalRow, str(proposal_id))
            if row is None:
                return None
            row.status = status.value
            if pending_action_id is not None:
                row.pending_action_id = str(pending_action_id)
            if last_error is not _UNSET:
                row.last_error = str(last_error) if last_error is not None else None
            row.updated_at = _utc_now()
            session.flush()
            return _proposal_model(row)

    def _latest_approval_event(
        self,
        session: Session,
        *,
        proposal_id: str,
    ) -> ApprovalEventRow | None:
        return session.scalar(
            select(ApprovalEventRow)
            .where(ApprovalEventRow.proposal_id == str(proposal_id))
            .order_by(desc(ApprovalEventRow.created_at))
            .limit(1)
        )

    def _latest_execution_attempt(
        self,
        session: Session,
        *,
        proposal_id: str,
    ) -> ExecutionAttemptRow | None:
        return session.scalar(
            select(ExecutionAttemptRow)
            .where(ExecutionAttemptRow.proposal_id == str(proposal_id))
            .order_by(desc(ExecutionAttemptRow.created_at))
            .limit(1)
        )

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


def _proposal_model(row: ProposalRow) -> Proposal:
    return Proposal(
        proposal_id=row.proposal_id,
        chat_id=row.chat_id,
        user_id=row.user_id,
        intent_kind=row.intent_kind,
        action_kind=ProposalActionKind(row.action_kind),
        original_user_message=row.original_user_message,
        action_summary=row.action_summary,
        order_intent=json.loads(row.order_intent_json),
        thesis=row.thesis,
        risks=list(json.loads(row.risks_json)),
        confidence=_bounded_confidence(row.confidence),
        status=ProposalStatus(row.status),
        pending_action_id=row.pending_action_id,
        created_at=_ensure_aware(row.created_at),
        updated_at=_ensure_aware(row.updated_at),
        last_error=row.last_error,
    )


def _approval_event_model(row: ApprovalEventRow) -> ApprovalEvent:
    return ApprovalEvent(
        event_id=row.event_id,
        proposal_id=row.proposal_id,
        pending_action_id=row.pending_action_id,
        decision=ApprovalDecision(row.decision),
        source=ApprovalSource(row.source),
        chat_id=row.chat_id,
        user_id=row.user_id,
        created_at=_ensure_aware(row.created_at),
    )


def _execution_attempt_model(row: ExecutionAttemptRow) -> ExecutionAttempt:
    return ExecutionAttempt(
        attempt_id=row.attempt_id,
        proposal_id=row.proposal_id,
        pending_action_id=row.pending_action_id,
        broker_provider=row.broker_provider,
        action_kind=ProposalActionKind(row.action_kind),
        status=ExecutionAttemptStatus(row.status),
        broker_order_id=row.broker_order_id,
        broker_response=(
            json.loads(row.broker_response_json) if row.broker_response_json else None
        ),
        error_message=row.error_message,
        created_at=_ensure_aware(row.created_at),
        remote_status=(
            json.loads(row.remote_status_json) if row.remote_status_json else None
        ),
        reconciled_at=(
            _ensure_aware(row.reconciled_at) if row.reconciled_at is not None else None
        ),
    )


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _bounded_confidence(value: float | int | None) -> float:
    if value is None:
        return 0.0
    try:
        resolved = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, resolved))


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
