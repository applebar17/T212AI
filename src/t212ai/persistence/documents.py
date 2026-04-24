"""Generic file-backed structured document primitives."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StructuredDocumentNode(BaseModel):
    id: str
    category: str
    title: str
    body: str
    status: str = "active"
    priority: int = 0
    tags: list[str] = Field(default_factory=list)
    applies_to: list[str] = Field(default_factory=list)
    source: str = "user"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class StructuredDocument(BaseModel):
    document_id: str
    kind: str
    version: int = 1
    updated_at: datetime = Field(default_factory=utc_now)
    nodes: list[StructuredDocumentNode] = Field(default_factory=list)


class StructuredDocumentStore(Protocol):
    def load(self) -> StructuredDocument: ...

    def save(self, document: StructuredDocument) -> StructuredDocument: ...


class FileBackedStructuredDocumentStore:
    def __init__(
        self,
        path: str | Path,
        *,
        document_factory: Callable[[], StructuredDocument],
    ) -> None:
        self.path = Path(path)
        self._document_factory = document_factory

    def load(self) -> StructuredDocument:
        if not self.path.exists():
            return self._document_factory()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return StructuredDocument.model_validate(payload)

    def save(self, document: StructuredDocument) -> StructuredDocument:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        updated_document = document.model_copy(update={"updated_at": utc_now()})
        payload = updated_document.model_dump(mode="json", exclude_none=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self.path)
        return updated_document
