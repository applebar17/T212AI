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
                "MARKET_DATA_PROVIDER=yahoo",
                "MARKET_INTELLIGENCE_PROVIDER=alpha_vantage",
                "COMMUNITY_PROVIDER=reddit",
                "SEARCH_PROVIDER=searxng",
                "T212_ENVIRONMENT=live",
                "T212_LIVE_BASE_URL=https://live.example/api/v0",
                "T212_LIVE_API_KEY=file-live-key",
                "T212_LIVE_API_SECRET=file-live-secret",
                "T212_DEMO_API_KEY=file-demo-key",
                "T212_DEMO_API_SECRET=file-demo-secret",
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
        "MARKET_DATA_PROVIDER",
        "MARKET_INTELLIGENCE_PROVIDER",
        "COMMUNITY_PROVIDER",
        "SEARCH_PROVIDER",
        "T212_ENVIRONMENT",
        "T212_LIVE_BASE_URL",
        "T212_LIVE_API_KEY",
        "T212_LIVE_API_SECRET",
        "T212_DEMO_API_KEY",
        "T212_DEMO_API_SECRET",
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
        "ALPACA_ENVIRONMENT",
        "ALPACA_API_KEY",
        "ALPACA_API_SECRET",
        "ALPACA_PAPER_API_KEY",
        "ALPACA_PAPER_API_SECRET",
        "ALPACA_LIVE_API_KEY",
        "ALPACA_LIVE_API_SECRET",
    ]:
        monkeypatch.delenv(key, raising=False)

    settings = get_app_settings(env_file=env_file)

    assert settings.llm_provider == "openai"
    assert settings.broker_provider == "trading212"
    assert settings.trading212_environment == "live"
    assert settings.trading212_base_url == "https://live.example/api/v0"
    assert settings.trading212_api_key == "file-live-key"
    assert settings.trading212_api_secret == "file-live-secret"
    assert settings.trading212_live_api_key == "file-live-key"
    assert settings.trading212_live_api_secret == "file-live-secret"
    assert settings.trading212_demo_api_key == "file-demo-key"
    assert settings.trading212_demo_api_secret == "file-demo-secret"
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


def test_get_app_settings_loads_genai_context_settings() -> None:
    settings = get_app_settings(
        env={
            "GENAI_CONTEXT_TOKENS_DEFAULT": "200000",
            "GENAI_CONTEXT_TOKENS_SMART": "300000",
            "GENAI_CONTEXT_TOKENS_REASONING": "400000",
            "GENAI_CONTEXT_TOKENS_BY_MODEL_JSON": '{"custom":250000}',
            "GENAI_CONTEXT_FALLBACK_TOKENS": "128000",
            "GENAI_CONTEXT_GUARD_RATIO": "0.9",
            "GENAI_OUTPUT_RESERVE_TOKENS": "2048",
            "GENAI_CONTEXT_RECENT_MESSAGES": "16",
            "GENAI_CONTEXT_SUMMARY_MAX_TOKENS": "1536",
        }
    )

    assert settings.genai_context_tokens_default == "200000"
    assert settings.genai_context_tokens_smart == "300000"
    assert settings.genai_context_tokens_reasoning == "400000"
    assert settings.genai_context_tokens_by_model_json == '{"custom":250000}'
    assert settings.genai_context_fallback_tokens == "128000"
    assert settings.genai_context_guard_ratio == "0.9"
    assert settings.genai_output_reserve_tokens == "2048"
    assert settings.genai_context_recent_messages == "16"
    assert settings.genai_context_summary_max_tokens == "1536"


def test_get_app_settings_loads_scheduler_defaults() -> None:
    settings = get_app_settings(
        env={
            "SCHEDULER_DEFAULT_TIMEZONE": "Europe/Rome",
            "SCHEDULER_DEFAULT_POLL_EVERY_SECONDS": "900",
        }
    )

    assert settings.scheduler_default_timezone == "Europe/Rome"
    assert settings.scheduler_default_poll_every_seconds == 900


def test_get_app_settings_infers_provider_selectors_from_existing_keys() -> None:
    settings = get_app_settings(
        env={
            "OPENAI_API_KEY": "openai-key",
            "T212_LIVE_API_SECRET": "secret",
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


def test_get_app_settings_supports_explicit_alpaca_market_data_provider() -> None:
    settings = get_app_settings(
        env={
            "MARKET_DATA_PROVIDER": "alpaca",
            "ALPACA_LIVE_API_KEY": "alpaca-live-key",
            "ALPACA_LIVE_API_SECRET": "alpaca-live-secret",
            "ALPACA_ENVIRONMENT": "live",
            "ALPACA_DATA_FEED": "sip",
        }
    )

    assert settings.market_data_provider == "alpaca"
    assert settings.alpaca_api_key == "alpaca-live-key"
    assert settings.alpaca_api_secret == "alpaca-live-secret"
    assert settings.alpaca_environment == "live"
    assert settings.alpaca_data_feed == "sip"
    assert not settings.yahoo_enabled


def test_get_app_settings_requires_explicit_alpaca_market_data_provider() -> None:
    settings = get_app_settings(
        env={
            "ALPACA_API_KEY": "alpaca-key",
            "ALPACA_API_SECRET": "alpaca-secret",
        }
    )

    assert settings.market_data_provider == "yahoo"
    assert settings.yahoo_enabled


def test_get_app_settings_supports_explicit_alpaca_broker_provider() -> None:
    settings = get_app_settings(
        env={
            "BROKER_PROVIDER": "alpaca",
            "ALPACA_LIVE_API_KEY": "alpaca-live-key",
            "ALPACA_LIVE_API_SECRET": "alpaca-live-secret",
            "ALPACA_ENVIRONMENT": "live",
        }
    )

    assert settings.broker_provider == "alpaca"
    assert settings.alpaca_api_key == "alpaca-live-key"
    assert settings.alpaca_api_secret == "alpaca-live-secret"
    assert settings.alpaca_environment == "live"
    assert settings.market_data_provider == "yahoo"


def test_get_app_settings_prefers_environment_specific_broker_credentials() -> None:
    settings = get_app_settings(
        env={
            "BROKER_PROVIDER": "trading212",
            "T212_ENVIRONMENT": "demo",
            "T212_DEMO_API_KEY": "demo-key",
            "T212_DEMO_API_SECRET": "demo-secret",
            "T212_LIVE_API_KEY": "live-key",
            "T212_LIVE_API_SECRET": "live-secret",
            "ALPACA_ENVIRONMENT": "paper",
            "ALPACA_PAPER_API_KEY": "paper-key",
            "ALPACA_PAPER_API_SECRET": "paper-secret",
            "ALPACA_LIVE_API_KEY": "alpaca-live-key",
            "ALPACA_LIVE_API_SECRET": "alpaca-live-secret",
        }
    )

    assert settings.trading212_api_key == "demo-key"
    assert settings.trading212_api_secret == "demo-secret"
    assert settings.alpaca_api_key == "paper-key"
    assert settings.alpaca_api_secret == "paper-secret"


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
