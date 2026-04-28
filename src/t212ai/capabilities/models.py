"""Capability-layer lightweight models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CapabilityBinding:
    capability: str
    selected_provider: str | None
    ready: bool
    implementation: Any | None = None
