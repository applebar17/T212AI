"""Order reconciliation result models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from t212ai.pending_actions import PendingActionKind, PendingActionState


class ReconciliationOutcome(StrEnum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    FAILED = "failed"
    UNRESOLVED = "unresolved"


class ReconciledActionResult(BaseModel):
    action_id: str
    kind: PendingActionKind
    previous_state: PendingActionState
    current_state: PendingActionState
    outcome: ReconciliationOutcome
    remote_order_id: int | None = None
    remote_status: dict[str, Any] | None = None
    note: str


class ReconciliationRunResult(BaseModel):
    started_at: datetime
    finished_at: datetime
    scanned_actions: int = 0
    updated_actions: int = 0
    finalized_actions: int = 0
    pending_actions: int = 0
    failed_actions: int = 0
    unresolved_actions: int = 0
    actions: list[ReconciledActionResult] = Field(default_factory=list)

    def render_text(self) -> str:
        lines = [
            "Trading 212 reconciliation run finished.",
            f"Started at: {self.started_at.isoformat()}",
            f"Finished at: {self.finished_at.isoformat()}",
            (
                "Summary: "
                f"scanned={self.scanned_actions}, "
                f"updated={self.updated_actions}, "
                f"finalized={self.finalized_actions}, "
                f"pending={self.pending_actions}, "
                f"failed={self.failed_actions}, "
                f"unresolved={self.unresolved_actions}."
            ),
        ]
        if self.actions:
            lines.append("Actions:")
            for action in self.actions:
                suffix = (
                    f", remote_order_id={action.remote_order_id}"
                    if action.remote_order_id is not None
                    else ""
                )
                lines.append(
                    "- "
                    f"{action.action_id}: outcome={action.outcome.value}, "
                    f"state={action.previous_state.value}->{action.current_state.value}"
                    f"{suffix}. {action.note}"
                )
        return "\n".join(lines)
