"""SQLAlchemy rows for market signal memory."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from t212ai.persistence.database import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MarketSignalRow(Base):
    __tablename__ = "market_signals"

    signal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    symbols_json: Mapped[str] = mapped_column(Text)
    sectors_json: Mapped[str] = mapped_column(Text)
    tags_json: Mapped[str] = mapped_column(Text)
    signal_type: Mapped[str] = mapped_column(String(32), index=True)
    direction: Mapped[str] = mapped_column(String(32), index=True)
    impact_horizon: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    source_refs_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
