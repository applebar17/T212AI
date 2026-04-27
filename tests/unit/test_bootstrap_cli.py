from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path
from types import ModuleType

from t212ai import cli
from t212ai import __main__ as package_main


def test_cli_parser_routes_configure_doctor_and_run_bot() -> None:
    parser = cli.build_parser("brokerai")

    assert parser.parse_args(["configure"]).handler is cli.command_configure
    assert parser.parse_args(["doctor"]).handler is cli.command_doctor
    assert parser.parse_args(["run", "bot"]).handler is cli.command_run_bot


def test_apply_configuration_wizard_handles_openai_and_optional_providers() -> None:
    updates = cli.build_managed_env_values({})
    responses = iter(
        [
            "1",
            "openai-key",
            "2",
            "y",
            "telegram-token",
            "12345",
            "y",
            "y",
            "alpha-key",
            "n",
            "y",
            "https://search.example",
            "n",
        ]
    )
    io_runtime = cli.TerminalIO(input_fn=lambda _prompt: next(responses), output=StringIO())

    cli.apply_configuration_wizard(io_runtime, updates)

    assert updates["LLM_PROVIDER"] == "openai"
    assert updates["OPENAI_API_KEY"] == "openai-key"
    assert updates["BROKER_PROVIDER"] == "none"
    assert updates["TELEGRAM_BOT_TOKEN"] == "telegram-token"
    assert updates["TELEGRAM_ALLOWED_CHAT_ID"] == "12345"
    assert updates["YAHOO_ENABLED"] == "true"
    assert updates["ALPHA_VANTAGE_ENABLED"] == "true"
    assert updates["ALPHA_VANTAGE_API_KEY"] == "alpha-key"
    assert updates["REDDIT_ENABLED"] == "false"
    assert updates["SEARXNG_ENABLED"] == "true"
    assert updates["SEARXNG_BASE_URL"] == "https://search.example"


def test_apply_configuration_wizard_supports_azure_and_reddit_user_password() -> None:
    updates = cli.build_managed_env_values({})
    responses = iter(
        [
            "2",
            "https://azure.example",
            "azure-key",
            "",
            "2",
            "n",
            "n",
            "n",
            "y",
            "reddit-id",
            "reddit-secret",
            "reddit-agent",
            "2",
            "reddit-user",
            "reddit-password",
            "n",
            "n",
        ]
    )
    io_runtime = cli.TerminalIO(input_fn=lambda _prompt: next(responses), output=StringIO())

    cli.apply_configuration_wizard(io_runtime, updates)

    assert updates["LLM_PROVIDER"] == "azure_openai"
    assert updates["AZURE_OPENAI_ENABLED"] == "true"
    assert updates["AZURE_OPENAI_ENDPOINT"] == "https://azure.example"
    assert updates["AZURE_OPENAI_API_KEY"] == "azure-key"
    assert updates["REDDIT_ENABLED"] == "true"
    assert updates["REDDIT_USERNAME"] == "reddit-user"
    assert updates["REDDIT_PASSWORD"] == "reddit-password"


def test_update_env_file_preserves_unrelated_lines_and_updates_managed_keys(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# existing comment\nFOO=bar\nOPENAI_API_KEY=oldkey\n",
        encoding="utf-8",
    )

    cli.update_env_file(
        env_file,
        {
            "OPENAI_API_KEY": "newkey",
            "LLM_PROVIDER": "openai",
        },
    )

    content = env_file.read_text(encoding="utf-8")
    assert "# existing comment" in content
    assert "FOO=bar" in content
    assert "OPENAI_API_KEY=newkey" in content
    assert "LLM_PROVIDER=openai" in content


def test_doctor_returns_zero_for_valid_but_incomplete_defaults(tmp_path, capsys) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")

    exit_code = cli.main(["doctor", "--env-file", str(env_file)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Configuration status: valid" in output
    assert "Run bot preflight: blocked" in output


def test_doctor_returns_nonzero_for_partial_reddit_config(tmp_path, capsys) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "REDDIT_ENABLED=true\nREDDIT_CLIENT_ID=reddit-id\n",
        encoding="utf-8",
    )

    exit_code = cli.main(["doctor", "--env-file", str(env_file)])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Reddit is missing required settings" in output


def test_run_bot_preflight_fails_cleanly_when_llm_is_missing(tmp_path, capsys) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TELEGRAM_BOT_TOKEN=tg-token\nTELEGRAM_ALLOWED_CHAT_ID=123\n",
        encoding="utf-8",
    )

    exit_code = cli.main(["run", "bot", "--env-file", str(env_file)])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Run bot requires LLM reasoning" in output


def test_run_bot_valid_preflight_invokes_telegram_service(
    tmp_path,
    monkeypatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "LLM_PROVIDER=openai",
                "OPENAI_API_KEY=openai-key",
                "TELEGRAM_BOT_TOKEN=tg-token",
                "TELEGRAM_ALLOWED_CHAT_ID=123",
            ]
        ),
        encoding="utf-8",
    )
    calls: dict[str, object] = {}

    fake_module = ModuleType("t212ai.telegram")

    class FakeTelegramBotService:
        @classmethod
        def from_settings(cls, settings, runtime=None):
            calls["settings"] = settings
            calls["runtime"] = runtime
            return cls()

        def run_polling(self) -> None:
            calls["ran"] = True

    fake_module.TelegramBotService = FakeTelegramBotService
    monkeypatch.setitem(sys.modules, "t212ai.telegram", fake_module)

    exit_code = cli.main(["run", "bot", "--env-file", str(env_file)])

    assert exit_code == 0
    assert calls["ran"] is True
    assert getattr(calls["settings"], "llm_provider") == "openai"
    assert calls["runtime"] is not None


def test_package_main_delegates_to_cli(monkeypatch) -> None:
    calls: dict[str, object] = {}

    def fake_cli_main(argv):
        calls["argv"] = argv
        return 7

    monkeypatch.setattr(package_main, "cli_main", fake_cli_main)

    assert package_main.main(["doctor"]) == 7
    assert calls["argv"] == ["doctor"]
