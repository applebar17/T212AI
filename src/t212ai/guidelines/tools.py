"""Guideline memory tool definitions."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Any, Callable

from t212ai.genai.models import ToolError, ToolResult, ToolSpec
from t212ai.genai.tools.tools import ToolBox, build_tool_index
from t212ai.genai.tracing import (
    set_trace_metadata,
    traceable,
)

from .service import GuidelineMemoryService


@dataclass(slots=True)
class GuidelineToolRuntime:
    service: GuidelineMemoryService


GUIDELINE_LIST_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "guideline_list_nodes",
        "description": "List stored guideline nodes with optional filters.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "categories": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "default": None,
                },
                "scopes": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "default": None,
                },
                "active_only": {
                    "type": "boolean",
                    "default": True,
                },
            },
            "required": ["categories", "scopes", "active_only"],
            "additionalProperties": False,
        },
    },
}

GUIDELINE_RENDER_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "guideline_render_preview",
        "description": "Render the guideline memory as markdown for prompt injection preview.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "scopes": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "default": None,
                },
                "include_categories": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "default": None,
                },
                "active_only": {
                    "type": "boolean",
                    "default": True,
                },
            },
            "required": ["scopes", "include_categories", "active_only"],
            "additionalProperties": False,
        },
    },
}

GUIDELINE_CREATE_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "guideline_create_node",
        "description": "Create a new persistent guideline node.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "category": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "priority": {"type": "integer", "default": 0},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                },
                "applies_to": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                },
                "source": {"type": "string", "default": "user"},
            },
            "required": [
                "category",
                "title",
                "body",
                "priority",
                "tags",
                "applies_to",
                "source",
            ],
            "additionalProperties": False,
        },
    },
}

GUIDELINE_UPDATE_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "guideline_update_node",
        "description": "Update one persistent guideline node by id.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string"},
                "category": {"type": ["string", "null"], "default": None},
                "title": {"type": ["string", "null"], "default": None},
                "body": {"type": ["string", "null"], "default": None},
                "priority": {"type": ["integer", "null"], "default": None},
                "tags": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "default": None,
                },
                "applies_to": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "default": None,
                },
                "source": {"type": ["string", "null"], "default": None},
            },
            "required": [
                "node_id",
                "category",
                "title",
                "body",
                "priority",
                "tags",
                "applies_to",
                "source",
            ],
            "additionalProperties": False,
        },
    },
}

GUIDELINE_ARCHIVE_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "guideline_archive_node",
        "description": "Archive a stored guideline node by id.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string"},
                "source": {"type": "string", "default": "agent"},
            },
            "required": ["node_id", "source"],
            "additionalProperties": False,
        },
    },
}

GUIDELINE_DELETE_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "guideline_delete_node",
        "description": (
            "Permanently delete a stored guideline node by id. Use only when the user "
            "explicitly asked to delete permanently."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string"},
                "confirmed": {"type": "boolean"},
            },
            "required": ["node_id", "confirmed"],
            "additionalProperties": False,
        },
    },
}


def build_guideline_tool_mapping(
    runtime: GuidelineToolRuntime,
) -> dict[str, Callable[..., ToolResult]]:
    return {
        "guideline_list_nodes": partial(guideline_list_nodes, runtime=runtime),
        "guideline_render_preview": partial(guideline_render_preview, runtime=runtime),
        "guideline_create_node": partial(guideline_create_node, runtime=runtime),
        "guideline_update_node": partial(guideline_update_node, runtime=runtime),
        "guideline_archive_node": partial(guideline_archive_node, runtime=runtime),
        "guideline_delete_node": partial(guideline_delete_node, runtime=runtime),
    }


@traceable(
    name="guideline_list_nodes",
    run_type="tool"
)
def guideline_list_nodes(
    *,
    categories: list[str] | None,
    scopes: list[str] | None,
    active_only: bool,
    runtime: GuidelineToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider="guideline_memory", tool_name="guideline_list_nodes")
    try:
        nodes = runtime.service.list_nodes(
            categories=categories,
            scopes=scopes,
            active_only=active_only,
        )
    except Exception as exc:
        return _tool_exception(exc, operation="list_nodes")
    payload = [_node_payload(node) for node in nodes]
    lines = [f"Listed {len(nodes)} guideline node(s)."]
    if categories:
        lines.append(f"Categories filter: {', '.join(categories)}.")
    if scopes:
        lines.append(f"Scope filter: {', '.join(scopes)}.")
    if payload:
        lines.append("Nodes:")
        for item in payload[:10]:
            lines.append(
                "- "
                f"id={item['id']}, category={item['category']}, title={item['title']}, "
                f"status={item['status']}, applies_to={', '.join(item['applies_to']) or 'none'}."
            )
    return ToolResult(status="ok", output="\n".join(lines), data={"nodes": payload})


@traceable(
    name="guideline_render_preview",
    run_type="tool"
)
def guideline_render_preview(
    *,
    scopes: list[str] | None,
    include_categories: list[str] | None,
    active_only: bool,
    runtime: GuidelineToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider="guideline_memory", tool_name="guideline_render_preview")
    try:
        markdown = runtime.service.render_markdown(
            scopes=scopes,
            include_categories=include_categories,
            active_only=active_only,
        )
    except Exception as exc:
        return _tool_exception(exc, operation="render_preview")
    if not markdown:
        return ToolResult(
            status="ok",
            output="No guideline nodes matched the requested render preview.",
            data={"markdown": "", "scopes": scopes or [], "include_categories": include_categories or []},
        )
    return ToolResult(
        status="ok",
        output=f"Rendered guideline markdown preview for prompt injection.\n\n{markdown}",
        data={
            "markdown": markdown,
            "scopes": scopes or [],
            "include_categories": include_categories or [],
        },
    )


@traceable(
    name="guideline_create_node",
    run_type="tool"
)
def guideline_create_node(
    *,
    category: str,
    title: str,
    body: str,
    priority: int,
    tags: list[str],
    applies_to: list[str],
    source: str,
    runtime: GuidelineToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider="guideline_memory", tool_name="guideline_create_node")
    try:
        node = runtime.service.create_node(
            category=category,
            title=title,
            body=body,
            priority=priority,
            tags=tags,
            applies_to=applies_to,
            source=source,
        )
    except Exception as exc:
        return _tool_exception(exc, operation="create_node")
    return ToolResult(
        status="ok",
        output=f"Created guideline node {node.id} titled '{node.title}'.",
        data=_node_payload(node),
    )


@traceable(
    name="guideline_update_node",
    run_type="tool"
)
def guideline_update_node(
    *,
    node_id: str,
    category: str | None,
    title: str | None,
    body: str | None,
    priority: int | None,
    tags: list[str] | None,
    applies_to: list[str] | None,
    source: str | None,
    runtime: GuidelineToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider="guideline_memory", tool_name="guideline_update_node")
    try:
        node = runtime.service.update_node(
            node_id,
            category=category,
            title=title,
            body=body,
            priority=priority,
            tags=tags,
            applies_to=applies_to,
            source=source,
        )
    except Exception as exc:
        return _tool_exception(exc, operation="update_node")
    return ToolResult(
        status="ok",
        output=f"Updated guideline node {node.id} titled '{node.title}'.",
        data=_node_payload(node),
    )


@traceable(
    name="guideline_archive_node",
    run_type="tool"
)
def guideline_archive_node(
    *,
    node_id: str,
    source: str,
    runtime: GuidelineToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider="guideline_memory", tool_name="guideline_archive_node")
    try:
        node = runtime.service.archive_node(node_id, source=source)
    except Exception as exc:
        return _tool_exception(exc, operation="archive_node")
    return ToolResult(
        status="ok",
        output=f"Archived guideline node {node.id} titled '{node.title}'.",
        data=_node_payload(node),
    )


@traceable(
    name="guideline_delete_node",
    run_type="tool"
)
def guideline_delete_node(
    *,
    node_id: str,
    confirmed: bool,
    runtime: GuidelineToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider="guideline_memory", tool_name="guideline_delete_node")
    if not confirmed:
        return ToolResult(
            status="error",
            output="Guideline deletion requires explicit confirmation.",
            error=ToolError(
                message="Guideline deletion requires confirmed=true.",
                code="confirmation_required",
                hint="Use archive for normal removals. Delete only on explicit permanent-delete requests.",
                retryable=False,
            ),
        )
    try:
        node = runtime.service.delete_node(node_id)
    except Exception as exc:
        return _tool_exception(exc, operation="delete_node")
    return ToolResult(
        status="ok",
        output=f"Permanently deleted guideline node {node.id} titled '{node.title}'.",
        data=_node_payload(node),
    )


def _node_payload(node) -> dict[str, Any]:
    return node.model_dump(mode="json")


def _tool_exception(exc: Exception, *, operation: str) -> ToolResult:
    return ToolResult(
        status="error",
        output=(
            f"Guideline memory {operation} failed. Reason: {exc}. "
            "Verify the node id, category, scope, and whether the requested operation "
            "was explicit enough for the current tool."
        ),
        error=ToolError(
            message=str(exc),
            code="guideline_memory_error",
            type=exc.__class__.__name__,
            hint=(
                "Check whether the node exists, whether required fields were provided, "
                "and whether delete vs archive was chosen correctly."
            ),
            retryable=False,
        ),
    )


GUIDELINE_MEMORY_TOOLS = [
    GUIDELINE_LIST_TOOL,
    GUIDELINE_RENDER_TOOL,
    GUIDELINE_CREATE_TOOL,
    GUIDELINE_UPDATE_TOOL,
    GUIDELINE_ARCHIVE_TOOL,
    GUIDELINE_DELETE_TOOL,
]

GUIDELINE_MEMORY_TOOLBOX = ToolBox(
    name="guideline_memory",
    tools=GUIDELINE_MEMORY_TOOLS,
    tools_by_name=build_tool_index(GUIDELINE_MEMORY_TOOLS),
)
