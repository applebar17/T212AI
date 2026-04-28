"""Shared toolbox primitives.

Kept separate from the higher-level registry to avoid import cycles when
provider-specific tool modules want to define their own toolboxes while the
generic registry also imports those provider modules.
"""

from __future__ import annotations

from dataclasses import dataclass

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
