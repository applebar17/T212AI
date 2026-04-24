"""Persistent guideline memory service."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from t212ai.persistence.documents import (
    FileBackedStructuredDocumentStore,
    StructuredDocument,
    StructuredDocumentNode,
    StructuredDocumentStore,
    utc_now,
)

from .models import GuidelineCategory


GuidelineNode = StructuredDocumentNode


class GuidelineMemoryService:
    def __init__(self, store: StructuredDocumentStore) -> None:
        self.store = store

    @classmethod
    def from_path(cls, path: str | Path) -> "GuidelineMemoryService":
        return cls(
            FileBackedStructuredDocumentStore(
                path,
                document_factory=build_empty_guideline_document,
            )
        )

    def list_nodes(
        self,
        *,
        categories: list[str] | None = None,
        scopes: list[str] | None = None,
        active_only: bool = False,
    ) -> list[GuidelineNode]:
        document = self.store.load()
        filtered = [
            node
            for node in document.nodes
            if _matches_node(
                node,
                categories=categories,
                scopes=scopes,
                active_only=active_only,
            )
        ]
        return _sort_nodes(filtered)

    def get_node(self, node_id: str) -> GuidelineNode:
        document = self.store.load()
        for node in document.nodes:
            if node.id == str(node_id):
                return node
        raise ValueError(f"Guideline node '{node_id}' was not found.")

    def create_node(
        self,
        *,
        category: str,
        title: str,
        body: str,
        priority: int = 0,
        tags: list[str] | None = None,
        applies_to: list[str] | None = None,
        source: str = "user",
    ) -> GuidelineNode:
        resolved_category = _validate_category(category)
        now = utc_now()
        node = GuidelineNode(
            id=f"guideline_{uuid4().hex[:12]}",
            category=resolved_category,
            title=_required_text(title, "title"),
            body=_required_text(body, "body"),
            status="active",
            priority=int(priority),
            tags=_clean_list(tags),
            applies_to=_clean_list(applies_to),
            source=_validate_source(source),
            created_at=now,
            updated_at=now,
        )
        document = self.store.load()
        updated = document.model_copy(update={"nodes": [*document.nodes, node]})
        self.store.save(updated)
        return node

    def update_node(
        self,
        node_id: str,
        *,
        category: str | None = None,
        title: str | None = None,
        body: str | None = None,
        priority: int | None = None,
        tags: list[str] | None = None,
        applies_to: list[str] | None = None,
        source: str | None = None,
    ) -> GuidelineNode:
        updates: dict[str, object] = {"updated_at": utc_now()}
        if category is not None:
            updates["category"] = _validate_category(category)
        if title is not None:
            updates["title"] = _required_text(title, "title")
        if body is not None:
            updates["body"] = _required_text(body, "body")
        if priority is not None:
            updates["priority"] = int(priority)
        if tags is not None:
            updates["tags"] = _clean_list(tags)
        if applies_to is not None:
            updates["applies_to"] = _clean_list(applies_to)
        if source is not None:
            updates["source"] = _validate_source(source)
        if len(updates) == 1:
            raise ValueError("No changes were provided for the guideline update.")

        document = self.store.load()
        new_nodes: list[GuidelineNode] = []
        updated_node: GuidelineNode | None = None
        for node in document.nodes:
            if node.id != str(node_id):
                new_nodes.append(node)
                continue
            updated_node = node.model_copy(update=updates)
            new_nodes.append(updated_node)
        if updated_node is None:
            raise ValueError(f"Guideline node '{node_id}' was not found.")
        self.store.save(document.model_copy(update={"nodes": new_nodes}))
        return updated_node

    def archive_node(
        self,
        node_id: str,
        *,
        source: str = "agent",
    ) -> GuidelineNode:
        document = self.store.load()
        archived_node: GuidelineNode | None = None
        new_nodes: list[GuidelineNode] = []
        for node in document.nodes:
            if node.id != str(node_id):
                new_nodes.append(node)
                continue
            archived_node = node.model_copy(
                update={
                    "status": "archived",
                    "source": _validate_source(source),
                    "updated_at": utc_now(),
                }
            )
            new_nodes.append(archived_node)
        if archived_node is None:
            raise ValueError(f"Guideline node '{node_id}' was not found.")
        self.store.save(document.model_copy(update={"nodes": new_nodes}))
        return archived_node

    def delete_node(self, node_id: str) -> GuidelineNode:
        document = self.store.load()
        removed: GuidelineNode | None = None
        kept_nodes: list[GuidelineNode] = []
        for node in document.nodes:
            if node.id == str(node_id):
                removed = node
                continue
            kept_nodes.append(node)
        if removed is None:
            raise ValueError(f"Guideline node '{node_id}' was not found.")
        self.store.save(document.model_copy(update={"nodes": kept_nodes}))
        return removed

    def render_markdown(
        self,
        *,
        scopes: list[str] | None = None,
        include_categories: list[str] | None = None,
        active_only: bool = True,
    ) -> str:
        document = self.store.load()
        filtered = [
            node
            for node in document.nodes
            if _matches_render_filter(
                node,
                scopes=scopes,
                include_categories=include_categories,
                active_only=active_only,
            )
        ]
        nodes = _sort_nodes(filtered)
        if not nodes:
            return ""
        lines = ["# Persistent Guidelines", ""]
        for node in nodes:
            lines.extend(_render_node_markdown(node))
            lines.append("")
        return "\n".join(line for line in lines).strip()


def build_empty_guideline_document() -> StructuredDocument:
    return StructuredDocument(
        document_id="persistent_guidelines",
        kind="guideline_memory",
        version=1,
        nodes=[],
    )


def _matches_node(
    node: GuidelineNode,
    *,
    categories: list[str] | None,
    scopes: list[str] | None,
    active_only: bool,
) -> bool:
    category_values = {str(item) for item in categories or []}
    scope_values = {str(item) for item in scopes or []}
    if active_only and node.status != "active":
        return False
    if category_values and node.category not in category_values:
        return False
    if scope_values and not set(node.applies_to).intersection(scope_values):
        return False
    return True


def _matches_render_filter(
    node: GuidelineNode,
    *,
    scopes: list[str] | None,
    include_categories: list[str] | None,
    active_only: bool,
) -> bool:
    scope_values = {str(item) for item in scopes or []}
    category_values = {str(item) for item in include_categories or []}
    if active_only and node.status != "active":
        return False
    if not scope_values and not category_values:
        return True
    scope_match = bool(scope_values) and bool(set(node.applies_to).intersection(scope_values))
    category_match = bool(category_values) and node.category in category_values
    return scope_match or category_match


def _sort_nodes(nodes: list[GuidelineNode]) -> list[GuidelineNode]:
    return sorted(
        nodes,
        key=lambda node: (
            -int(node.priority),
            -_timestamp_value(node.updated_at),
            node.id,
        ),
    )


def _timestamp_value(value: datetime) -> float:
    return value.timestamp()


def _render_node_markdown(node: GuidelineNode) -> list[str]:
    lines = [f"## {node.title} (`{node.id}`)"]
    lines.append(f"- category: {node.category}")
    lines.append(f"- priority: {node.priority}")
    lines.append(f"- applies_to: {', '.join(node.applies_to) or 'none'}")
    lines.append(f"- tags: {', '.join(node.tags) or 'none'}")
    lines.append(f"- source: {node.source}")
    lines.append(f"- created_at: {node.created_at.isoformat()}")
    lines.append(f"- updated_at: {node.updated_at.isoformat()}")
    lines.append("")
    lines.append(node.body)
    return lines


def _validate_category(category: str) -> str:
    resolved = _required_text(category, "category")
    allowed = {item.value for item in GuidelineCategory}
    if resolved not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise ValueError(f"Unsupported guideline category. Allowed: {allowed_text}.")
    return resolved


def _validate_source(source: str) -> str:
    resolved = _required_text(source, "source")
    if resolved not in {"user", "agent", "system"}:
        raise ValueError("source must be one of: user, agent, system.")
    return resolved


def _required_text(value: str, field_name: str) -> str:
    resolved = str(value or "").strip()
    if not resolved:
        raise ValueError(f"{field_name} is required.")
    return resolved


def _clean_list(values: list[str] | None) -> list[str]:
    return [str(value).strip() for value in values or [] if str(value).strip()]
