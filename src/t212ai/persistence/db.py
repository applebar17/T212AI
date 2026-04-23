"""Database session setup placeholder."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class DatabaseSettings:
    url: str = "sqlite:///./data/t212ai.db"

