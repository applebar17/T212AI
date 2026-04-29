from __future__ import annotations

from t212ai.genai.client import GenAIClient, GenAISettings


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
