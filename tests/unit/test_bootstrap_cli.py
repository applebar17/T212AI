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
    assert parser.parse_args(["run", "reconcile-once"]).handler is cli.command_run_reconcile_once
    assert parser.parse_args(["run", "worker"]).handler is cli.command_run_worker


def test_apply_configuration_wizard_handles_openai_and_optional_providers() -> None:
    updates = cli.build_managed_env_values({})
    responses = iter(
        [
            "1",
            "openai-key",
            "3",
            "y",
            "telegram-token",
            "12345",
            "",
            "1",
            "y",
            "alpha-key",
            "",
            "",
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
    assert updates["MARKET_DATA_PROVIDER"] == "yahoo"
    assert updates["MARKET_INTELLIGENCE_PROVIDER"] == "alpha_vantage"
    assert updates["DISCLOSURE_PROVIDER"] == "sec_edgar"
    assert updates["COMMUNITY_PROVIDER"] == "none"
    assert updates["SEARCH_PROVIDER"] == "searxng"
    assert updates["TELEGRAM_BOT_TOKEN"] == "telegram-token"
    assert updates["TELEGRAM_ALLOWED_CHAT_ID"] == "12345"
    assert updates["TELEGRAM_ALLOWED_USER_ID"] == ""
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
            "3",
            "n",
            "3",
            "n",
            "",
            "",
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
    assert updates["MARKET_DATA_PROVIDER"] == "none"
    assert updates["MARKET_INTELLIGENCE_PROVIDER"] == "none"
    assert updates["DISCLOSURE_PROVIDER"] == "sec_edgar"
    assert updates["COMMUNITY_PROVIDER"] == "reddit"
    assert updates["SEARCH_PROVIDER"] == "none"
    assert updates["REDDIT_ENABLED"] == "true"
    assert updates["REDDIT_USERNAME"] == "reddit-user"
    assert updates["REDDIT_PASSWORD"] == "reddit-password"


def test_apply_configuration_wizard_supports_alpaca_market_data() -> None:
    updates = cli.build_managed_env_values({})
    responses = iter(
        [
            "3",
            "3",
            "n",
            "2",
            "1",
            "alpaca-key",
            "alpaca-secret",
            "n",
            "",
            "",
            "n",
            "n",
            "n",
        ]
    )
    io_runtime = cli.TerminalIO(input_fn=lambda _prompt: next(responses), output=StringIO())

    cli.apply_configuration_wizard(io_runtime, updates)

    assert updates["LLM_PROVIDER"] == "none"
    assert updates["BROKER_PROVIDER"] == "none"
    assert updates["MARKET_DATA_PROVIDER"] == "alpaca"
    assert updates["ALPACA_ENVIRONMENT"] == "paper"
    assert updates["ALPACA_API_KEY"] == "alpaca-key"
    assert updates["ALPACA_API_SECRET"] == "alpaca-secret"
    assert updates["YAHOO_ENABLED"] == "false"


def test_apply_configuration_wizard_supports_alpaca_broker_and_market_data_reuse() -> None:
    updates = cli.build_managed_env_values({})
    responses = iter(
        [
            "3",
            "2",
            "1",
            "alpaca-broker-key",
            "alpaca-broker-secret",
            "n",
            "y",
            "n",
            "",
            "",
            "n",
            "n",
            "n",
        ]
    )
    io_runtime = cli.TerminalIO(input_fn=lambda _prompt: next(responses), output=StringIO())

    cli.apply_configuration_wizard(io_runtime, updates)

    assert updates["BROKER_PROVIDER"] == "alpaca"
    assert updates["MARKET_DATA_PROVIDER"] == "alpaca"
    assert updates["ALPACA_ENVIRONMENT"] == "paper"
    assert updates["ALPACA_API_KEY"] == "alpaca-broker-key"
    assert updates["ALPACA_API_SECRET"] == "alpaca-broker-secret"
    assert updates["YAHOO_ENABLED"] == "false"


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


def test_run_reconcile_once_preflight_requires_broker(tmp_path, capsys) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")

    exit_code = cli.main(["run", "reconcile-once", "--env-file", str(env_file)])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Reconciliation requires broker read access" in output


def test_run_reconcile_once_invokes_reconciliation_runtime(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "BROKER_PROVIDER=trading212",
                "T212_API_KEY=t212-key",
                "T212_API_SECRET=t212-secret",
            ]
        ),
        encoding="utf-8",
    )
    calls: dict[str, object] = {}

    class FakeResult:
        def render_text(self) -> str:
            return "reconciled"

    class FakeRuntime:
        reconciliation_service = object()

    monkeypatch.setattr(cli, "build_runtime", lambda settings=None: FakeRuntime())

    def fake_run_reconcile_once(runtime):
        calls["runtime"] = runtime
        return FakeResult()

    monkeypatch.setattr(cli, "run_reconcile_once", fake_run_reconcile_once)

    exit_code = cli.main(["run", "reconcile-once", "--env-file", str(env_file)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.strip() == "reconciled"
    assert isinstance(calls["runtime"], FakeRuntime)


def test_run_worker_parses_interval_and_invokes_worker(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "BROKER_PROVIDER=trading212",
                "T212_API_KEY=t212-key",
                "T212_API_SECRET=t212-secret",
            ]
        ),
        encoding="utf-8",
    )
    calls: dict[str, object] = {}

    class FakeRuntime:
        reconciliation_service = object()

    monkeypatch.setattr(cli, "build_runtime", lambda settings=None: FakeRuntime())

    def fake_run_worker(runtime, *, interval_seconds: int) -> int:
        calls["runtime"] = runtime
        calls["interval_seconds"] = interval_seconds
        return 0

    monkeypatch.setattr(cli, "run_reconcile_worker", fake_run_worker)

    exit_code = cli.main(
        ["run", "worker", "--env-file", str(env_file), "--reconcile-every", "15m"]
    )

    assert exit_code == 0
    assert isinstance(calls["runtime"], FakeRuntime)
    assert calls["interval_seconds"] == 900


def test_parse_duration_to_seconds_supports_compact_forms() -> None:
    assert cli.parse_duration_to_seconds("5m") == 300
    assert cli.parse_duration_to_seconds("1h") == 3600
    assert cli.parse_duration_to_seconds("45s") == 45


def test_package_main_delegates_to_cli(monkeypatch) -> None:
    calls: dict[str, object] = {}

    def fake_cli_main(argv):
        calls["argv"] = argv
        return 7

    monkeypatch.setattr(package_main, "cli_main", fake_cli_main)

    assert package_main.main(["doctor"]) == 7
    assert calls["argv"] == ["doctor"]
