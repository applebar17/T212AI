from __future__ import annotations

from types import SimpleNamespace

from t212ai.genai.client import GenAIClient, GenAISettings
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
