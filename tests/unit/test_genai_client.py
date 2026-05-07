from __future__ import annotations

import logging
from types import SimpleNamespace

from t212ai.genai.client import GenAIClient, GenAISettings
from t212ai.genai.context import (
    ContextBudgetResolver,
    GenAIContextManager,
    ModelContextRegistry,
    PRIOR_CONTEXT_SUMMARY_HEADER,
    parse_context_token_value,
    parse_context_tokens_by_model_json,
)
from t212ai.genai.tokenizer import TokenCounter
from t212ai.genai.tools.base import ToolBox, build_tool_index, render_tool_descriptions


def test_chat_model_for_falls_back_to_default_when_optional_models_are_blank() -> None:
    client = GenAIClient.__new__(GenAIClient)
    client.settings = GenAISettings(
        chat_model_default="base-model",
        chat_model_smart="",
        chat_model_reasoning="",
    )

    assert client.chat_model_for("default") == "base-model"
    assert client.chat_model_for("smart") == "base-model"
    assert client.chat_model_for("reasoning") == "base-model"


def test_context_resolver_prefers_tier_then_model_then_registry_then_fallback() -> None:
    resolver = ContextBudgetResolver(
        tier_context_tokens={"smart": 222_000},
        model_context_tokens={"custom-model": 333_000},
        fallback_tokens=128_000,
    )

    assert resolver.resolve("custom-model", tier="smart") == 222_000
    assert resolver.resolve("custom-model") == 333_000
    assert resolver.resolve("gpt-4.1") == 1_047_576
    assert resolver.resolve("unknown-model") == 128_000


def test_context_registry_matches_only_exact_or_date_snapshot_aliases() -> None:
    registry = ModelContextRegistry()

    assert registry.lookup("gpt-4.1-2025-04-14") == 1_047_576
    assert registry.lookup("my-gpt-4.1-deployment") is None


def test_context_token_parsing_rejects_invalid_or_too_small_values() -> None:
    assert parse_context_token_value("64000") is None
    assert parse_context_token_value("not-an-int") is None
    assert parse_context_tokens_by_model_json("{bad json") == {}
    assert parse_context_tokens_by_model_json('{"custom": 200000, "bad": 1}') == {
        "custom": 200_000
    }


def test_context_manager_summarizes_older_messages_and_preserves_recent_flow() -> None:
    counter = TokenCounter(
        tiktoken_module=None,
        fallback_chars_per_token=1,
        message_overhead_tokens=0,
    )
    manager = GenAIContextManager(
        resolver=ContextBudgetResolver(fallback_tokens=80),
        token_counter=counter,
        guard_ratio=1.0,
        output_reserve_tokens=0,
        recent_messages=2,
        summary_max_tokens=16,
    )
    params = {
        "model": "tiny",
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "x" * 120},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "new"},
            {"role": "assistant", "content": "answer"},
        ],
    }

    result = manager.ensure_budget(
        params,
        summarizer=lambda _messages, _model, _max_tokens: "old compressed",
    )

    assert result.changed
    assert result.summary_used
    assert params["messages"][0] == {"role": "system", "content": "sys"}
    assert params["messages"][1]["role"] == "user"
    assert PRIOR_CONTEXT_SUMMARY_HEADER in params["messages"][1]["content"]
    assert params["messages"][-2:] == [
        {"role": "user", "content": "new"},
        {"role": "assistant", "content": "answer"},
    ]


def test_context_manager_falls_back_to_truncation_when_summary_fails() -> None:
    counter = TokenCounter(
        tiktoken_module=None,
        fallback_chars_per_token=1,
        message_overhead_tokens=0,
    )
    manager = GenAIContextManager(
        resolver=ContextBudgetResolver(fallback_tokens=30),
        token_counter=counter,
        guard_ratio=1.0,
        output_reserve_tokens=0,
        recent_messages=2,
        summary_max_tokens=16,
    )
    params = {
        "model": "tiny",
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "x" * 120},
            {"role": "user", "content": "new"},
            {"role": "assistant", "content": "answer"},
        ],
    }

    result = manager.ensure_budget(
        params,
        summarizer=lambda _messages, _model, _max_tokens: (_ for _ in ()).throw(
            RuntimeError("summary failed")
        ),
    )

    assert result.changed
    assert result.fallback_truncated
    assert params["messages"][0] == {"role": "system", "content": "sys"}
    assert all(PRIOR_CONTEXT_SUMMARY_HEADER not in str(message) for message in params["messages"])
    assert params["messages"][-1] == {"role": "assistant", "content": "answer"}


def test_handle_params_strips_parallel_tool_calls_without_tools() -> None:
    client = GenAIClient.__new__(GenAIClient)
    client.settings = GenAISettings(chat_model_default="base-model")
    client._ensure_context_budget = lambda _params: None

    params = client.handle_params(
        "system",
        [{"role": "user", "content": "hello"}],
        parallel_tool_calls=False,
    )

    assert "tools" not in params
    assert "parallel_tool_calls" not in params


def test_call_with_retries_compacts_once_after_context_length_error() -> None:
    counter = TokenCounter(
        tiktoken_module=None,
        fallback_chars_per_token=1,
        message_overhead_tokens=0,
    )

    class FakeCompletions:
        def __init__(self) -> None:
            self.calls = 0
            self.last_params = {}

        def create(self, **params):
            self.calls += 1
            self.last_params = params
            if self.calls == 1:
                raise RuntimeError(
                    "This model's maximum context length is 180 tokens. "
                    "Please reduce your prompt."
                )
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content="final answer"))
                ]
            )

    completions = FakeCompletions()
    client = GenAIClient.__new__(GenAIClient)
    client.settings = GenAISettings(chat_model_default="tiny")
    client.logger = logging.getLogger(__name__)
    client.token_counter = counter
    client.context_manager = GenAIContextManager(
        resolver=ContextBudgetResolver(fallback_tokens=1_000),
        token_counter=counter,
        guard_ratio=1.0,
        output_reserve_tokens=0,
        recent_messages=2,
        summary_max_tokens=32,
    )
    client.client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    client.max_retries = 2
    client.retry_backoff_seconds = 0
    client._summarize_context_messages = (
        lambda _messages, _model, _max_tokens: "compressed older context"
    )
    params = {
        "model": "tiny",
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "x" * 500},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "new"},
            {"role": "assistant", "content": "answer"},
        ],
    }

    response = client._call_with_retries(params)

    assert response.choices[0].message.content == "final answer"
    assert completions.calls == 2
    assert client.context_manager.resolver.resolve("tiny") == 180
    assert PRIOR_CONTEXT_SUMMARY_HEADER in completions.last_params["messages"][1]["content"]


def test_render_tool_descriptions_softens_restrictive_phrasing() -> None:
    tool = {
        "type": "function",
        "function": {
            "name": "example_tool",
            "description": "Example tool.",
            "parameters": {
                "type": "object",
                "properties": {
                    "value": {
                        "type": "string",
                        "description": "Do not pass formulas. Only resolved values.",
                    }
                },
                "required": ["value"],
                "additionalProperties": False,
            },
        },
    }
    toolbox = ToolBox(
        name="example",
        tools=[tool],
        tools_by_name=build_tool_index([tool]),
    )

    rendered = render_tool_descriptions(toolbox, include_parameters=True)

    assert "Use resolved values rather than formulas" in rendered
    assert "Do not" not in rendered


def test_render_tool_descriptions_omits_parameters_by_default() -> None:
    tool = {
        "type": "function",
        "function": {
            "name": "example_tool",
            "description": "Example tool.",
            "parameters": {
                "type": "object",
                "properties": {
                    "value": {"type": "string", "description": "Verbose input detail."}
                },
                "required": ["value"],
            },
        },
    }
    toolbox = ToolBox(
        name="example",
        tools=[tool],
        tools_by_name=build_tool_index([tool]),
    )

    rendered = render_tool_descriptions(toolbox)

    assert "example_tool" in rendered
    assert "Example tool." in rendered
    assert "inputs:" not in rendered
    assert "Verbose input detail" not in rendered


def test_message_to_dict_falls_back_when_model_dump_raises() -> None:
    client = GenAIClient.__new__(GenAIClient)

    class BrokenMessage:
        role = "assistant"
        content = None
        tool_calls = [
            SimpleNamespace(
                id="call_123",
                type="function",
                function=SimpleNamespace(
                    name="delegate_to_portfolio_analyst",
                    arguments='{"task_brief":"check portfolio"}',
                ),
            )
        ]

        def model_dump(self, **_kwargs):
            raise TypeError("super(type, obj): obj must be an instance or subtype of type")

    payload = client._message_to_dict(BrokenMessage())

    assert payload["role"] == "assistant"
    assert payload["content"] is None
    assert payload["tool_calls"] == [
        {
            "id": "call_123",
            "type": "function",
            "function": {
                "name": "delegate_to_portfolio_analyst",
                "arguments": '{"task_brief":"check portfolio"}',
            },
        }
    ]
