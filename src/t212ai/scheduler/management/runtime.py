"""Runtime context for scheduler management tools."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from ..service import ScheduledProcessService


@dataclass(slots=True)
class SchedulerManagementRuntime:
    service: ScheduledProcessService | None = None
    default_timezone: str = "UTC"
    default_poll_every_seconds: int = 300
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    chat_id: str | None = None
    user_id: int | None = None
