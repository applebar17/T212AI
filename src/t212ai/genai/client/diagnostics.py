"""Prompt-shape diagnostics for GenAI logging.

This module intentionally records structure and fingerprints only; it does not
log raw prompts, message text, or tool payloads.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from t212ai.genai.tools import ToolBox


def _llm_prompt_diagnostics(
    params: dict[str, Any],
    *,
    toolbox: ToolBox | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    raw_messages = params.get("messages")
    messages = raw_messages if isinstance(raw_messages, list) else []
    role_counts: dict[str, int] = {}
    prompt_chars_total = 0
    prompt_system_chars = 0
    prompt_user_chars = 0
    prompt_assistant_chars = 0
    prompt_tool_chars = 0
    last_user_chars: int | None = None

    for message in messages:
        role = _message_role(message)
        role_counts[role] = role_counts.get(role, 0) + 1
        char_count = _text_char_count(_message_content(message))
        prompt_chars_total += char_count
        if role == "system":
            prompt_system_chars += char_count
        elif role == "user":
            prompt_user_chars += char_count
            last_user_chars = char_count
        elif role == "assistant":
            prompt_assistant_chars += char_count
        elif role == "tool":
            prompt_tool_chars += char_count

    tools = params.get("tools") or (toolbox.tools if toolbox else [])
    tool_names = _tool_names(tools)
    resolved_model = str(model or params.get("model") or "unknown")
    return {
        "message_count": len(messages),
        "message_role_counts": role_counts,
        "prompt_chars_total": prompt_chars_total,
        "prompt_system_chars": prompt_system_chars,
        "prompt_user_chars": prompt_user_chars,
        "prompt_assistant_chars": prompt_assistant_chars,
        "prompt_tool_chars": prompt_tool_chars,
        "last_user_chars": last_user_chars,
        "tool_count": len(tool_names),
        "tool_names": tool_names,
        "toolbox_name": toolbox.name if toolbox else None,
        "prompt_fingerprint": _prompt_fingerprint(
            model=resolved_model,
            messages=messages,
            tool_names=tool_names,
        ),
    }


def _message_role(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("role") or "unknown")
    return str(getattr(message, "role", "unknown") or "unknown")


def _message_content(message: Any) -> Any:
    if isinstance(message, dict):
        return message.get("content")
    return getattr(message, "content", None)


def _text_char_count(value: Any) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, dict):
        return sum(_text_char_count(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return sum(_text_char_count(item) for item in value)
    return 0


def _tool_names(tools: Any) -> list[str]:
    if not isinstance(tools, list):
        return []
    names: list[str] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function")
        if isinstance(function, dict) and function.get("name"):
            names.append(str(function["name"]))
    return sorted(names)


def _prompt_fingerprint(
    *,
    model: str,
    messages: list[Any],
    tool_names: list[str],
) -> str:
    payload = {
        "model": model,
        "messages": _json_safe(messages),
        "tool_names": tool_names,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        default=str,
    ).encode("utf-8", errors="replace")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump(exclude_none=True)
        except Exception:
            dumped = None
        if dumped is not None:
            return _json_safe(dumped)
    return str(value)
