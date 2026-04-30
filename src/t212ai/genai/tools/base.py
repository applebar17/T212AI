"""Shared toolbox primitives.

Kept separate from the higher-level registry to avoid import cycles when
provider-specific tool modules want to define their own toolboxes while the
generic registry also imports those provider modules.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from ..models import ToolSpec


@dataclass(frozen=True)
class ToolBox:
    name: str
    tools: list[ToolSpec]
    tools_by_name: dict[str, ToolSpec]


def build_tool_index(tools: list[ToolSpec]) -> dict[str, ToolSpec]:
    index: dict[str, ToolSpec] = {}
    for tool in tools:
        fn = tool.get("function") or {}
        name = fn.get("name")
        if not name:
            raise ValueError("Tool definition missing function.name")
        if name in index:
            raise ValueError(f"Duplicate tool name: {name}")
        index[name] = tool
    return index


def render_tool_descriptions(toolbox: ToolBox | None) -> str:
    if toolbox is None or not toolbox.tools:
        return "No tools are available."
    rendered: list[str] = []
    for tool in toolbox.tools:
        function = tool.get("function") or {}
        name = str(function.get("name") or "").strip()
        description = str(function.get("description") or "").strip()
        parameters = function.get("parameters") or {}
        rendered.append(
            "\n".join(
                item
                for item in (
                    f"- {name}",
                    f"  description: {description}" if description else "",
                    f"  parameters: {_compact_parameters(parameters)}",
                )
                if item
            )
        )
    return "\n".join(rendered)


def _compact_parameters(parameters: Any) -> str:
    if not isinstance(parameters, dict):
        return "{}"
    required = parameters.get("required") or []
    properties = parameters.get("properties") or {}
    compact: dict[str, Any] = {"required": required, "properties": {}}
    if isinstance(properties, dict):
        for name, schema in properties.items():
            if not isinstance(schema, dict):
                continue
            compact["properties"][name] = {
                key: schema[key]
                for key in ("type", "enum", "description", "default")
                if key in schema
            }
    return json.dumps(compact, ensure_ascii=True, sort_keys=True)
