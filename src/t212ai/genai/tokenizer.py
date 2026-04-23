"""Token counting helpers with optional tiktoken support."""

from __future__ import annotations

import json
from typing import Any

try:  # pragma: no cover - optional dependency
    import tiktoken  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    tiktoken = None  # type: ignore


DEFAULT_FALLBACK_ENCODING = "cl100k_base"
DEFAULT_MESSAGE_OVERHEAD_TOKENS = 3
DEFAULT_CHARS_PER_TOKEN = 4


class TokenCounter:
    """Reusable token counter for plain text and chat-style messages."""

    def __init__(
        self,
        *,
        fallback_encoding_name: str = DEFAULT_FALLBACK_ENCODING,
        message_overhead_tokens: int = DEFAULT_MESSAGE_OVERHEAD_TOKENS,
        fallback_chars_per_token: int = DEFAULT_CHARS_PER_TOKEN,
        tiktoken_module: Any | None = tiktoken,
    ) -> None:
        self.fallback_encoding_name = fallback_encoding_name
        self.message_overhead_tokens = int(message_overhead_tokens)
        self.fallback_chars_per_token = max(1, int(fallback_chars_per_token))
        self._tiktoken = tiktoken_module
        self._encoding_cache: dict[str, Any] = {}

    def encoding_for_model(self, model: str | None = None) -> Any | None:
        key = str(model or "").strip()
        if key in self._encoding_cache:
            return self._encoding_cache[key]

        encoding = self._resolve_encoding(key)
        self._encoding_cache[key] = encoding
        return encoding

    def count_text(
        self,
        text: str,
        *,
        model: str | None = None,
        encoding: Any | None = None,
    ) -> int:
        if not text:
            return 0
        resolved_encoding = encoding or self.encoding_for_model(model)
        if resolved_encoding is None:
            return max(1, len(text) // self.fallback_chars_per_token)
        return len(resolved_encoding.encode(text))

    def count_content(
        self,
        content: Any,
        *,
        model: str | None = None,
        encoding: Any | None = None,
    ) -> int:
        if content is None:
            return 0
        if isinstance(content, str):
            return self.count_text(content, model=model, encoding=encoding)
        try:
            serialized = json.dumps(content)
        except Exception:
            serialized = str(content)
        return self.count_text(serialized, model=model, encoding=encoding)

    def count_message(
        self,
        message: dict[str, Any],
        *,
        model: str | None = None,
        encoding: Any | None = None,
        message_overhead_tokens: int | None = None,
    ) -> int:
        overhead = (
            self.message_overhead_tokens
            if message_overhead_tokens is None
            else int(message_overhead_tokens)
        )
        content = None
        if isinstance(message, dict):
            content = message.get("content")
        return self.count_content(content, model=model, encoding=encoding) + overhead

    def count_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        encoding: Any | None = None,
        message_overhead_tokens: int | None = None,
    ) -> int:
        resolved_encoding = encoding or self.encoding_for_model(model)
        return sum(
            self.count_message(
                message,
                model=model,
                encoding=resolved_encoding,
                message_overhead_tokens=message_overhead_tokens,
            )
            for message in messages
        )

    def _resolve_encoding(self, model: str) -> Any | None:
        if self._tiktoken is None:
            return None
        if model:
            try:
                return self._tiktoken.encoding_for_model(model)
            except Exception:
                pass
        try:
            return self._tiktoken.get_encoding(self.fallback_encoding_name)
        except Exception:
            return None


_DEFAULT_COUNTER = TokenCounter()


def count_text_tokens(
    text: str,
    *,
    model: str | None = None,
    encoding: Any | None = None,
) -> int:
    return _DEFAULT_COUNTER.count_text(text, model=model, encoding=encoding)


def count_content_tokens(
    content: Any,
    *,
    model: str | None = None,
    encoding: Any | None = None,
) -> int:
    return _DEFAULT_COUNTER.count_content(content, model=model, encoding=encoding)


def count_message_tokens(
    message: dict[str, Any],
    *,
    model: str | None = None,
    encoding: Any | None = None,
    message_overhead_tokens: int | None = None,
) -> int:
    return _DEFAULT_COUNTER.count_message(
        message,
        model=model,
        encoding=encoding,
        message_overhead_tokens=message_overhead_tokens,
    )


def count_messages_tokens(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    encoding: Any | None = None,
    message_overhead_tokens: int | None = None,
) -> int:
    return _DEFAULT_COUNTER.count_messages(
        messages,
        model=model,
        encoding=encoding,
        message_overhead_tokens=message_overhead_tokens,
    )


__all__ = [
    "TokenCounter",
    "count_text_tokens",
    "count_content_tokens",
    "count_message_tokens",
    "count_messages_tokens",
]
