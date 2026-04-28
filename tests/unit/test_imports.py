def test_baseline_imports() -> None:
    from t212ai.agent.intents import AgentIntent, IntentKind
    from t212ai.app.config import get_app_settings
    import t212ai.genai.tools as genai_tools
    from t212ai.genai.tools import CHAT_TOOLBOX
    from t212ai.telegram.commands import HELP_COMMANDS

    assert get_app_settings().trading212_environment
    assert CHAT_TOOLBOX.name == "chat"
    assert "market_get_quote" in genai_tools.__all__
    assert "broker_get_portfolio_snapshot" in genai_tools.__all__
    assert "yahoo_quote_snapshot" not in genai_tools.__all__
    assert "YAHOO_MARKET_CONTEXT_TOOLBOX" not in genai_tools.__all__
    assert "/help" in HELP_COMMANDS
    assert AgentIntent(kind=IntentKind.HELP, confidence=1.0).kind == IntentKind.HELP
