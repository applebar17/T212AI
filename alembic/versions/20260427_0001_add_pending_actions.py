"""Add pending actions table.

Revision ID: 20260427_0001
Revises:
Create Date: 2026-04-27 00:01:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260427_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pending_actions",
        sa.Column("action_id", sa.String(length=64), primary_key=True),
        sa.Column("chat_id", sa.String(length=128), nullable=False, index=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False, index=True),
        sa.Column("broker_provider", sa.String(length=64), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(length=128), nullable=True),
        sa.Column("prepared_order_payload_json", sa.Text(), nullable=True),
        sa.Column("target_order_id", sa.BigInteger(), nullable=True),
        sa.Column("original_user_message", sa.Text(), nullable=False),
        sa.Column("approval_message_id", sa.BigInteger(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("broker_result_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_pending_actions_chat_id_state",
        "pending_actions",
        ["chat_id", "state"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_pending_actions_chat_id_state", table_name="pending_actions")
    op.drop_table("pending_actions")
