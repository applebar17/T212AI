"""SQLAlchemy rows for scheduled processes."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from t212ai.persistence.database import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ScheduledProcessRow(Base):
    __tablename__ = "scheduled_processes"

    process_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    execution_mode: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    schedule_json: Mapped[str] = mapped_column(Text)
    trigger_json: Mapped[str] = mapped_column(Text)
    inputs_json: Mapped[str] = mapped_column(Text)
    llm_scope_json: Mapped[str] = mapped_column(Text)
    action_json: Mapped[str] = mapped_column(Text)
    notification_json: Mapped[str] = mapped_column(Text)
    lifecycle_json: Mapped[str] = mapped_column(Text)
    safety_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)


class ScheduledProcessRunRow(Base):
    __tablename__ = "scheduled_process_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    process_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    matched: Mapped[int] = mapped_column(Integer, default=0)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text)


class ScheduledProcessLockRow(Base):
    __tablename__ = "scheduled_process_locks"

    process_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    lease_token: Mapped[str] = mapped_column(String(64), index=True)
    worker_id: Mapped[str] = mapped_column(String(128), index=True)
    leased_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class ScheduledProcessEventRow(Base):
    __tablename__ = "scheduled_process_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    process_id: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    message: Mapped[str] = mapped_column(Text)
    details_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
