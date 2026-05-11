"""Reusable OpenAI/Azure GenAI client wrapper with tools and token guardrails."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
import json
import logging
import os
import time
from typing import Any, Callable, Iterable

from pydantic import BaseModel

from t212ai.app.config import AppSettings, load_env_file
from t212ai.app.logging import log_event

from .context import (
    DEFAULT_CONTEXT_FALLBACK_TOKENS,
    DEFAULT_CONTEXT_GUARD_RATIO,
    DEFAULT_CONTEXT_RECENT_MESSAGES,
    DEFAULT_CONTEXT_SUMMARY_MAX_TOKENS,
    DEFAULT_OUTPUT_RESERVE_TOKENS,
    ContextBudgetResolver,
    GenAIContextManager,
    is_context_length_error,
    parse_context_limit_from_error,
    parse_context_token_value,
    parse_context_tokens_by_model_json,
)
from .models import ToolError, ToolResult, ToolSpec
from .tokenizer import TokenCounter
from .tools import ToolBox, build_chat_toolbox, build_tool_mapping
from .tracing import (
    traceable,
)

try:
    from langsmith.wrappers import wrap_openai  # type: ignore
except Exception:  # pragma: no cover - tracing is optional
    wrap_openai = None  # type: ignore


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_context_tokens(name: str) -> int | None:
    return parse_context_token_value(os.getenv(name))


def _env_context_tokens_default(name: str, default: int) -> int:
    parsed = parse_context_token_value(os.getenv(name))
    return parsed if parsed is not None else default


def _settings_context_tokens(value: str | None) -> int | None:
    return parse_context_token_value(value)


def _settings_context_tokens_default(value: str | None, default: int) -> int:
    parsed = parse_context_token_value(value)
    return parsed if parsed is not None else default


def _safe_int(value: Any, default: int) -> int:
    if value is None or not str(value).strip():
        return default
    try:
        return int(str(value).strip())
    except ValueError:
        return default


def _safe_float(value: Any, default: float) -> float:
    if value is None or not str(value).strip():
        return default
    try:
        return float(str(value).strip())
    except ValueError:
        return default


def _provider_error_code(exc: Exception) -> str | None:
    return _provider_error_details(exc).get("error_code")


def _provider_error_details(exc: Exception) -> dict[str, Any]:
    payload = _provider_error_payload(exc)
    error_payload: dict[str, Any] = {}
    if isinstance(payload, dict):
        nested = payload.get("error")
        error_payload = nested if isinstance(nested, dict) else payload

    values = [
        getattr(exc, "code", None),
        getattr(exc, "status_code", None),
        getattr(exc, "body", None),
        getattr(exc, "message", None),
        payload,
        str(exc),
    ]
    text = " ".join(str(value).lower() for value in values if value is not None)
    raw_code = (
        error_payload.get("code")
        or getattr(exc, "code", None)
        or error_payload.get("status")
        or getattr(exc, "status_code", None)
    )
    error_code = _normalize_provider_error_code(raw_code, text)
    inner_error = error_payload.get("innererror") or error_payload.get("inner_error")
    inner_error = inner_error if isinstance(inner_error, dict) else {}
    filter_summary = _content_filter_summary(error_payload, inner_error)
    if filter_summary and error_code is None:
        error_code = "content_filter"

    return {
        "error_code": error_code,
        "provider_error_code": raw_code if raw_code is not None else None,
        "provider_error_type": error_payload.get("type") or getattr(exc, "type", None),
        "provider_error_param": error_payload.get("param")
        or getattr(exc, "param", None),
        "provider_status": error_payload.get("status")
        or getattr(exc, "status_code", None),
        "provider_policy_code": inner_error.get("code"),
        **filter_summary,
    }


def _provider_error_payload(exc: Exception) -> dict[str, Any] | None:
    body = getattr(exc, "body", None)
    parsed = _parse_provider_payload(body)
    if isinstance(parsed, dict):
        return parsed

    response = getattr(exc, "response", None)
    if response is None:
        return None
    response_json = getattr(response, "json", None)
    if callable(response_json):
        try:
            parsed = response_json()
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    return _parse_provider_payload(getattr(response, "text", None))


def _parse_provider_payload(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _normalize_provider_error_code(value: Any, text: str) -> str | None:
    raw = str(value).strip() if value is not None else ""
    lowered = raw.lower().replace("-", "_")
    if (
        "contentfilter" in text
        or "content_filter" in text
        or "responsibleaipolicyviolation" in text
    ):
        return "content_filter"
    if lowered in {"contentfilter", "content_filter"}:
        return "content_filter"
    return raw or None


def _content_filter_summary(
    error_payload: dict[str, Any],
    inner_error: dict[str, Any],
) -> dict[str, Any]:
    result = (
        inner_error.get("contentfilterresult")
        or inner_error.get("content_filter_result")
        or error_payload.get("contentfilterresult")
        or error_payload.get("content_filter_result")
    )
    if not isinstance(result, dict):
        return {}

    category_status: dict[str, dict[str, Any]] = {}
    categories: list[str] = []
    blocked_categories: list[str] = []
    detected_categories: list[str] = []
    for category, raw_status in sorted(result.items()):
        if not isinstance(raw_status, dict):
            continue
        filtered = bool(raw_status.get("filtered"))
        detected = bool(raw_status.get("detected"))
        severity = str(raw_status.get("severity") or "").strip().lower()
        category_status[str(category)] = {
            key: value
            for key, value in {
                "filtered": filtered,
                "detected": detected if "detected" in raw_status else None,
                "severity": severity or None,
            }.items()
            if value is not None
        }
        if filtered or detected or severity not in {"", "safe"}:
            categories.append(str(category))
        if filtered:
            blocked_categories.append(str(category))
        if detected:
            detected_categories.append(str(category))

    return {
        "content_filter_categories": categories,
        "content_filter_blocked_categories": blocked_categories,
        "content_filter_detected_categories": detected_categories,
        "content_filter_category_status": category_status,
    }


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


@dataclass(slots=True)
class GenAISettings:
    openai_api_key: str | None = None
    openai_embed_model: str = "text-embedding-3-small"
    chat_model_default: str = "gpt-4o-mini"
    chat_model_smart: str = "gpt-4.1"
    chat_model_reasoning: str = "o4-mini"
    embed_dimensions: int | None = None
    context_tokens_default: int | None = None
    context_tokens_smart: int | None = None
    context_tokens_reasoning: int | None = None
    context_tokens_by_model: dict[str, int] = field(default_factory=dict)
    context_fallback_tokens: int = DEFAULT_CONTEXT_FALLBACK_TOKENS
    context_guard_ratio: float = DEFAULT_CONTEXT_GUARD_RATIO
    output_reserve_tokens: int = DEFAULT_OUTPUT_RESERVE_TOKENS
    context_recent_messages: int = DEFAULT_CONTEXT_RECENT_MESSAGES
    context_summary_max_tokens: int = DEFAULT_CONTEXT_SUMMARY_MAX_TOKENS
    is_azure: bool = False
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_embed_deployment: str | None = None
    genai_tool_call_limit: int = 8
    genai_tool_call_timeout_seconds: float = 30.0


def get_genai_settings() -> GenAISettings:
    load_env_file()
    embed_dimensions_raw = os.getenv("OPENAI_EMBED_DIMENSIONS")
    embed_dimensions = None
    if embed_dimensions_raw and embed_dimensions_raw.strip():
        try:
            embed_dimensions = int(embed_dimensions_raw)
        except ValueError:
            embed_dimensions = None

    return GenAISettings(
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_embed_model=os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small"),
        chat_model_default=os.getenv("OPENAI_CHAT_MODEL_DEFAULT", "gpt-4o-mini"),
        chat_model_smart=os.getenv("OPENAI_CHAT_MODEL_SMART", "gpt-4.1"),
        chat_model_reasoning=os.getenv("OPENAI_CHAT_MODEL_REASONING", "o4-mini"),
        embed_dimensions=embed_dimensions,
        context_tokens_default=_env_context_tokens("GENAI_CONTEXT_TOKENS_DEFAULT"),
        context_tokens_smart=_env_context_tokens("GENAI_CONTEXT_TOKENS_SMART"),
        context_tokens_reasoning=_env_context_tokens("GENAI_CONTEXT_TOKENS_REASONING"),
        context_tokens_by_model=parse_context_tokens_by_model_json(
            os.getenv("GENAI_CONTEXT_TOKENS_BY_MODEL_JSON")
        ),
        context_fallback_tokens=_env_context_tokens_default(
            "GENAI_CONTEXT_FALLBACK_TOKENS",
            DEFAULT_CONTEXT_FALLBACK_TOKENS,
        ),
        context_guard_ratio=_env_float(
            "GENAI_CONTEXT_GUARD_RATIO",
            DEFAULT_CONTEXT_GUARD_RATIO,
        ),
        output_reserve_tokens=_env_int(
            "GENAI_OUTPUT_RESERVE_TOKENS",
            DEFAULT_OUTPUT_RESERVE_TOKENS,
        ),
        context_recent_messages=_env_int(
            "GENAI_CONTEXT_RECENT_MESSAGES",
            DEFAULT_CONTEXT_RECENT_MESSAGES,
        ),
        context_summary_max_tokens=_env_int(
            "GENAI_CONTEXT_SUMMARY_MAX_TOKENS",
            DEFAULT_CONTEXT_SUMMARY_MAX_TOKENS,
        ),
        is_azure=_env_bool("AZURE_OPENAI_ENABLED", False),
        azure_openai_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        azure_openai_api_version=os.getenv(
            "AZURE_OPENAI_API_VERSION", "2024-10-21"
        ),
        azure_openai_embed_deployment=os.getenv("AZURE_OPENAI_EMBED_DEPLOYMENT"),
        genai_tool_call_limit=_env_int("GENAI_TOOL_CALL_LIMIT", 8),
        genai_tool_call_timeout_seconds=_env_float(
            "GENAI_TOOL_CALL_TIMEOUT_SECONDS", 30.0
        ),
    )


def genai_settings_from_app_settings(settings: AppSettings) -> GenAISettings:
    embed_dimensions = None
    raw_dimensions = str(settings.openai_embed_dimensions or "").strip()
    if raw_dimensions:
        try:
            embed_dimensions = int(raw_dimensions)
        except ValueError:
            embed_dimensions = None

    return GenAISettings(
        openai_api_key=settings.openai_api_key,
        openai_embed_model=settings.openai_embed_model,
        chat_model_default=settings.openai_chat_model_default,
        chat_model_smart=settings.openai_chat_model_smart,
        chat_model_reasoning=settings.openai_chat_model_reasoning,
        embed_dimensions=embed_dimensions,
        context_tokens_default=_settings_context_tokens(
            settings.genai_context_tokens_default
        ),
        context_tokens_smart=_settings_context_tokens(settings.genai_context_tokens_smart),
        context_tokens_reasoning=_settings_context_tokens(
            settings.genai_context_tokens_reasoning
        ),
        context_tokens_by_model=parse_context_tokens_by_model_json(
            settings.genai_context_tokens_by_model_json
        ),
        context_fallback_tokens=_settings_context_tokens_default(
            settings.genai_context_fallback_tokens,
            DEFAULT_CONTEXT_FALLBACK_TOKENS,
        ),
        context_guard_ratio=_safe_float(
            settings.genai_context_guard_ratio,
            DEFAULT_CONTEXT_GUARD_RATIO,
        ),
        output_reserve_tokens=_safe_int(
            settings.genai_output_reserve_tokens,
            DEFAULT_OUTPUT_RESERVE_TOKENS,
        ),
        context_recent_messages=_safe_int(
            settings.genai_context_recent_messages,
            DEFAULT_CONTEXT_RECENT_MESSAGES,
        ),
        context_summary_max_tokens=_safe_int(
            settings.genai_context_summary_max_tokens,
            DEFAULT_CONTEXT_SUMMARY_MAX_TOKENS,
        ),
        is_azure=(
            str(settings.llm_provider or "").strip().lower() == "azure_openai"
            or bool(settings.azure_openai_enabled)
        ),
        azure_openai_endpoint=settings.azure_openai_endpoint,
        azure_openai_api_key=settings.azure_openai_api_key,
        azure_openai_api_version=settings.azure_openai_api_version,
        azure_openai_embed_deployment=settings.azure_openai_embed_deployment,
    )


class GenAIClient:
    def __init__(
        self,
        settings: GenAISettings | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.settings = settings or get_genai_settings()
        self.logger = logger or logging.getLogger(__name__)
        self.client = self._make_client()
        self.token_counter = TokenCounter()
        self.context_manager = self._build_context_manager()
        self.max_context_tokens = self.settings.context_fallback_tokens
        self.output_reserve_tokens = self.settings.output_reserve_tokens
        self.max_retries = 3
        self.retry_backoff_seconds = 1.5
        self.use_responses_api = self._resolve_responses_api()
        self.tool_call_limit = max(0, int(self.settings.genai_tool_call_limit))
        self.tool_call_timeout_seconds = max(
            0.0, float(self.settings.genai_tool_call_timeout_seconds)
        )
        self.chat_toolbox = build_chat_toolbox()
        self._tool_mapping: dict[str, Callable[..., Any]] | None = None
        self._log_configuration()

    @traceable(
        name="Structured Generation",
        run_type="chain"
    )
    def generate_structured(
        self,
        schema: type[BaseModel],
        system_prompt: str,
        chat_message: str | dict[str, Any] | list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> BaseModel:
        messages = self._build_messages(system_prompt, chat_message)
        params: dict[str, Any] = {
            "model": model or self._default_chat_model(),
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        self._ensure_context_budget(params)
        messages = params.get("messages") or messages
        max_tokens = params.get("max_tokens")
        return self._call_structured_with_retries(
            schema,
            messages=messages,
            model=params["model"],
            temperature=temperature,
            max_tokens=max_tokens,
        )

    @traceable(name="Embed Texts", run_type="embedding")
    def embed(
        self,
        texts: Iterable[str],
        *,
        model: str | None = None,
    ) -> list[list[float]]:
        model_name = model or self._default_embed_model()
        params: dict[str, Any] = {
            "model": model_name,
            "input": list(texts),
        }
        dimensions = getattr(self.settings, "embed_dimensions", None)
        if dimensions:
            params["dimensions"] = dimensions
        response = self.client.embeddings.create(**params)
        return [item.embedding for item in response.data]

    @traceable(
        name="Build Chat Params",
        run_type="prompt"
    )
    def handle_params(
        self,
        system_prompt: str,
        chat_messages: str | dict[str, Any] | list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | type[BaseModel] | None = None,
        tools: list[ToolSpec] | None = None,
        toolbox: ToolBox | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        messages = self._build_messages(system_prompt, chat_messages)

        params: dict[str, Any] = {
            "model": model or self._default_chat_model(),
            "messages": messages,
            # "temperature": temperature,       # OpenAI models 5> do not support well this parameter
        }

        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        if response_format is not None:
            params["response_format"] = response_format
        if toolbox and not tools:
            tools = toolbox.tools
        if tools:
            params["tools"] = tools

        for key, value in kwargs.items():
            if value is not None:
                params[key] = value
        if "tools" not in params:
            params.pop("parallel_tool_calls", None)

        self._ensure_context_budget(params)
        return params

    @traceable(name="Chat Completion", run_type="chain")
    def call_openai(
        self,
        params: dict[str, Any],
        tools_mapping: dict[str, Callable[..., Any]] | None = None,
        toolbox: ToolBox | None = None,
        include_tool_meta: bool = False,
        max_tool_calls: int | None = None,
    ):
        call_start = time.monotonic()
        model = str(params.get("model") or "unknown")
        tool_call_limit = self._resolve_tool_call_limit(max_tool_calls)
        prompt_diagnostics = _llm_prompt_diagnostics(
            params,
            toolbox=toolbox,
            model=model,
        )
        log_event(
            self.logger,
            "llm.call.start",
            component="genai",
            step="call_openai",
            status="started",
            model=model,
            provider="azure_openai" if self.settings.is_azure else "openai",
            **prompt_diagnostics,
        )
        if toolbox and "tools" not in params:
            params["tools"] = toolbox.tools
        if tools_mapping is None and (toolbox or params.get("tools")):
            tools_mapping = self._get_tool_mapping()

        tools_by_name = toolbox.tools_by_name if toolbox else None
        tool_calls_executed = 0
        start_time = time.monotonic()
        response_format = params.get("response_format")
        structured_schema = (
            response_format
            if isinstance(response_format, type)
            and issubclass(response_format, BaseModel)
            else None
        )
        call_fn = (
            self._call_structured_response_with_retries
            if structured_schema is not None
            else self._call_with_retries
        )

        try:
            while True:
                self._ensure_context_budget(params)
                response = call_fn(params)

                choice = response.choices[0]
                message = choice.message
                tool_calls = getattr(message, "tool_calls", None)
                if not tool_calls:
                    prompt_diagnostics = _llm_prompt_diagnostics(
                        params,
                        toolbox=toolbox,
                        model=model,
                    )
                    log_event(
                        self.logger,
                        "llm.call.end",
                        component="genai",
                        step="call_openai",
                        status="ok",
                        model=model,
                        provider="azure_openai" if self.settings.is_azure else "openai",
                        duration_ms=int((time.monotonic() - call_start) * 1000),
                        tool_call_count=tool_calls_executed,
                        **prompt_diagnostics,
                    )
                    return response

                params["messages"].append(self._message_to_dict(message))

                if not tools_mapping:
                    raise ValueError("tools_mapping is required for tool calls.")

                if self._tool_budget_exceeded(
                    start_time,
                    tool_calls_executed,
                    len(tool_calls),
                    tool_call_limit=tool_call_limit,
                ):
                    self.logger.warning(
                        "Tool budget exceeded; completing without tools. "
                        "tool_calls=%s limit=%s timeout=%.1fs",
                        tool_calls_executed,
                        tool_call_limit,
                        self.tool_call_timeout_seconds,
                    )
                    log_event(
                        self.logger,
                        "llm.tool_budget_exceeded",
                        "warning",
                        component="genai",
                        step="call_openai",
                        status="error",
                        model=model,
                        tool_call_count=tool_calls_executed,
                        tool_call_limit=tool_call_limit,
                        tool_call_timeout_seconds=self.tool_call_timeout_seconds,
                    )
                    tool_calls_executed += self._append_tool_budget_exceeded_messages(
                        params,
                        tool_calls,
                        tool_calls_executed=tool_calls_executed,
                        start_time=start_time,
                        tool_call_limit=tool_call_limit,
                    )
                    response = self._call_without_tools(params)
                    prompt_diagnostics = _llm_prompt_diagnostics(
                        params,
                        toolbox=toolbox,
                        model=model,
                    )
                    log_event(
                        self.logger,
                        "llm.call.end",
                        component="genai",
                        step="call_openai",
                        status="partial",
                        model=model,
                        provider="azure_openai" if self.settings.is_azure else "openai",
                        duration_ms=int((time.monotonic() - call_start) * 1000),
                        tool_call_count=tool_calls_executed,
                        **prompt_diagnostics,
                    )
                    return response

                for tool_call in tool_calls:
                    tool_result = self._execute_tool_call(
                        tool_call,
                        tools_mapping=tools_mapping,
                        tools_by_name=tools_by_name,
                        include_tool_meta=include_tool_meta,
                    )
                    params["messages"].append(tool_result)
                    tool_calls_executed += 1
        except Exception as exc:
            duration_ms = int((time.monotonic() - call_start) * 1000)
            prompt_diagnostics = _llm_prompt_diagnostics(
                params,
                toolbox=toolbox,
                model=model,
            )
            error_details = _provider_error_details(exc)
            if error_details.get("error_code") == "content_filter":
                log_event(
                    self.logger,
                    "llm.content_filter",
                    "warning",
                    component="genai",
                    step="call_openai",
                    status="error",
                    model=model,
                    provider="azure_openai" if self.settings.is_azure else "openai",
                    duration_ms=duration_ms,
                    error_type=exc.__class__.__name__,
                    **error_details,
                    **prompt_diagnostics,
                )
            log_event(
                self.logger,
                "llm.call.error",
                "error",
                component="genai",
                step="call_openai",
                status="error",
                model=model,
                provider="azure_openai" if self.settings.is_azure else "openai",
                duration_ms=duration_ms,
                error_type=exc.__class__.__name__,
                **error_details,
                **prompt_diagnostics,
            )
            raise

    def _default_chat_model(self) -> str:
        return self.settings.chat_model_default or "gpt-4o-mini"

    def chat_model_for(self, purpose: str | None = None) -> str:
        key = (purpose or "default").strip().lower()
        default_model = self._default_chat_model()
        if key in {"strategic", "strategy", "critical", "smart"}:
            return self.settings.chat_model_smart or default_model
        if key in {"reasoning", "reason"}:
            return self.settings.chat_model_reasoning or default_model
        return default_model

    def _default_embed_model(self) -> str:
        if self.settings.is_azure:
            return self.settings.azure_openai_embed_deployment or "text-embedding-3-small"
        return self.settings.openai_embed_model

    def _make_client(self):
        try:
            import openai
        except ImportError as exc:
            raise RuntimeError(
                "openai package is required for GenAIClient."
            ) from exc

        if self.settings.is_azure:
            if (
                not self.settings.azure_openai_endpoint
                or not self.settings.azure_openai_api_key
            ):
                raise RuntimeError("Azure OpenAI settings are missing.")
            client = openai.AzureOpenAI(
                api_key=self.settings.azure_openai_api_key,
                azure_endpoint=self.settings.azure_openai_endpoint,
                api_version=self.settings.azure_openai_api_version,
            )
            return wrap_openai(client) if wrap_openai else client

        if not self.settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is missing.")
        client = openai.OpenAI(api_key=self.settings.openai_api_key)
        return wrap_openai(client) if wrap_openai else client

    def _build_context_manager(self) -> GenAIContextManager:
        tier_context_tokens = {
            key: value
            for key, value in {
                "default": self.settings.context_tokens_default,
                "smart": self.settings.context_tokens_smart,
                "reasoning": self.settings.context_tokens_reasoning,
            }.items()
            if value is not None
        }
        resolver = ContextBudgetResolver(
            tier_context_tokens=tier_context_tokens,
            model_context_tokens=self.settings.context_tokens_by_model,
            fallback_tokens=self.settings.context_fallback_tokens,
        )
        return GenAIContextManager(
            resolver=resolver,
            token_counter=self.token_counter,
            guard_ratio=self.settings.context_guard_ratio,
            output_reserve_tokens=self.settings.output_reserve_tokens,
            recent_messages=self.settings.context_recent_messages,
            summary_max_tokens=self.settings.context_summary_max_tokens,
            logger=self.logger,
        )

    def _resolve_responses_api(self) -> bool:
        override = os.getenv("GENAI_USE_RESPONSES_API")
        supported = hasattr(self.client, "responses") and hasattr(
            self.client.responses, "parse"
        )
        if override is None or override.strip() == "":
            return supported and not self.settings.is_azure
        enabled = override.strip().lower() in {"1", "true", "yes", "y"}
        if enabled and not supported:
            self.logger.warning(
                "GENAI_USE_RESPONSES_API is set but responses API is unavailable; "
                "falling back to chat completions."
            )
            return False
        if enabled and self.settings.is_azure:
            self.logger.warning(
                "GENAI_USE_RESPONSES_API is set but Azure does not support responses; "
                "using chat completions."
            )
            return False
        return enabled

    def _log_configuration(self) -> None:
        if self.settings.is_azure:
            self.logger.debug(
                "GenAI client init: provider=azure endpoint=%s api_version=%s "
                "chat_default=%s chat_smart=%s chat_reasoning=%s "
                "embed_deployment=%s responses_api=%s",
                self.settings.azure_openai_endpoint or "unset",
                self.settings.azure_openai_api_version or "unset",
                self.settings.chat_model_default or "unset",
                self.settings.chat_model_smart or "unset",
                self.settings.chat_model_reasoning or "unset",
                self.settings.azure_openai_embed_deployment or "unset",
                self.use_responses_api,
            )
            return
        self.logger.debug(
            "GenAI client init: provider=openai chat_default=%s chat_smart=%s "
            "chat_reasoning=%s embed_model=%s responses_api=%s",
            self.settings.chat_model_default or "unset",
            self.settings.chat_model_smart or "unset",
            self.settings.chat_model_reasoning or "unset",
            self.settings.openai_embed_model or "unset",
            self.use_responses_api,
        )

    def _tool_budget_exceeded(
        self,
        start_time: float,
        tool_calls_executed: int,
        new_calls: int,
        *,
        tool_call_limit: int | None = None,
    ) -> bool:
        resolved_limit = self.tool_call_limit if tool_call_limit is None else tool_call_limit
        if (
            resolved_limit
            and tool_calls_executed + new_calls > resolved_limit
        ):
            return True
        if self.tool_call_timeout_seconds:
            elapsed = time.monotonic() - start_time
            if elapsed > self.tool_call_timeout_seconds:
                return True
        return False

    def _call_without_tools(self, params: dict[str, Any]):
        params_no_tools = dict(params)
        params_no_tools.pop("tools", None)
        params_no_tools.pop("tool_choice", None)
        params_no_tools.pop("parallel_tool_calls", None)
        response_format = params_no_tools.get("response_format")
        if isinstance(response_format, type) and issubclass(response_format, BaseModel):
            return self._call_structured_response_with_retries(params_no_tools)
        return self._call_with_retries(params_no_tools)

    @traceable(
        name="Tool Call",
        run_type="tool"
    )
    def _execute_tool_call(
        self,
        tool_call: Any,
        *,
        tools_mapping: dict[str, Callable[..., Any]],
        tools_by_name: dict[str, ToolSpec] | None = None,
        include_tool_meta: bool = False,
    ) -> dict[str, Any]:
        fn_name = tool_call.function.name
        raw_args = tool_call.function.arguments or "{}"
        meta = {
            "tool": fn_name,
            "raw_args": raw_args,
        }

        start = time.monotonic()
        log_event(
            self.logger,
            "tool.call.start",
            component="tool",
            step="execute_tool_call",
            tool_name=fn_name,
            status="started",
        )

        if tools_by_name is not None and fn_name not in tools_by_name:
            error = ToolError(
                message=f"Tool '{fn_name}' is not allowed for this toolbox.",
                code="tool_not_allowed",
                hint=self._allowed_tools_hint(tools_by_name),
                retryable=False,
                details={"allowed_tools": sorted(tools_by_name.keys())},
            )
            result = ToolResult(status="error", error=error, meta=meta)
            log_event(
                self.logger,
                "tool.call.error",
                "warning",
                component="tool",
                step="execute_tool_call",
                tool_name=fn_name,
                status="error",
                duration_ms=int((time.monotonic() - start) * 1000),
                error_code=error.code,
            )
            return self._tool_message(
                tool_call.id,
                result,
                include_tool_meta=include_tool_meta,
            )

        if fn_name not in tools_mapping:
            error = ToolError(
                message=f"Tool '{fn_name}' not found.",
                code="tool_not_found",
                hint=self._build_tool_hint(fn_name, tools_by_name),
                retryable=False,
                details={"available_tools": sorted(tools_mapping.keys())},
            )
            result = ToolResult(status="error", error=error, meta=meta)
            log_event(
                self.logger,
                "tool.call.error",
                "warning",
                component="tool",
                step="execute_tool_call",
                tool_name=fn_name,
                status="error",
                duration_ms=int((time.monotonic() - start) * 1000),
                error_code=error.code,
            )
            return self._tool_message(
                tool_call.id,
                result,
                include_tool_meta=include_tool_meta,
            )

        try:
            args = json.loads(raw_args) if raw_args else {}
        except json.JSONDecodeError as exc:
            error = ToolError(
                message="Failed to parse tool arguments as JSON.",
                code="invalid_json",
                type=exc.__class__.__name__,
                hint=self._build_tool_hint(fn_name, tools_by_name),
                retryable=False,
                details={"raw": raw_args},
            )
            result = ToolResult(status="error", error=error, meta=meta)
            log_event(
                self.logger,
                "tool.call.error",
                "warning",
                component="tool",
                step="execute_tool_call",
                tool_name=fn_name,
                status="error",
                duration_ms=int((time.monotonic() - start) * 1000),
                error_type=exc.__class__.__name__,
                error_code=error.code,
            )
            return self._tool_message(
                tool_call.id,
                result,
                include_tool_meta=include_tool_meta,
            )

        tool_fn = tools_mapping[fn_name]
        try:
            output = tool_fn(**args)
            result = self._normalize_tool_output(output)
        except Exception as exc:  # pragma: no cover
            error = ToolError(
                message=f"Tool '{fn_name}' raised: {exc}",
                code="tool_exception",
                type=exc.__class__.__name__,
                hint="Verify required parameters and try again.",
                retryable=False,
            )
            result = ToolResult(status="error", error=error)

        duration_ms = int((time.monotonic() - start) * 1000)
        meta["duration_ms"] = duration_ms
        if result.meta:
            meta.update(result.meta)
        result.meta = meta
        log_event(
            self.logger,
            "tool.call.end" if result.status == "ok" else "tool.call.error",
            "info" if result.status == "ok" else "warning",
            component="tool",
            step="execute_tool_call",
            tool_name=fn_name,
            status=result.status,
            duration_ms=duration_ms,
            error_type=result.error.type if result.error else None,
            error_code=result.error.code if result.error else None,
            arg_keys=sorted(args.keys()),
        )
        return self._tool_message(
            tool_call.id,
            result,
            include_tool_meta=include_tool_meta,
        )

    def _normalize_tool_output(self, output: Any) -> ToolResult:
        if isinstance(output, ToolResult):
            return output
        if isinstance(output, BaseModel):
            return ToolResult(status="ok", data=output.model_dump(exclude_none=True))
        if isinstance(output, (dict, list)):
            return ToolResult(status="ok", data=output)
        if output is None:
            return ToolResult(status="ok", output="ok")
        return ToolResult(status="ok", output=str(output))

    def _build_tool_hint(
        self,
        tool_name: str,
        tools_by_name: dict[str, ToolSpec] | None,
    ) -> str | None:
        if not tools_by_name:
            return None
        spec = tools_by_name.get(tool_name)
        if not spec:
            return None
        params = spec.get("function", {}).get("parameters", {})
        required = params.get("required") or []
        properties = params.get("properties") or {}
        return (
            "Expected params: "
            + ", ".join(required)
            + ". Available fields: "
            + ", ".join(properties.keys())
        )

    def _allowed_tools_hint(self, tools_by_name: dict[str, ToolSpec]) -> str | None:
        if not tools_by_name:
            return None
        return "Allowed tools: " + ", ".join(sorted(tools_by_name.keys()))

    def _tool_message(
        self,
        tool_call_id: str,
        result: ToolResult,
        *,
        include_tool_meta: bool = False,
    ) -> dict[str, Any]:
        if include_tool_meta:
            payload = result.model_dump_json(exclude_none=True)
        else:
            payload = result.model_copy(update={"meta": None}).model_dump_json(
                exclude_none=True
            )
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": payload,
        }

    def _append_tool_budget_exceeded_messages(
        self,
        params: dict[str, Any],
        tool_calls: list[Any],
        *,
        tool_calls_executed: int,
        start_time: float,
        tool_call_limit: int,
    ) -> int:
        elapsed = max(0.0, time.monotonic() - start_time)
        appended = 0
        for tool_call in tool_calls:
            function = getattr(tool_call, "function", None)
            fn_name = getattr(function, "name", "unknown_tool")
            tool_call_id = getattr(tool_call, "id", None) or (
                f"tool_budget_exceeded_{tool_calls_executed + appended + 1}"
            )
            error = ToolError(
                message="Tool execution skipped because the tool budget was exceeded.",
                code="tool_budget_exceeded",
                hint="Proceed with the available context without additional tool calls.",
                retryable=False,
                details={
                    "tool": fn_name,
                    "executed_calls": tool_calls_executed,
                    "tool_call_limit": tool_call_limit,
                    "tool_call_timeout_seconds": self.tool_call_timeout_seconds,
                    "elapsed_seconds": round(elapsed, 3),
                },
            )
            result = ToolResult(
                status="error",
                error=error,
                meta={"tool": fn_name, "reason": "tool_budget_exceeded"},
            )
            params["messages"].append(
                self._tool_message(
                    tool_call_id,
                    result,
                    include_tool_meta=False,
                )
            )
            appended += 1
        return appended

    def _resolve_tool_call_limit(self, max_tool_calls: int | None) -> int:
        if max_tool_calls is None:
            return self.tool_call_limit
        try:
            return max(0, int(max_tool_calls))
        except (TypeError, ValueError):
            return self.tool_call_limit

    def _get_tool_mapping(self) -> dict[str, Callable[..., Any]]:
        if self._tool_mapping is not None:
            return self._tool_mapping
        try:
            self._tool_mapping = build_tool_mapping(
                embed_fn=self.embed,
                genai_client=self,
            )
            return self._tool_mapping
        except Exception as exc:  # pragma: no cover
            self.logger.exception("Failed to initialize tool mapping.")

            def _tool_init_failed(**_kwargs: Any) -> ToolResult:
                return ToolResult(
                    status="error",
                    error=ToolError(
                        message="Tooling backend is unavailable.",
                        code="tool_init_failed",
                        type=exc.__class__.__name__,
                        hint="Verify search and market-data settings and try again.",
                        retryable=False,
                        details={"error": str(exc)},
                    ),
                )

            fallback = {
                tool_name: _tool_init_failed
                for tool_name in self.chat_toolbox.tools_by_name.keys()
            }
            self._tool_mapping = fallback
            return self._tool_mapping

    def _message_to_dict(self, message: Any) -> dict[str, Any]:
        if isinstance(message, dict):
            return message
        if hasattr(message, "model_dump"):
            try:
                payload = message.model_dump(exclude_none=True)
            except Exception:
                payload = None
            if isinstance(payload, dict):
                return payload
        return {
            "role": getattr(message, "role", "assistant"),
            "content": getattr(message, "content", None),
            "tool_calls": self._tool_calls_to_dict(
                getattr(message, "tool_calls", None)
            ),
        }

    def _tool_calls_to_dict(self, tool_calls: Any) -> Any:
        if not isinstance(tool_calls, list):
            return tool_calls
        serialized: list[dict[str, Any]] = []
        for call in tool_calls:
            if isinstance(call, dict):
                serialized.append(call)
                continue
            function = getattr(call, "function", None)
            serialized.append(
                {
                    "id": getattr(call, "id", None),
                    "type": getattr(call, "type", "function"),
                    "function": {
                        "name": getattr(function, "name", None),
                        "arguments": getattr(function, "arguments", None),
                    },
                }
            )
        return serialized

    def _call_with_retries(self, params: dict[str, Any]):
        adjusted_for_temperature = False
        adjusted_for_max_tokens = False
        adjusted_for_context = False
        for attempt in range(1, self.max_retries + 1):
            try:
                self._ensure_context_budget(params)
                return self.client.chat.completions.create(**params)
            except Exception as exc:  # pragma: no cover
                if (
                    not adjusted_for_temperature
                    and self._should_retry_without_temperature(exc, params)
                ):
                    adjusted_for_temperature = True
                    params = self._drop_temperature(params)
                    self.logger.warning(
                        "OpenAI model rejected explicit temperature; retrying without temperature."
                    )
                    continue
                if (
                    not adjusted_for_max_tokens
                    and self._should_retry_with_max_completion_tokens(exc, params)
                ):
                    adjusted_for_max_tokens = True
                    params = self._replace_max_tokens(params)
                    self.logger.warning(
                        "OpenAI model rejected max_tokens; retrying with max_completion_tokens."
                    )
                    continue
                if (
                    not adjusted_for_context
                    and self._should_retry_after_context_compaction(exc, params)
                ):
                    adjusted_for_context = True
                    self._record_context_limit_from_error(exc, params.get("model"))
                    compacted = self._force_context_compaction(params)
                    self.logger.warning(
                        "OpenAI call exceeded context limit; compacted=%s and retrying once.",
                        compacted,
                    )
                    continue
                if not self._is_retryable_error(exc) or attempt == self.max_retries:
                    raise
                delay = self.retry_backoff_seconds * attempt
                self.logger.warning(
                    "OpenAI call failed (attempt %s/%s): %s. Retrying in %.1fs",
                    attempt,
                    self.max_retries,
                    exc,
                    delay,
                )
                time.sleep(delay)

        raise RuntimeError("Retries exhausted for OpenAI call.")

    @traceable(name="Structured LLM Call", run_type="parser")
    def _call_structured_response_with_retries(self, params: dict[str, Any]):
        adjusted_for_temperature = False
        adjusted_for_max_tokens = False
        adjusted_for_context = False
        for attempt in range(1, self.max_retries + 1):
            try:
                self._ensure_context_budget(params)
                if hasattr(self.client, "chat") and hasattr(
                    self.client.chat.completions, "parse"
                ):
                    return self.client.chat.completions.parse(**params)
                if hasattr(self.client, "beta"):
                    return self.client.beta.chat.completions.parse(**params)
                fallback_params = dict(params)
                fallback_params.pop("response_format", None)
                return self.client.chat.completions.create(**fallback_params)
            except Exception as exc:  # pragma: no cover
                if (
                    not adjusted_for_temperature
                    and self._should_retry_without_temperature(exc, params)
                ):
                    adjusted_for_temperature = True
                    params = self._drop_temperature(params)
                    self.logger.warning(
                        "OpenAI model rejected explicit temperature; retrying structured call without temperature."
                    )
                    continue
                if (
                    not adjusted_for_max_tokens
                    and self._should_retry_with_max_completion_tokens(exc, params)
                ):
                    adjusted_for_max_tokens = True
                    params = self._replace_max_tokens(params)
                    self.logger.warning(
                        "OpenAI model rejected max_tokens; retrying structured call with max_completion_tokens."
                    )
                    continue
                if (
                    not adjusted_for_context
                    and self._should_retry_after_context_compaction(exc, params)
                ):
                    adjusted_for_context = True
                    self._record_context_limit_from_error(exc, params.get("model"))
                    compacted = self._force_context_compaction(params)
                    self.logger.warning(
                        "OpenAI structured call exceeded context limit; compacted=%s "
                        "and retrying once.",
                        compacted,
                    )
                    continue
                if not self._is_retryable_error(exc) or attempt == self.max_retries:
                    raise
                delay = self.retry_backoff_seconds * attempt
                self.logger.warning(
                    "OpenAI structured call failed (attempt %s/%s): %s. Retrying in %.1fs",
                    attempt,
                    self.max_retries,
                    exc,
                    delay,
                )
                time.sleep(delay)

        raise RuntimeError("Retries exhausted for structured OpenAI call.")

    def _call_structured_with_retries(
        self,
        schema: type[BaseModel],
        *,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float | None,
        max_tokens: int | None,
    ) -> BaseModel:
        adjusted_for_temperature = False
        adjusted_for_max_tokens = False
        adjusted_for_context = False
        max_completion_tokens: int | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                params_for_budget: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                }
                if max_tokens is not None:
                    params_for_budget["max_tokens"] = max_tokens
                if max_completion_tokens is not None:
                    params_for_budget["max_completion_tokens"] = max_completion_tokens
                self._ensure_context_budget(params_for_budget)
                messages = params_for_budget["messages"]
                return self._call_structured_once(
                    schema,
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    max_completion_tokens=max_completion_tokens,
                )
            except Exception as exc:  # pragma: no cover
                if (
                    not adjusted_for_temperature
                    and self._should_retry_without_temperature(
                        exc,
                        {"model": model, "temperature": temperature},
                    )
                ):
                    adjusted_for_temperature = True
                    temperature = None
                    self.logger.warning(
                        "OpenAI model rejected explicit temperature; retrying structured parse call without temperature."
                    )
                    continue
                if (
                    not adjusted_for_max_tokens
                    and self._should_retry_with_max_completion_tokens(
                        exc,
                        {"model": model, "max_tokens": max_tokens},
                    )
                ):
                    adjusted_for_max_tokens = True
                    self.logger.warning(
                        "OpenAI model rejected max_tokens; retrying structured parse call with max_completion_tokens."
                    )
                    max_completion_tokens = (
                        None if max_tokens is None else int(max_tokens)
                    )
                    max_tokens = None
                    continue
                if not adjusted_for_context and is_context_length_error(exc):
                    adjusted_for_context = True
                    self._record_context_limit_from_error(exc, model)
                    params_for_budget = {
                        "model": model,
                        "messages": messages,
                    }
                    if max_tokens is not None:
                        params_for_budget["max_tokens"] = max_tokens
                    if max_completion_tokens is not None:
                        params_for_budget["max_completion_tokens"] = max_completion_tokens
                    compacted = self._force_context_compaction(params_for_budget)
                    messages = params_for_budget["messages"]
                    self.logger.warning(
                        "OpenAI structured parse call exceeded context limit; "
                        "compacted=%s and retrying once.",
                        compacted,
                    )
                    continue
                if not self._is_retryable_error(exc) or attempt == self.max_retries:
                    raise
                delay = self.retry_backoff_seconds * attempt
                self.logger.warning(
                    "OpenAI structured call failed (attempt %s/%s): %s. Retrying in %.1fs",
                    attempt,
                    self.max_retries,
                    exc,
                    delay,
                )
                time.sleep(delay)
        raise RuntimeError("Retries exhausted for structured OpenAI call.")

    @traceable(name="Structurization", run_type="parser")
    def _call_structured_once(
        self,
        schema: type[BaseModel],
        *,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float | None,
        max_tokens: int | None,
        max_completion_tokens: int | None = None,
    ) -> BaseModel:
        params = {
            "model": model,
            "messages": messages,
            "response_format": schema,
        }
        # if temperature is not None:               # in some OpenAI 5> models temperature is not supported anymore
        #     params["temperature"] = temperature
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        if max_completion_tokens is not None:
            params["max_completion_tokens"] = max_completion_tokens
        if hasattr(self.client, "chat") and hasattr(
            self.client.chat.completions, "parse"
        ):
            response = self.client.chat.completions.parse(**params)
            parsed = getattr(response, "output_parsed", None)
            if parsed is None:
                parsed = getattr(response.choices[0].message, "parsed", None)
            if parsed is not None:
                return parsed
            content = response.choices[0].message.content or "{}"
            return schema.model_validate_json(content)

        if (
            hasattr(self.client, "beta")
            and hasattr(self.client.beta, "chat")
            and hasattr(self.client.beta.chat.completions, "parse")
        ):
            response = self.client.beta.chat.completions.parse(**params)
            parsed = getattr(response, "output_parsed", None)
            if parsed is None:
                parsed = getattr(response.choices[0].message, "parsed", None)
            if parsed is not None:
                return parsed
            content = response.choices[0].message.content or "{}"
            return schema.model_validate_json(content)

        params.pop("response_format", None)
        response = self.client.chat.completions.create(**params)
        content = response.choices[0].message.content or "{}"
        return schema.model_validate_json(content)

    def _should_retry_without_temperature(
        self,
        exc: Exception,
        params: dict[str, Any],
    ) -> bool:
        if "temperature" not in params:
            return False

        message = str(exc).lower()
        if "temperature" not in message:
            return False

        unsupported_markers = (
            "does not support",
            "only the default",
            "unsupported_value",
        )
        return any(marker in message for marker in unsupported_markers)

    def _drop_temperature(self, params: dict[str, Any]) -> dict[str, Any]:
        updated = dict(params)
        updated.pop("temperature", None)
        return updated

    def _should_retry_with_max_completion_tokens(
        self,
        exc: Exception,
        params: dict[str, Any],
    ) -> bool:
        if "max_tokens" not in params:
            return False

        message = str(exc).lower()
        if "max_tokens" not in message:
            return False

        unsupported_markers = (
            "not supported with this model",
            "use 'max_completion_tokens' instead",
            "unsupported_parameter",
        )
        return any(marker in message for marker in unsupported_markers)

    def _should_retry_after_context_compaction(
        self,
        exc: Exception,
        params: dict[str, Any],
    ) -> bool:
        if not is_context_length_error(exc):
            return False
        messages = params.get("messages")
        return isinstance(messages, list) and bool(messages)

    def _replace_max_tokens(self, params: dict[str, Any]) -> dict[str, Any]:
        updated = dict(params)
        max_tokens = updated.pop("max_tokens", None)
        if max_tokens is not None:
            updated["max_completion_tokens"] = max_tokens
        return updated

    def _is_retryable_error(self, exc: Exception) -> bool:
        message = str(exc).lower()
        retry_markers = (
            "rate limit",
            "timeout",
            "temporarily unavailable",
            "server error",
            "502",
            "503",
            "504",
        )
        return any(marker in message for marker in retry_markers)

    def _build_messages(
        self,
        system_prompt: str,
        chat_message: str | dict[str, Any] | list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

        if isinstance(chat_message, str):
            messages.append({"role": "user", "content": chat_message})
        elif isinstance(chat_message, dict):
            messages.append(chat_message)
        elif isinstance(chat_message, list):
            messages.extend(chat_message)
        else:
            raise ValueError("chat_message is of unsupported type.")

        return messages

    def _ensure_context_budget(self, params: dict[str, Any]) -> None:
        model = params.get("model")
        messages = params.get("messages") or []
        if not model or not messages:
            return

        result = self._get_context_manager().ensure_budget(
            params,
            tier=self._context_tier_for_model(str(model)),
            summarizer=self._summarize_context_messages,
        )
        if result.changed:
            self.logger.warning(
                "Context tokens %s exceed budget %s for model %s; compacted messages "
                "(summary=%s truncation=%s).",
                result.input_tokens,
                result.budget_tokens,
                model,
                result.summary_used,
                result.fallback_truncated,
            )

    def _count_tokens_messages(self, messages: list[dict[str, Any]], model: str) -> int:
        return self._get_token_counter().count_messages(messages, model=model)

    def _encoding_for_model(self, model: str):
        return self._get_token_counter().encoding_for_model(model)

    def _get_token_counter(self) -> TokenCounter:
        counter = getattr(self, "token_counter", None)
        if isinstance(counter, TokenCounter):
            return counter
        counter = TokenCounter()
        self.token_counter = counter
        return counter

    def _get_context_manager(self) -> GenAIContextManager:
        manager = getattr(self, "context_manager", None)
        if isinstance(manager, GenAIContextManager):
            return manager
        manager = GenAIContextManager(
            token_counter=self._get_token_counter(),
            logger=getattr(self, "logger", logging.getLogger(__name__)),
        )
        self.context_manager = manager
        return manager

    def _context_tier_for_model(self, model: str) -> str | None:
        normalized = str(model or "").strip()
        if normalized and normalized == (self.settings.chat_model_default or "").strip():
            return "default"
        if normalized and normalized == (self.settings.chat_model_smart or "").strip():
            return "smart"
        if normalized and normalized == (self.settings.chat_model_reasoning or "").strip():
            return "reasoning"
        return None

    def _truncate_messages(
        self,
        messages: list[dict[str, Any]],
        model: str,
        budget: int,
    ) -> list[dict[str, Any]]:
        return self._get_context_manager().truncate_messages(
            messages,
            model=model,
            budget_tokens=budget,
        )

    def _force_context_compaction(self, params: dict[str, Any]) -> bool:
        model = str(params.get("model") or "")
        messages_before = params.get("messages")
        if not model or not isinstance(messages_before, list) or not messages_before:
            return False
        result = self._get_context_manager().ensure_budget(
            params,
            tier=self._context_tier_for_model(model),
            summarizer=self._summarize_context_messages,
            force=True,
        )
        return result.changed

    def _record_context_limit_from_error(
        self,
        exc: Exception,
        model: str | None,
    ) -> int | None:
        limit = parse_context_limit_from_error(exc)
        if limit is not None:
            self._get_context_manager().resolver.record_runtime_limit(model, limit)
        return limit

    def _summarize_context_messages(
        self,
        messages: list[dict[str, Any]],
        model: str,
        max_tokens: int,
    ) -> str:
        summary_model = self._default_chat_model()
        manager = self._get_context_manager()
        source_budget = max(2_048, min(32_000, manager.resolver.resolve(summary_model) // 4))
        source = manager.render_messages_for_summary(
            messages,
            model=summary_model,
            max_tokens=source_budget,
        )
        if not source.strip():
            return ""

        params: dict[str, Any] = {
            "model": summary_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You compress prior conversation and tool context for a trading "
                        "assistant. Preserve user intent, decisions, constraints, tool "
                        "results, unresolved errors, and next actions. Be concise."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Summarize the following older context so another model can "
                        "continue the same task without seeing the raw messages.\n\n"
                        f"{source}"
                    ),
                },
            ],
            "max_tokens": max_tokens,
        }
        try:
            response = self.client.chat.completions.create(**params)
        except Exception as exc:
            if self._should_retry_with_max_completion_tokens(exc, params):
                response = self.client.chat.completions.create(
                    **self._replace_max_tokens(params)
                )
            else:
                raise
        return str(response.choices[0].message.content or "").strip()
