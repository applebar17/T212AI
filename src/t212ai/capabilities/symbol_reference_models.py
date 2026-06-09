"""Provider-neutral symbol-reference models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SymbolReferenceSearchResult:
    query: str
    candidates: list[dict[str, Any]]
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SymbolIdentifierMappingResult:
    records: list[dict[str, Any]]
    total: int | None = None
    limit: int | None = None
    offset: int | None = None
    next_url: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
