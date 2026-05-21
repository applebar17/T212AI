"""Message building and context-budget operations for GenAI calls."""

from __future__ import annotations

import logging
from typing import Any

from t212ai.genai.context import GenAIContextManager, parse_context_limit_from_error
from t212ai.genai.tokenizer import TokenCounter


class GenAIContextMixin:
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
