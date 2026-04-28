"""Add reconciliation metadata to pending actions and execution attempts.

Revision ID: 20260428_0003
Revises: 20260427_0002
Create Date: 2026-04-28 00:03:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260428_0003"
down_revision = "20260427_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pending_actions",
        sa.Column("remote_status_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "pending_actions",
        sa.Column("last_reconciled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "execution_attempts",
        sa.Column("remote_status_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "execution_attempts",
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("execution_attempts", "reconciled_at")
    op.drop_column("execution_attempts", "remote_status_json")
    op.drop_column("pending_actions", "last_reconciled_at")
    op.drop_column("pending_actions", "remote_status_json")
