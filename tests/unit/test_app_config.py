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
                "T212_ENVIRONMENT=live",
                "T212_LIVE_BASE_URL=https://live.example/api/v0",
                "T212_API_KEY=file-key",
                "T212_API_SECRET=file-secret",
                "TELEGRAM_ALLOWED_CHAT_ID=123",
                "ALPHA_VANTAGE_API_KEY=alpha-key",
                "T212_LIVE_TRADING_ENABLED=true",
            ]
        ),
        encoding="utf-8",
    )
    for key in [
        "T212_ENVIRONMENT",
        "T212_LIVE_BASE_URL",
        "T212_API_KEY",
        "T212_API_SECRET",
        "TELEGRAM_ALLOWED_CHAT_ID",
        "ALPHA_VANTAGE_API_KEY",
        "T212_LIVE_TRADING_ENABLED",
    ]:
        monkeypatch.delenv(key, raising=False)

    settings = get_app_settings(env_file=env_file)

    assert settings.trading212_environment == "live"
    assert settings.trading212_base_url == "https://live.example/api/v0"
    assert settings.trading212_api_key == "file-key"
    assert settings.trading212_api_secret == "file-secret"
    assert settings.telegram_allowed_chat_id == "123"
    assert settings.alpha_vantage_api_key == "alpha-key"
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
