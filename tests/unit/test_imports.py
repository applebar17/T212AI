def test_baseline_imports() -> None:
    from t212ai.agent.intents import AgentIntent, IntentKind
    from t212ai.app.config import get_app_settings
    from t212ai.genai.tools import CHAT_TOOLBOX
    from t212ai.telegram.commands import HELP_COMMANDS

    assert get_app_settings().trading212_environment
    assert CHAT_TOOLBOX.name == "chat"
    assert "/help" in HELP_COMMANDS
    assert AgentIntent(kind=IntentKind.HELP, confidence=1.0).kind == IntentKind.HELP

