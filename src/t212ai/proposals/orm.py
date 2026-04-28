"""SQLAlchemy models for proposals and execution journaling."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from t212ai.persistence.database import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProposalRow(Base):
    __tablename__ = "proposals"

    proposal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    intent_kind: Mapped[str] = mapped_column(String(64))
    action_kind: Mapped[str] = mapped_column(String(32))
    original_user_message: Mapped[str] = mapped_column(Text)
    action_summary: Mapped[str] = mapped_column(Text)
    order_intent_json: Mapped[str] = mapped_column(Text)
    thesis: Mapped[str] = mapped_column(Text)
    risks_json: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), index=True)
    pending_action_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("pending_actions.action_id"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ApprovalEventRow(Base):
    __tablename__ = "approval_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("proposals.proposal_id"),
        index=True,
    )
    pending_action_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("pending_actions.action_id"),
        nullable=True,
        index=True,
    )
    decision: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16))
    chat_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class ExecutionAttemptRow(Base):
    __tablename__ = "execution_attempts"

    attempt_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("proposals.proposal_id"),
        index=True,
    )
    pending_action_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("pending_actions.action_id"),
        nullable=True,
        index=True,
    )
    broker_provider: Mapped[str] = mapped_column(String(64))
    action_kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), index=True)
    broker_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    broker_response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    remote_status_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    reconciled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
