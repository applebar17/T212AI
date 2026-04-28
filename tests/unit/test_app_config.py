from __future__ import annotations

import os

from t212ai.app.config import get_app_settings, load_env_file, parse_env_file


def test_parse_env_file_supports_quotes_export_and_comments(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# comment",
                "export T212_ENVIRONMENT=live",
                "T212_API_KEY='key with spaces'",
                'T212_API_SECRET="secret#not-comment"',
                "DATABASE_URL=sqlite:///./data/app.db # local db",
                "INVALID_LINE",
            ]
        ),
        encoding="utf-8",
    )

    parsed = parse_env_file(env_file)

    assert parsed["T212_ENVIRONMENT"] == "live"
    assert parsed["T212_API_KEY"] == "key with spaces"
    assert parsed["T212_API_SECRET"] == "secret#not-comment"
    assert parsed["DATABASE_URL"] == "sqlite:///./data/app.db"
    assert "INVALID_LINE" not in parsed


def test_load_env_file_keeps_process_environment_precedence(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "T212_ENVIRONMENT=live\nT212_API_KEY=file-key\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("T212_ENVIRONMENT", "demo")
    monkeypatch.delenv("T212_API_KEY", raising=False)

    loaded = load_env_file(env_file)

    assert loaded["T212_ENVIRONMENT"] == "live"
    assert os.environ["T212_ENVIRONMENT"] == "demo"
    assert os.environ["T212_API_KEY"] == "file-key"


def test_get_app_settings_loads_values_from_env_file(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "LLM_PROVIDER=openai",
                "BROKER_PROVIDER=trading212",
                "T212_ENVIRONMENT=live",
                "T212_LIVE_BASE_URL=https://live.example/api/v0",
                "T212_API_KEY=file-key",
                "T212_API_SECRET=file-secret",
                "TELEGRAM_ALLOWED_CHAT_ID=123",
                "TELEGRAM_ALLOWED_USER_ID=999",
                "YAHOO_ENABLED=true",
                "ALPHA_VANTAGE_ENABLED=true",
                "ALPHA_VANTAGE_API_KEY=alpha-key",
                "REDDIT_ENABLED=true",
                "REDDIT_CLIENT_ID=reddit-client",
                "REDDIT_CLIENT_SECRET=reddit-secret",
                "REDDIT_USER_AGENT=server:t212ai:test (by /u/tester)",
                "SEARXNG_ENABLED=true",
                "SEARXNG_BASE_URL=https://search.example",
                "GUIDELINE_MEMORY_PATH=data/guidelines/test-guidelines.json",
                "T212_LIVE_TRADING_ENABLED=true",
            ]
        ),
        encoding="utf-8",
    )
    for key in [
        "LLM_PROVIDER",
        "BROKER_PROVIDER",
        "T212_ENVIRONMENT",
        "T212_LIVE_BASE_URL",
        "T212_API_KEY",
        "T212_API_SECRET",
        "TELEGRAM_ALLOWED_CHAT_ID",
        "TELEGRAM_ALLOWED_USER_ID",
        "YAHOO_ENABLED",
        "ALPHA_VANTAGE_ENABLED",
        "ALPHA_VANTAGE_API_KEY",
        "REDDIT_ENABLED",
        "REDDIT_CLIENT_ID",
        "REDDIT_CLIENT_SECRET",
        "REDDIT_USER_AGENT",
        "SEARXNG_ENABLED",
        "SEARXNG_BASE_URL",
        "GUIDELINE_MEMORY_PATH",
        "T212_LIVE_TRADING_ENABLED",
    ]:
        monkeypatch.delenv(key, raising=False)

    settings = get_app_settings(env_file=env_file)

    assert settings.llm_provider == "openai"
    assert settings.broker_provider == "trading212"
    assert settings.trading212_environment == "live"
    assert settings.trading212_base_url == "https://live.example/api/v0"
    assert settings.trading212_api_key == "file-key"
    assert settings.trading212_api_secret == "file-secret"
    assert settings.telegram_allowed_chat_id == "123"
    assert settings.telegram_allowed_user_id == "999"
    assert settings.yahoo_enabled
    assert settings.alpha_vantage_enabled
    assert settings.alpha_vantage_api_key == "alpha-key"
    assert settings.reddit_enabled
    assert settings.reddit_client_id == "reddit-client"
    assert settings.reddit_client_secret == "reddit-secret"
    assert settings.reddit_user_agent == "server:t212ai:test (by /u/tester)"
    assert settings.searxng_enabled
    assert settings.searxng_base_url == "https://search.example"
    assert settings.guideline_memory_path == "data/guidelines/test-guidelines.json"
    assert settings.live_trading_enabled


def test_get_app_settings_can_use_explicit_env_mapping_without_mutation(monkeypatch) -> None:
    monkeypatch.delenv("T212_ENVIRONMENT", raising=False)
    settings = get_app_settings(
        env={
            "T212_ENVIRONMENT": "live",
            "T212_LIVE_TRADING_ENABLED": "yes",
        }
    )

    assert settings.trading212_environment == "live"
    assert settings.live_trading_enabled
    assert "T212_ENVIRONMENT" not in os.environ


def test_get_app_settings_uses_default_guideline_memory_path() -> None:
    settings = get_app_settings(env={})

    assert settings.guideline_memory_path == "data/guidelines/guidelines.json"
    assert settings.market_data_provider == "yahoo"
    assert settings.disclosure_provider == "sec_edgar"
    assert settings.market_intelligence_provider == "none"
    assert settings.community_provider == "none"
    assert settings.search_provider == "none"
    assert settings.yahoo_enabled


def test_get_app_settings_infers_provider_selectors_from_existing_keys() -> None:
    settings = get_app_settings(
        env={
            "OPENAI_API_KEY": "openai-key",
            "T212_API_SECRET": "secret",
            "ALPHA_VANTAGE_API_KEY": "alpha-key",
            "REDDIT_CLIENT_ID": "reddit-id",
            "SEARXNG_BASE_URL": "https://search.example",
        }
    )

    assert settings.llm_provider == "openai"
    assert settings.broker_provider == "trading212"
    assert settings.market_data_provider == "yahoo"
    assert settings.market_intelligence_provider == "alpha_vantage"
    assert settings.community_provider == "reddit"
    assert settings.search_provider == "searxng"
    assert settings.disclosure_provider == "sec_edgar"
    assert settings.alpha_vantage_enabled
    assert settings.reddit_enabled
    assert settings.searxng_enabled


def test_get_app_settings_explicit_capability_selectors_override_legacy_flags() -> None:
    settings = get_app_settings(
        env={
            "MARKET_DATA_PROVIDER": "none",
            "DISCLOSURE_PROVIDER": "none",
            "COMMUNITY_PROVIDER": "none",
            "SEARCH_PROVIDER": "none",
            "MARKET_INTELLIGENCE_PROVIDER": "none",
            "YAHOO_ENABLED": "true",
            "ALPHA_VANTAGE_ENABLED": "true",
            "ALPHA_VANTAGE_API_KEY": "alpha-key",
            "REDDIT_ENABLED": "true",
            "REDDIT_CLIENT_ID": "reddit-id",
            "SEARXNG_ENABLED": "true",
            "SEARXNG_BASE_URL": "https://search.example",
        }
    )

    assert settings.market_data_provider == "none"
    assert settings.disclosure_provider == "none"
    assert settings.market_intelligence_provider == "none"
    assert settings.community_provider == "none"
    assert settings.search_provider == "none"
    assert not settings.yahoo_enabled
    assert not settings.alpha_vantage_enabled
    assert not settings.reddit_enabled
    assert not settings.searxng_enabled
