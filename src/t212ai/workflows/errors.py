"""Workflow-layer error types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class WorkflowExecutionError(RuntimeError):
    """Structured workflow failure that agents can surface verbosely."""

    message: str
    code: str
    hint: str
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message,
            "code": self.code,
            "hint": self.hint,
            "details": self.details,
        }
