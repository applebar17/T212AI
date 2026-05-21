"""Scheduler service public support types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..models import ScheduledProcess


@dataclass(frozen=True, slots=True)
class ScheduledProcessClaim:
    process: ScheduledProcess
    lease_token: str
    worker_id: str
    leased_until: datetime


@dataclass(frozen=True, slots=True)
class SchedulerMaintenanceResult:
    matched_count: int = 0
    changed_count: int = 0
    process_ids: tuple[str, ...] = ()
    run_ids: tuple[str, ...] = ()
    event_count: int = 0
    run_count: int = 0
    dry_run: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
