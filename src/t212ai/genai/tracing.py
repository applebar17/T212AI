"""Optional LangSmith tracing helpers for GenAI runs."""

from __future__ import annotations

from contextlib import contextmanager
import json
import re
from typing import Any, Callable, Iterable

from pydantic import BaseModel

from .models import ToolSpec

try:  # pragma: no cover - optional dependency
    from langsmith import traceable as _traceable  # type: ignore
except Exception:  # pragma: no cover - tracing is optional
    _traceable = None  # type: ignore

try:  # pragma: no cover - optional dependency
    from langsmith.run_helpers import (  # type: ignore
        get_current_run_tree as _get_current_run_tree,
    )
    from langsmith.run_helpers import tracing_context as _tracing_context  # type: ignore
except Exception:  # pragma: no cover - tracing is optional
    _get_current_run_tree = None  # type: ignore
    _tracing_context = None  # type: ignore

TRACE_ROLE_PREVIEW_LIMIT = 8
TRACE_MESSAGE_PREVIEW_CHARS = 160
TRACE_MESSAGE_SUMMARY_LIMIT = 12
TRACE_TOOL_NAME_LIMIT = 8
TRACE_LLM_MESSAGE_LOG_LIMIT = 8
TRACE_TOOL_CALL_PREVIEW_LIMIT = 6
TRACE_TOOL_ARGS_PREVIEW_CHARS = 240
TRACE_COLLECTION_LIMIT = 20

_TRACE_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_TRACE_PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d(). \-]{6,}\d)")
_TRACE_HANDLE_RE = re.compile(r"(?<!\S)@[A-Za-z0-9_]{2,32}")


def traceable(*args, **kwargs):  # type: ignore
    if _traceable is not None:
        return _traceable(*args, **kwargs)
    if args and callable(args[0]) and len(args) == 1 and not kwargs:
        return args[0]

    def decorator(fn):
        return fn

    return decorator


@contextmanager
def tracing_context(*args, **kwargs):  # type: ignore
    if _tracing_context is not None:
        with _tracing_context(*args, **kwargs) as ctx:
            yield ctx
        return
    yield None


def set_trace_metadata(**metadata: Any) -> None:
    if _get_current_run_tree is None:
        return
    clean = {
        key: _sanitize_trace_value(value)
        for key, value in metadata.items()
        if value is not None
    }
    if not clean:
        return
    try:
        run_tree = _get_current_run_tree()
    except Exception:
        return
    if not run_tree:
        return
    try:
        existing = getattr(run_tree, "metadata", None)
        if isinstance(existing, dict):
            existing.update(clean)
        else:
            run_tree.metadata = clean
    except Exception:
        try:
            run_tree.add_metadata(clean)
        except Exception:
            return


def set_trace_name(name: str | None) -> None:
    if not name or _get_current_run_tree is None:
        return
    try:
        run_tree = _get_current_run_tree()
    except Exception:
        return
    if not run_tree:
        return
    try:
        run_tree.name = name
    except Exception:
        return


def get_trace_parent_headers() -> dict[str, str] | None:
    if _get_current_run_tree is None:
        return None
    try:
        run_tree = _get_current_run_tree()
    except Exception:
        return None
    if not run_tree:
        return None
    try:
        headers = run_tree.to_headers()
    except Exception:
        return None
    if not headers:
        return None
    return dict(headers)


def _safe_len(value: Any) -> int | None:
    try:
        return len(value)
    except Exception:
        return None


def _trim_text(value: str, max_chars: int) -> str:
    value = _sanitize_trace_text(value)
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip() + "... [truncated]"


def _sanitize_trace_text(value: str) -> str:
    redacted = _TRACE_EMAIL_RE.sub("[redacted-email]", value)
    redacted = _TRACE_PHONE_RE.sub("[redacted-phone]", redacted)
    redacted = _TRACE_HANDLE_RE.sub("@[redacted-user]", redacted)
    return redacted


def _sanitize_trace_value(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_trace_text(value)
    if isinstance(value, list):
        return [_sanitize_trace_value(item) for item in value[:TRACE_COLLECTION_LIMIT]]
    if isinstance(value, tuple):
        return tuple(
            _sanitize_trace_value(item) for item in value[:TRACE_COLLECTION_LIMIT]
        )
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= TRACE_COLLECTION_LIMIT:
                sanitized["truncated_items"] = len(value) - TRACE_COLLECTION_LIMIT
                break
            sanitized[str(key)] = _sanitize_trace_value(item)
        return sanitized
    return value


def _summarize_chat_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, str):
        return {"kind": "text", "chars": len(payload)}
    if isinstance(payload, dict):
        return {"kind": "dict", "role": payload.get("role")}
    if isinstance(payload, list):
        roles: list[str] = []
        for item in payload:
            if isinstance(item, dict):
                role = item.get("role")
                roles.append(role if role else "unknown")
            else:
                roles.append(type(item).__name__)
        summary: dict[str, Any] = {"kind": "list", "count": len(payload)}
        if roles:
            summary["roles"] = roles[:TRACE_ROLE_PREVIEW_LIMIT]
            if len(roles) > TRACE_ROLE_PREVIEW_LIMIT:
                summary["roles_truncated"] = len(roles) - TRACE_ROLE_PREVIEW_LIMIT
        return summary
    return {"kind": type(payload).__name__}


def _summarize_messages(messages: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not messages:
        return []
    summaries: list[dict[str, Any]] = []
    for message in messages[:TRACE_MESSAGE_SUMMARY_LIMIT]:
        if not isinstance(message, dict):
            summaries.append({"type": type(message).__name__})
            continue
        role = message.get("role")
        summary: dict[str, Any] = {"role": role}
        content = message.get("content")
        if isinstance(content, str):
            summary["content_chars"] = len(content)
            if role == "system":
                summary["content_preview"] = _trim_text(
                    content, TRACE_MESSAGE_PREVIEW_CHARS
                )
        elif content is None:
            summary["content"] = None
        else:
            summary["content_type"] = type(content).__name__
        tool_calls = message.get("tool_calls")
        if tool_calls:
            summary["tool_calls"] = _safe_len(tool_calls) or "unknown"
        summaries.append(summary)
    if len(messages) > TRACE_MESSAGE_SUMMARY_LIMIT:
        summaries.append(
            {"truncated_messages": len(messages) - TRACE_MESSAGE_SUMMARY_LIMIT}
        )
    return summaries


def _summarize_tools(tools: list[ToolSpec] | None) -> dict[str, Any]:
    if not tools:
        return {"tool_count": 0}
    names: list[str] = []
    for tool in tools:
        fn = tool.get("function") or {}
        name = fn.get("name")
        if name:
            names.append(name)
    summary: dict[str, Any] = {"tool_count": len(tools)}
    if names:
        summary["tool_names"] = names[:TRACE_TOOL_NAME_LIMIT]
        if len(names) > TRACE_TOOL_NAME_LIMIT:
            summary["tool_names_truncated"] = len(names) - TRACE_TOOL_NAME_LIMIT
    return summary


def _trace_tool_calls(tool_calls: Any) -> list[dict[str, Any]] | None:
    if not tool_calls or not isinstance(tool_calls, list):
        return None
    preview: list[dict[str, Any]] = []
    for call in tool_calls[:TRACE_TOOL_CALL_PREVIEW_LIMIT]:
        if isinstance(call, dict):
            fn = call.get("function") or {}
            name = fn.get("name")
            raw_args = fn.get("arguments")
            call_id = call.get("id")
            call_type = call.get("type")
        else:
            fn = getattr(call, "function", None)
            name = getattr(fn, "name", None) if fn else None
            raw_args = getattr(fn, "arguments", None) if fn else None
            call_id = getattr(call, "id", None)
            call_type = getattr(call, "type", None)

        entry: dict[str, Any] = {
            "id": call_id,
            "type": call_type,
            "name": name,
        }
        if isinstance(raw_args, str):
            entry["arguments"] = _trim_text(raw_args, TRACE_TOOL_ARGS_PREVIEW_CHARS)
        elif raw_args is not None:
            entry["arguments_type"] = type(raw_args).__name__
        preview.append(entry)

    if len(tool_calls) > TRACE_TOOL_CALL_PREVIEW_LIMIT:
        preview.append(
            {"truncated_tool_calls": len(tool_calls) - TRACE_TOOL_CALL_PREVIEW_LIMIT}
        )
    return preview


def _trace_messages_for_llm(messages: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not messages:
        return []
    preview: list[dict[str, Any]] = []
    for message in messages[:TRACE_LLM_MESSAGE_LOG_LIMIT]:
        if not isinstance(message, dict):
            preview.append({"type": type(message).__name__})
            continue
        entry: dict[str, Any] = {"role": message.get("role")}
        if message.get("name"):
            entry["name"] = message.get("name")
        content = message.get("content")
        if isinstance(content, str):
            entry["content"] = _trim_text(content, TRACE_MESSAGE_PREVIEW_CHARS)
        elif content is None:
            entry["content"] = None
        else:
            entry["content_type"] = type(content).__name__
        tool_calls = message.get("tool_calls")
        if tool_calls:
            entry["tool_calls"] = _trace_tool_calls(tool_calls)
        preview.append(entry)
    if len(messages) > TRACE_LLM_MESSAGE_LOG_LIMIT:
        preview.append(
            {"truncated_messages": len(messages) - TRACE_LLM_MESSAGE_LOG_LIMIT}
        )
    return preview


def _normalize_tool_call_block(tool_call: Any) -> dict[str, Any] | None:
    if isinstance(tool_call, dict):
        fn = tool_call.get("function") or {}
        name = fn.get("name")
        raw_args = fn.get("arguments")
        call_id = tool_call.get("id")
    else:
        fn = getattr(tool_call, "function", None)
        name = getattr(fn, "name", None) if fn else None
        raw_args = getattr(fn, "arguments", None) if fn else None
        call_id = getattr(tool_call, "id", None)
    if not name and not call_id:
        return None
    args: dict[str, Any]
    if isinstance(raw_args, dict):
        args = raw_args
    elif isinstance(raw_args, str):
        try:
            args = json.loads(raw_args)
        except Exception:
            args = {"_raw": _trim_text(raw_args, TRACE_TOOL_ARGS_PREVIEW_CHARS)}
    elif raw_args is None:
        args = {}
    else:
        args = {"_raw": _trim_text(str(raw_args), TRACE_TOOL_ARGS_PREVIEW_CHARS)}
    block: dict[str, Any] = {"type": "tool_call", "args": args}
    if call_id:
        block["id"] = call_id
    if name:
        block["name"] = name
    return block


def _build_tool_result_block(
    tool_call_id: str | None,
    content: Any,
) -> dict[str, Any]:
    status = "success"
    output: Any = None
    payload: dict[str, Any] | None = None

    if isinstance(content, dict):
        payload = content
    elif isinstance(content, str):
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                payload = parsed
            else:
                output = parsed
        except Exception:
            output = _trim_text(content, TRACE_MESSAGE_PREVIEW_CHARS)
    elif content is not None:
        output = _trim_text(str(content), TRACE_MESSAGE_PREVIEW_CHARS)

    if payload is not None:
        payload_status = payload.get("status")
        if isinstance(payload_status, str) and payload_status.lower() == "error":
            status = "error"
        if payload.get("error") is not None:
            status = "error"
        output = (
            payload.get("data")
            if payload.get("data") is not None
            else payload.get("output")
        )
        if output is None:
            output = payload.get("error") or payload

    block: dict[str, Any] = {
        "type": "server_tool_result",
        "tool_call_id": tool_call_id or "unknown",
        "status": status,
    }
    if output is not None:
        block["output"] = output
    return block


def _normalize_content_blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, list):
        blocks: list[dict[str, Any]] = []
        for item in content:
            if isinstance(item, dict):
                block = dict(item)
                if block.get("type") in {"text", "reasoning"} and isinstance(
                    block.get("text"), str
                ):
                    block["text"] = _trim_text(
                        block["text"], TRACE_MESSAGE_PREVIEW_CHARS
                    )
                blocks.append(block)
            else:
                blocks.append(
                    {
                        "type": "text",
                        "text": _trim_text(str(item), TRACE_MESSAGE_PREVIEW_CHARS),
                    }
                )
        return blocks
    if isinstance(content, str):
        return [{"type": "text", "text": _trim_text(content, TRACE_MESSAGE_PREVIEW_CHARS)}]
    if content is None:
        return []
    return [
        {
            "type": "text",
            "text": _trim_text(str(content), TRACE_MESSAGE_PREVIEW_CHARS),
        }
    ]


def _normalize_message_for_langsmith(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        role = message.get("role")
        tool_call_id = message.get("tool_call_id")
        content = message.get("content")
        tool_calls = message.get("tool_calls")
    else:
        role = getattr(message, "role", None)
        tool_call_id = getattr(message, "tool_call_id", None)
        content = getattr(message, "content", None)
        tool_calls = getattr(message, "tool_calls", None)

    normalized: dict[str, Any] = {"role": role or "assistant"}
    if role == "tool":
        block = _build_tool_result_block(tool_call_id, content)
        normalized["content"] = [block]
        if tool_call_id:
            normalized["tool_call_id"] = tool_call_id
        return normalized

    blocks = _normalize_content_blocks(content)

    if tool_calls and isinstance(tool_calls, list):
        for call in tool_calls:
            block = _normalize_tool_call_block(call)
            if block:
                blocks.append(block)

    normalized["content"] = blocks
    if tool_call_id:
        normalized["tool_call_id"] = tool_call_id
    return normalized


def _build_langsmith_messages(messages: list[Any] | None) -> list[dict[str, Any]]:
    if not messages:
        return []
    normalized: list[dict[str, Any]] = []
    for message in messages[:TRACE_LLM_MESSAGE_LOG_LIMIT]:
        normalized.append(_normalize_message_for_langsmith(message))
    if len(messages) > TRACE_LLM_MESSAGE_LOG_LIMIT:
        normalized.append(
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": f"[truncated {len(messages) - TRACE_LLM_MESSAGE_LOG_LIMIT} messages]",
                    }
                ],
            }
        )
    return normalized


def _summarize_response_format(response_format: Any) -> Any:
    if response_format is None:
        return None
    if isinstance(response_format, dict):
        return {"keys": list(response_format.keys())}
    if isinstance(response_format, type):
        return getattr(response_format, "__name__", str(response_format))
    return type(response_format).__name__


def _trace_generate_structured_inputs(*args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        pos_args = list(args)
        self_obj = None
        if pos_args and not isinstance(pos_args[0], type):
            self_obj = pos_args.pop(0)

        schema = kwargs.get("schema")
        system_prompt = kwargs.get("system_prompt")
        chat_message = kwargs.get("chat_message")
        if schema is None and len(pos_args) >= 1:
            schema = pos_args[0]
        if system_prompt is None and len(pos_args) >= 2:
            system_prompt = pos_args[1]
        if chat_message is None and len(pos_args) >= 3:
            chat_message = pos_args[2]

        model = kwargs.get("model")
        temperature = kwargs.get("temperature", 0.2)
        max_tokens = kwargs.get("max_tokens")
        if model is None and self_obj is not None:
            try:
                model = self_obj._default_chat_model()  # type: ignore[attr-defined]
            except Exception:
                model = None

        if schema is None or system_prompt is None or chat_message is None:
            return {
                "schema": getattr(schema, "__name__", str(schema)) if schema else None,
                "system_prompt_chars": len(system_prompt) if system_prompt else 0,
                "chat_message": _summarize_chat_payload(chat_message)
                if chat_message is not None
                else {"kind": "missing"},
                "model": model or "unknown",
                "temperature": temperature,
                "max_tokens": max_tokens,
            "trace_warning": "missing_required_inputs",
            "arg_count": len(args),
            "kw_keys": sorted(kwargs.keys())[:10],
        }

        return {
            "schema": getattr(schema, "__name__", str(schema)),
            "system_prompt_chars": len(system_prompt) if system_prompt else 0,
            "chat_message": _summarize_chat_payload(chat_message),
            "model": model or "unknown",
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
    except Exception as exc:  # pragma: no cover - defensive tracing
        return {
            "trace_warning": "trace_inputs_failed",
            "error": str(exc),
            "arg_count": len(args),
            "kw_keys": sorted(kwargs.keys())[:10],
        }


def _trace_generate_structured_outputs(output: BaseModel) -> dict[str, Any]:
    summary: dict[str, Any] = {"output_type": output.__class__.__name__}
    try:
        payload = output.model_dump(exclude_none=True)
    except Exception:
        payload = None
    if isinstance(payload, dict):
        summary["output_keys"] = list(payload.keys())
    return summary


def _trace_embed_inputs(*args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        pos_args = list(args)
        self_obj = None
        if pos_args and not isinstance(pos_args[0], (str, bytes, list, tuple)):
            self_obj = pos_args.pop(0)

        texts = kwargs.get("texts")
        if texts is None and pos_args:
            texts = pos_args[0]
        model = kwargs.get("model")
        if model is None and self_obj is not None:
            try:
                model = self_obj._default_embed_model()  # type: ignore[attr-defined]
            except Exception:
                model = None
        return {
            "text_count": _safe_len(texts),
            "model": model or "unknown",
        }
    except Exception as exc:  # pragma: no cover - defensive tracing
        return {
            "trace_warning": "trace_inputs_failed",
            "error": str(exc),
            "arg_count": len(args),
            "kw_keys": sorted(kwargs.keys())[:10],
        }


def _trace_embed_outputs(output: list[list[float]]) -> dict[str, Any]:
    dimensions = len(output[0]) if output else 0
    return {"embedding_count": len(output), "dimensions": dimensions}


def _trace_handle_params_inputs(*args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        pos_args = list(args)
        self_obj = None
        if pos_args and not isinstance(pos_args[0], (str, dict, list)):
            self_obj = pos_args.pop(0)
        system_prompt = kwargs.get("system_prompt")
        chat_messages = kwargs.get("chat_messages")
        if system_prompt is None and pos_args:
            system_prompt = pos_args[0]
        if chat_messages is None and len(pos_args) >= 2:
            chat_messages = pos_args[1]

        model = kwargs.get("model")
        temperature = kwargs.get("temperature", 0.2)
        max_tokens = kwargs.get("max_tokens")
        response_format = kwargs.get("response_format")
        tools = kwargs.get("tools")
        toolbox = kwargs.get("toolbox")

        summary = {
            "system_prompt_chars": len(system_prompt) if system_prompt else 0,
            "chat_messages": _summarize_chat_payload(chat_messages),
            "model": model or "unknown",
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": _summarize_response_format(response_format),
        }
        if model is None and self_obj is not None:
            try:
                summary["model"] = self_obj._default_chat_model()  # type: ignore[attr-defined]
            except Exception:
                summary["model"] = "unknown"
        tools_payload = tools
        if tools_payload is None and toolbox is not None:
            tools_payload = toolbox.tools
        summary.update(_summarize_tools(tools_payload))
        if kwargs:
            summary["extra_params"] = sorted(kwargs.keys())[:10]
        return summary
    except Exception as exc:  # pragma: no cover - defensive tracing
        return {
            "trace_warning": "trace_inputs_failed",
            "error": str(exc),
            "arg_count": len(args),
            "kw_keys": sorted(kwargs.keys())[:10],
        }


def _trace_handle_params_outputs(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": params.get("model"),
        "message_count": _safe_len(params.get("messages") or []),
        "tool_count": _safe_len(params.get("tools") or []),
        "response_format": _summarize_response_format(params.get("response_format")),
    }


def _trace_call_openai_inputs(*args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        inputs: dict[str, Any] | None = None
        if args and isinstance(args[0], dict):
            inputs = args[0]
        if inputs is None:
            inputs = kwargs

        params = inputs.get("params") if isinstance(inputs, dict) else None
        if params is None and isinstance(inputs, dict):
            params = inputs
        tools_mapping = inputs.get("tools_mapping") if isinstance(inputs, dict) else None
        toolbox = inputs.get("toolbox") if isinstance(inputs, dict) else None

        summary = {
            "model": params.get("model") if isinstance(params, dict) else None,
            "temperature": params.get("temperature") if isinstance(params, dict) else None,
            "max_tokens": None,
            "message_count": None,
        }
        if isinstance(params, dict):
            summary["max_tokens"] = params.get("max_tokens") or params.get(
                "max_output_tokens"
            )
            messages = params.get("messages") or []
            summary["message_count"] = _safe_len(messages)
            summary["messages"] = _build_langsmith_messages(messages)
            summary["messages_preview"] = _trace_messages_for_llm(messages)
            summary["messages_summary"] = _summarize_messages(messages)
            tools_payload = params.get("tools")
            if isinstance(tools_payload, list):
                summary.update(_summarize_tools(tools_payload))
        if toolbox is not None:
            summary["toolbox"] = getattr(toolbox, "name", str(toolbox))
        if tools_mapping is not None:
            summary["tool_mapping_count"] = _safe_len(tools_mapping) or 0
        return summary
    except Exception as exc:  # pragma: no cover - defensive tracing
        return {
            "trace_warning": "trace_inputs_failed",
            "error": str(exc),
            "arg_count": len(args),
            "kw_keys": sorted(kwargs.keys())[:10],
        }


def _trace_parse_structured_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(inputs, dict):
        return {"inputs_type": type(inputs).__name__}
    response = inputs.get("response")
    schema = inputs.get("schema")
    return {
        "response_type": type(response).__name__ if response is not None else None,
        "schema": getattr(schema, "__name__", str(schema)) if schema else None,
    }


def _trace_parse_structured_outputs(output: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {"output_type": type(output).__name__}
    try:
        if isinstance(output, BaseModel):
            payload = output.model_dump(exclude_none=True)
            if isinstance(payload, dict):
                summary["output_keys"] = list(payload.keys())
        elif isinstance(output, dict):
            summary["output_keys"] = list(output.keys())
    except Exception:
        pass
    return summary


def _trace_call_openai_outputs(response: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {"response_type": type(response).__name__}
    model = getattr(response, "model", None)
    if model:
        summary["model"] = model
    usage = getattr(response, "usage", None)
    if usage is not None:
        usage_payload: dict[str, Any] = {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = getattr(usage, key, None)
            if value is not None:
                usage_payload[key] = value
        if usage_payload:
            summary["usage_metadata"] = usage_payload
    choices = getattr(response, "choices", None)
    if choices:
        summary["choices"] = _safe_len(choices)
        try:
            first = choices[0]
            summary["finish_reason"] = getattr(first, "finish_reason", None)
            message = getattr(first, "message", None)
            if message is not None:
                content = getattr(message, "content", None)
                if isinstance(content, str):
                    summary["message_chars"] = len(content)
                tool_calls = getattr(message, "tool_calls", None)
                if tool_calls:
                    summary["tool_calls"] = _safe_len(tool_calls) or "unknown"
                summary["messages"] = [_normalize_message_for_langsmith(message)]
        except Exception:
            pass
    return summary


def _trace_execute_tool_inputs(*args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        inputs: dict[str, Any] | None = None
        if args and isinstance(args[0], dict):
            inputs = args[0]
        if inputs is None:
            inputs = kwargs

        tool_call = inputs.get("tool_call") if isinstance(inputs, dict) else None
        tools_by_name = inputs.get("tools_by_name") if isinstance(inputs, dict) else None

        fn = getattr(tool_call, "function", None) if tool_call is not None else None
        name = getattr(fn, "name", None) if fn else None
        raw_args = getattr(fn, "arguments", None) if fn else None
        summary = {
            "tool": name,
            "raw_args_chars": len(raw_args) if isinstance(raw_args, str) else None,
        }
        if tools_by_name is not None and name is not None:
            summary["tool_allowed"] = name in tools_by_name
        return summary
    except Exception as exc:  # pragma: no cover - defensive tracing
        return {
            "trace_warning": "trace_inputs_failed",
            "error": str(exc),
            "arg_count": len(args),
            "kw_keys": sorted(kwargs.keys())[:10],
        }


def _trace_execute_tool_outputs(output: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"message_type": type(output).__name__}
    if isinstance(output, dict):
        summary["role"] = output.get("role")
        content = output.get("content")
        if isinstance(content, str):
            summary["content_chars"] = len(content)
            try:
                payload = json.loads(content)
            except Exception:
                payload = None
            if isinstance(payload, dict):
                summary["tool_status"] = payload.get("status")
                error = payload.get("error")
                if isinstance(error, dict):
                    summary["error_code"] = error.get("code")
                    summary["error_message"] = error.get("message")
                data = payload.get("data")
                if isinstance(data, dict):
                    summary["data_keys"] = list(data.keys())[:20]
                    if len(data.keys()) > 20:
                        summary["data_keys_truncated"] = len(data.keys()) - 20
                elif isinstance(data, list):
                    summary["data_items"] = len(data)
                meta = payload.get("meta")
                if isinstance(meta, dict):
                    summary["tool"] = meta.get("tool")
                    summary["duration_ms"] = meta.get("duration_ms")
    return summary
