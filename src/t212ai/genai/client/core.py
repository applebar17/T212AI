"""OpenAI/Azure GenAI client wrapper with tools and token guardrails."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, Iterable

from pydantic import BaseModel

from t212ai.app.logging import log_event
from t212ai.genai.context import ContextBudgetResolver, GenAIContextManager
from t212ai.genai.models import ToolSpec
from t212ai.genai.tokenizer import TokenCounter
from t212ai.genai.tools import ToolBox, build_chat_toolbox
from t212ai.genai.tracing import traceable

from .context_ops import GenAIContextMixin
from .diagnostics import _llm_prompt_diagnostics
from .errors import _provider_error_details
from .retrying import GenAIRetryMixin
from .settings import GenAISettings, get_genai_settings
from .tool_execution import GenAIToolExecutionMixin

try:
    from langsmith.wrappers import wrap_openai  # type: ignore
except Exception:  # pragma: no cover - tracing is optional
    wrap_openai = None  # type: ignore


class GenAIClient(GenAIToolExecutionMixin, GenAIRetryMixin, GenAIContextMixin):
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
