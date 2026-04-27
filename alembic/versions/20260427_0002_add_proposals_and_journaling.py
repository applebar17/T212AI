"""Add proposals, approval events, and execution attempts.

Revision ID: 20260427_0002
Revises: 20260427_0001
Create Date: 2026-04-27 00:02:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260427_0002"
down_revision = "20260427_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proposals",
        sa.Column("proposal_id", sa.String(length=64), primary_key=True),
        sa.Column("chat_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("intent_kind", sa.String(length=64), nullable=False),
        sa.Column("action_kind", sa.String(length=32), nullable=False),
        sa.Column("original_user_message", sa.Text(), nullable=False),
        sa.Column("action_summary", sa.Text(), nullable=False),
        sa.Column("order_intent_json", sa.Text(), nullable=False),
        sa.Column("thesis", sa.Text(), nullable=False),
        sa.Column("risks_json", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "pending_action_id",
            sa.String(length=64),
            sa.ForeignKey("pending_actions.action_id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_index("ix_proposals_chat_id", "proposals", ["chat_id"], unique=False)
    op.create_index("ix_proposals_user_id", "proposals", ["user_id"], unique=False)
    op.create_index("ix_proposals_status", "proposals", ["status"], unique=False)
    op.create_index(
        "ix_proposals_pending_action_id",
        "proposals",
        ["pending_action_id"],
        unique=False,
    )

    op.create_table(
        "approval_events",
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "proposal_id",
            sa.String(length=64),
            sa.ForeignKey("proposals.proposal_id"),
            nullable=False,
        ),
        sa.Column(
            "pending_action_id",
            sa.String(length=64),
            sa.ForeignKey("pending_actions.action_id"),
            nullable=True,
        ),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("chat_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_approval_events_proposal_id",
        "approval_events",
        ["proposal_id"],
        unique=False,
    )
    op.create_index(
        "ix_approval_events_pending_action_id",
        "approval_events",
        ["pending_action_id"],
        unique=False,
    )
    op.create_index(
        "ix_approval_events_chat_id",
        "approval_events",
        ["chat_id"],
        unique=False,
    )

    op.create_table(
        "execution_attempts",
        sa.Column("attempt_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "proposal_id",
            sa.String(length=64),
            sa.ForeignKey("proposals.proposal_id"),
            nullable=False,
        ),
        sa.Column(
            "pending_action_id",
            sa.String(length=64),
            sa.ForeignKey("pending_actions.action_id"),
            nullable=True,
        ),
        sa.Column("broker_provider", sa.String(length=64), nullable=False),
        sa.Column("action_kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("broker_order_id", sa.Integer(), nullable=True),
        sa.Column("broker_response_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_execution_attempts_proposal_id",
        "execution_attempts",
        ["proposal_id"],
        unique=False,
    )
    op.create_index(
        "ix_execution_attempts_pending_action_id",
        "execution_attempts",
        ["pending_action_id"],
        unique=False,
    )
    op.create_index(
        "ix_execution_attempts_status",
        "execution_attempts",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_execution_attempts_status", table_name="execution_attempts")
    op.drop_index("ix_execution_attempts_pending_action_id", table_name="execution_attempts")
    op.drop_index("ix_execution_attempts_proposal_id", table_name="execution_attempts")
    op.drop_table("execution_attempts")

    op.drop_index("ix_approval_events_chat_id", table_name="approval_events")
    op.drop_index("ix_approval_events_pending_action_id", table_name="approval_events")
    op.drop_index("ix_approval_events_proposal_id", table_name="approval_events")
    op.drop_table("approval_events")

    op.drop_index("ix_proposals_pending_action_id", table_name="proposals")
    op.drop_index("ix_proposals_status", table_name="proposals")
    op.drop_index("ix_proposals_user_id", table_name="proposals")
    op.drop_index("ix_proposals_chat_id", table_name="proposals")
    op.drop_table("proposals")
