"""Reusable GenAI helpers, client wrapper, and token utilities.

This package intentionally avoids eager imports so submodules such as
`t212ai.genai.models` can be imported without constructing the full client/tool
stack and triggering circular imports.
"""

from __future__ import annotations

from typing import Any


__all__ = [
    "GenAIClient",
    "GenAISettings",
    "genai_settings_from_app_settings",
    "get_genai_settings",
    "TokenCounter",
    "ContextBudgetResolver",
    "GenAIContextManager",
    "ModelContextRegistry",
    "count_text_tokens",
    "count_content_tokens",
    "count_message_tokens",
    "count_messages_tokens",
]


def __getattr__(name: str) -> Any:
    if name in {
        "GenAIClient",
        "GenAISettings",
        "genai_settings_from_app_settings",
        "get_genai_settings",
    }:
        from .client import (
            GenAIClient,
            GenAISettings,
            genai_settings_from_app_settings,
            get_genai_settings,
        )

        exports = {
            "GenAIClient": GenAIClient,
            "GenAISettings": GenAISettings,
            "genai_settings_from_app_settings": genai_settings_from_app_settings,
            "get_genai_settings": get_genai_settings,
        }
        return exports[name]

    if name in {
        "ContextBudgetResolver",
        "GenAIContextManager",
        "ModelContextRegistry",
    }:
        from .context import (
            ContextBudgetResolver,
            GenAIContextManager,
            ModelContextRegistry,
        )

        exports = {
            "ContextBudgetResolver": ContextBudgetResolver,
            "GenAIContextManager": GenAIContextManager,
            "ModelContextRegistry": ModelContextRegistry,
        }
        return exports[name]

    if name in {
        "TokenCounter",
        "count_text_tokens",
        "count_content_tokens",
        "count_message_tokens",
        "count_messages_tokens",
    }:
        from .tokenizer import (
            TokenCounter,
            count_content_tokens,
            count_message_tokens,
            count_messages_tokens,
            count_text_tokens,
        )

        exports = {
            "TokenCounter": TokenCounter,
            "count_text_tokens": count_text_tokens,
            "count_content_tokens": count_content_tokens,
            "count_message_tokens": count_message_tokens,
            "count_messages_tokens": count_messages_tokens,
        }
        return exports[name]

    raise AttributeError(f"module 't212ai.genai' has no attribute {name!r}")
