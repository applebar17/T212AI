"""Genericize broker order reference columns for pending actions and execution attempts.

Revision ID: 20260428_0004
Revises: 20260428_0003
Create Date: 2026-04-28 00:04:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260428_0004"
down_revision = "20260428_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("pending_actions") as batch_op:
        batch_op.add_column(sa.Column("target_order_ref", sa.String(length=128), nullable=True))
    op.execute(
        "UPDATE pending_actions SET target_order_ref = CAST(target_order_id AS TEXT) "
        "WHERE target_order_id IS NOT NULL"
    )
    with op.batch_alter_table("pending_actions") as batch_op:
        batch_op.drop_column("target_order_id")

    with op.batch_alter_table("execution_attempts") as batch_op:
        batch_op.add_column(sa.Column("broker_order_ref", sa.String(length=128), nullable=True))
    op.execute(
        "UPDATE execution_attempts SET broker_order_ref = CAST(broker_order_id AS TEXT) "
        "WHERE broker_order_id IS NOT NULL"
    )
    with op.batch_alter_table("execution_attempts") as batch_op:
        batch_op.drop_column("broker_order_id")


def downgrade() -> None:
    with op.batch_alter_table("pending_actions") as batch_op:
        batch_op.add_column(sa.Column("target_order_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE pending_actions SET target_order_id = CAST(target_order_ref AS INTEGER) "
        "WHERE target_order_ref IS NOT NULL"
    )
    with op.batch_alter_table("pending_actions") as batch_op:
        batch_op.drop_column("target_order_ref")

    with op.batch_alter_table("execution_attempts") as batch_op:
        batch_op.add_column(sa.Column("broker_order_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE execution_attempts SET broker_order_id = CAST(broker_order_ref AS INTEGER) "
        "WHERE broker_order_ref IS NOT NULL"
    )
    with op.batch_alter_table("execution_attempts") as batch_op:
        batch_op.drop_column("broker_order_ref")
