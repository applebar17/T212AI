from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path
from types import ModuleType, SimpleNamespace

from t212ai import __main__ as package_main
from t212ai import cli
from t212ai.persistence.database import build_engine, build_session_factory, ensure_schema
from t212ai.scheduler import ScheduledProcessService


def _scheduler_service(tmp_path: Path, name: str = "scheduler-cli.db") -> ScheduledProcessService:
    engine = build_engine(f"sqlite:///{tmp_path / name}")
    ensure_schema(engine)
    return ScheduledProcessService(build_session_factory(engine))


def _fake_scheduler_runtime(service: ScheduledProcessService):
    return SimpleNamespace(
        scheduled_process_service=service,
        settings=cli.get_app_settings(env={}),
    )


def test_cli_parser_routes_configure_doctor_and_run_bot() -> None:
    parser = cli.build_parser("brokerai")

    assert parser.parse_args(["configure"]).handler is cli.command_configure
    assert parser.parse_args(["doctor"]).handler is cli.command_doctor
    assert parser.parse_args(["run", "bot"]).handler is cli.command_run_bot
    assert parser.parse_args(["run", "reconcile-once"]).handler is cli.command_run_reconcile_once
    assert parser.parse_args(["run", "scheduler-once"]).handler is cli.command_run_scheduler_once
    assert parser.parse_args(["run", "scheduler"]).handler is cli.command_run_scheduler_worker
    assert parser.parse_args(["run", "worker"]).handler is cli.command_run_worker
    assert parser.parse_args(["scheduler", "status"]).handler is cli.command_scheduler_status
    assert parser.parse_args(["scheduler", "list"]).handler is cli.command_scheduler_list
    assert (
        parser.parse_args(["scheduler", "show", "sched_test"]).handler
        is cli.command_scheduler_show
    )
    assert (
        parser.parse_args(["scheduler", "recover-stale"]).handler
        is cli.command_scheduler_recover_stale
    )
    assert parser.parse_args(["scheduler", "cleanup"]).handler is cli.command_scheduler_cleanup
    assert parser.parse_args(["scheduler", "export"]).handler is cli.command_scheduler_export


def test_apply_configuration_wizard_handles_openai_and_optional_providers() -> None:
    updates = cli.build_managed_env_values({})
    responses = iter(
        [
            "1",
            "openai-key",
            "",
            "n",
            "n",
            "",
            "",
            "n",
            "3",
            "y",
            "telegram-token",
            "12345",
            "",
            "1",
            "y",
            "alpha-key",
            "n",
            "n",
            "n",
        ]
    )
    io_runtime = cli.TerminalIO(input_fn=lambda _prompt: next(responses), output=StringIO())

    cli.apply_configuration_wizard(io_runtime, updates)

    assert updates["LLM_PROVIDER"] == "openai"
    assert updates["OPENAI_API_KEY"] == "openai-key"
    assert updates["OPENAI_CHAT_MODEL_DEFAULT"] == "gpt-4o-mini"
    assert updates["GENAI_CONTEXT_TOKENS_DEFAULT"] == "128000"
    assert updates["OPENAI_CHAT_MODEL_SMART"] == ""
    assert updates["GENAI_CONTEXT_TOKENS_SMART"] == ""
    assert updates["OPENAI_CHAT_MODEL_REASONING"] == ""
    assert updates["GENAI_CONTEXT_TOKENS_REASONING"] == ""
    assert updates["BROKER_PROVIDER"] == "none"
    assert updates["MARKET_DATA_PROVIDER"] == "yahoo"
    assert updates["MARKET_INTELLIGENCE_PROVIDER"] == "alpha_vantage"
    assert updates["DISCLOSURE_PROVIDER"] == "none"
    assert updates["COMMUNITY_PROVIDER"] == "none"
    assert updates["SEARCH_PROVIDER"] == "none"
    assert updates["TELEGRAM_BOT_TOKEN"] == "telegram-token"
    assert updates["TELEGRAM_ALLOWED_CHAT_ID"] == "12345"
    assert updates["TELEGRAM_ALLOWED_USER_ID"] == ""
    assert updates["YAHOO_ENABLED"] == "true"
    assert updates["ALPHA_VANTAGE_ENABLED"] == "true"
    assert updates["ALPHA_VANTAGE_API_KEY"] == "alpha-key"
    assert updates["REDDIT_ENABLED"] == "false"
    assert updates["SEARXNG_ENABLED"] == "false"
    assert updates["LANGSMITH_TRACING"] == "false"


def test_apply_configuration_wizard_supports_azure_and_reddit_user_password() -> None:
    updates = cli.build_managed_env_values({"REDDIT_REFRESH_TOKEN": "legacy-refresh-token"})
    responses = iter(
        [
            "2",
            "https://azure.example",
            "azure-key",
            "",
            "azure-baseline",
            "",
            "y",
            "azure-smart",
            "",
            "y",
            "azure-reasoning",
            "",
            "azure-embed",
            "y",
            "",
            "smith-key",
            "",
            "3",
            "n",
            "3",
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
        ]
    )
    io_runtime = cli.TerminalIO(input_fn=lambda _prompt: next(responses), output=StringIO())

    cli.apply_configuration_wizard(io_runtime, updates)

    assert updates["LLM_PROVIDER"] == "azure_openai"
    assert updates["AZURE_OPENAI_ENABLED"] == "true"
    assert updates["AZURE_OPENAI_ENDPOINT"] == "https://azure.example"
    assert updates["AZURE_OPENAI_API_KEY"] == "azure-key"
    assert updates["OPENAI_CHAT_MODEL_DEFAULT"] == "azure-baseline"
    assert updates["GENAI_CONTEXT_TOKENS_DEFAULT"] == "128000"
    assert updates["OPENAI_CHAT_MODEL_SMART"] == "azure-smart"
    assert updates["GENAI_CONTEXT_TOKENS_SMART"] == "128000"
    assert updates["OPENAI_CHAT_MODEL_REASONING"] == "azure-reasoning"
    assert updates["GENAI_CONTEXT_TOKENS_REASONING"] == "128000"
    assert updates["AZURE_OPENAI_EMBED_DEPLOYMENT"] == "azure-embed"
    assert updates["LANGSMITH_TRACING"] == "true"
    assert updates["LANGSMITH_ENDPOINT"] == "https://eu.api.smith.langchain.com"
    assert updates["LANGSMITH_API_KEY"] == "smith-key"
    assert updates["LANGSMITH_PROJECT"] == "T212AI"
    assert updates["MARKET_DATA_PROVIDER"] == "none"
    assert updates["MARKET_INTELLIGENCE_PROVIDER"] == "none"
    assert updates["DISCLOSURE_PROVIDER"] == "none"
    assert updates["COMMUNITY_PROVIDER"] == "reddit"
    assert updates["SEARCH_PROVIDER"] == "none"
    assert updates["REDDIT_ENABLED"] == "true"
    assert updates["REDDIT_USERNAME"] == "reddit-user"
    assert updates["REDDIT_PASSWORD"] == "reddit-password"
    assert updates["REDDIT_REFRESH_TOKEN"] == ""


def test_context_limit_prompt_validates_custom_integer() -> None:
    responses = iter(["custom", "64000", "64001"])
    output = StringIO()
    io_runtime = cli.TerminalIO(input_fn=lambda _prompt: next(responses), output=output)

    result = cli._prompt_model_context_limit(
        io_runtime,
        model="custom-deployment",
        existing="",
        label="custom deployment",
    )

    assert result == "64001"
    assert "greater than 64000" in output.getvalue()


def test_context_limit_prompt_auto_uses_known_model_limit_without_prompting() -> None:
    io_runtime = cli.TerminalIO(
        input_fn=lambda _prompt: (_ for _ in ()).throw(AssertionError("unexpected prompt")),
        output=StringIO(),
    )

    result = cli._prompt_model_context_limit(
        io_runtime,
        model="gpt-4.1",
        existing="",
        label="known model",
    )

    assert result == "1047576"


def test_openai_model_prompt_allows_only_registry_known_custom_models() -> None:
    responses = iter(["custom", "not-a-model", "gpt-4.1-2025-04-14"])
    output = StringIO()
    io_runtime = cli.TerminalIO(input_fn=lambda _prompt: next(responses), output=output)

    result = cli._prompt_openai_model(
        io_runtime,
        "OpenAI model",
        options=cli.OPENAI_DEFAULT_MODEL_OPTIONS,
        default="gpt-4o-mini",
    )

    assert result == "gpt-4.1-2025-04-14"
    assert "not in the internal OpenAI context registry" in output.getvalue()


def test_build_managed_env_values_preserves_context_settings() -> None:
    updates = cli.build_managed_env_values(
        {
            "GENAI_CONTEXT_TOKENS_DEFAULT": "200000",
            "GENAI_CONTEXT_TOKENS_SMART": "300000",
            "GENAI_CONTEXT_TOKENS_BY_MODEL_JSON": '{"custom":250000}',
        }
    )

    assert updates["GENAI_CONTEXT_TOKENS_DEFAULT"] == "200000"
    assert updates["GENAI_CONTEXT_TOKENS_SMART"] == "300000"
    assert updates["GENAI_CONTEXT_TOKENS_BY_MODEL_JSON"] == '{"custom":250000}'


def test_apply_configuration_wizard_supports_alpaca_market_data() -> None:
    updates = cli.build_managed_env_values({})
    responses = iter(
        [
            "3",
            "n",
            "3",
            "n",
            "2",
            "",
            "alpaca-paper-key",
            "alpaca-paper-secret",
            "n",
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
    assert updates["ALPACA_PAPER_API_KEY"] == "alpaca-paper-key"
    assert updates["ALPACA_PAPER_API_SECRET"] == "alpaca-paper-secret"
    assert updates["ALPACA_LIVE_API_KEY"] == ""
    assert updates["ALPACA_LIVE_API_SECRET"] == ""
    assert updates["YAHOO_ENABLED"] == "false"


def test_apply_configuration_wizard_supports_alpaca_broker_and_market_data_reuse() -> None:
    updates = cli.build_managed_env_values({})
    responses = iter(
        [
            "3",
            "n",
            "2",
            "",
            "alpaca-paper-key",
            "alpaca-paper-secret",
            "n",
            "y",
            "n",
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
    assert updates["ALPACA_PAPER_API_KEY"] == "alpaca-paper-key"
    assert updates["ALPACA_PAPER_API_SECRET"] == "alpaca-paper-secret"
    assert updates["ALPACA_LIVE_API_KEY"] == ""
    assert updates["ALPACA_LIVE_API_SECRET"] == ""
    assert updates["YAHOO_ENABLED"] == "false"


def test_apply_configuration_wizard_supports_trading212_environment_specific_credentials() -> None:
    updates = cli.build_managed_env_values({})
    responses = iter(
        [
            "3",
            "n",
            "1",
            "2",
            "t212-live-key",
            "t212-live-secret",
            "y",
            "n",
            "3",
            "n",
            "n",
            "n",
            "n",
        ]
    )
    io_runtime = cli.TerminalIO(input_fn=lambda _prompt: next(responses), output=StringIO())

    cli.apply_configuration_wizard(io_runtime, updates)

    assert updates["BROKER_PROVIDER"] == "trading212"
    assert updates["T212_ENVIRONMENT"] == "live"
    assert updates["T212_DEMO_API_KEY"] == ""
    assert updates["T212_DEMO_API_SECRET"] == ""
    assert updates["T212_LIVE_API_KEY"] == "t212-live-key"
    assert updates["T212_LIVE_API_SECRET"] == "t212-live-secret"
    assert updates["T212_LIVE_TRADING_ENABLED"] == "true"


def test_build_managed_env_values_migrates_legacy_broker_keys_to_active_environment() -> None:
    updates = cli.build_managed_env_values(
        {
            "BROKER_PROVIDER": "trading212",
            "T212_ENVIRONMENT": "live",
            "T212_API_KEY": "legacy-live-key",
            "T212_API_SECRET": "legacy-live-secret",
            "ALPACA_ENVIRONMENT": "paper",
            "ALPACA_API_KEY": "legacy-paper-key",
            "ALPACA_API_SECRET": "legacy-paper-secret",
        }
    )

    assert updates["T212_LIVE_API_KEY"] == "legacy-live-key"
    assert updates["T212_LIVE_API_SECRET"] == "legacy-live-secret"
    assert updates["T212_DEMO_API_KEY"] == ""
    assert updates["T212_DEMO_API_SECRET"] == ""
    assert updates["ALPACA_PAPER_API_KEY"] == "legacy-paper-key"
    assert updates["ALPACA_PAPER_API_SECRET"] == "legacy-paper-secret"
    assert updates["ALPACA_LIVE_API_KEY"] == ""
    assert updates["ALPACA_LIVE_API_SECRET"] == ""


def test_apply_configuration_wizard_can_skip_existing_sections_and_explains_searxng() -> None:
    existing = {
        "LLM_PROVIDER": "openai",
        "OPENAI_API_KEY": "persisted-openai-key",
        "TELEGRAM_BOT_TOKEN": "persisted-telegram-token",
        "TELEGRAM_ALLOWED_CHAT_ID": "999",
    }
    updates = cli.build_managed_env_values(existing)
    output = StringIO()
    responses = iter(
        [
            "n",
            "n",
            "3",
            "n",
            "1",
            "n",
            "n",
            "n",
            "n",
        ]
    )
    io_runtime = cli.TerminalIO(input_fn=lambda _prompt: next(responses), output=output)

    cli.apply_configuration_wizard(io_runtime, updates, existing_raw=existing)

    assert updates["OPENAI_API_KEY"] == "persisted-openai-key"
    assert updates["TELEGRAM_BOT_TOKEN"] == "persisted-telegram-token"
    assert updates["TELEGRAM_ALLOWED_CHAT_ID"] == "999"
    assert "compose-managed" in output.getvalue()


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


def test_update_env_file_groups_broker_provider_settings_together(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")

    cli.update_env_file(
        env_file,
        {
            "T212_ENVIRONMENT": "demo",
            "T212_DEMO_API_KEY": "demo-key",
            "T212_DEMO_API_SECRET": "demo-secret",
            "ALPACA_ENVIRONMENT": "paper",
            "ALPACA_PAPER_API_KEY": "paper-key",
            "ALPACA_PAPER_API_SECRET": "paper-secret",
        },
    )

    content = env_file.read_text(encoding="utf-8")
    assert "# Broker providers" in content
    assert "# Trading 212" not in content
    assert "# Alpaca" not in content
    assert content.index("T212_ENVIRONMENT=demo") < content.index("ALPACA_ENVIRONMENT=paper")


def test_empty_inactive_broker_credentials_are_not_added_to_new_env_files() -> None:
    updates = cli.build_managed_env_values({})
    updates.update(
        {
            "BROKER_PROVIDER": "trading212",
            "MARKET_DATA_PROVIDER": "alpaca",
            "T212_ENVIRONMENT": "live",
            "T212_LIVE_API_KEY": "live-key",
            "T212_LIVE_API_SECRET": "live-secret",
            "ALPACA_ENVIRONMENT": "paper",
            "ALPACA_PAPER_API_KEY": "paper-key",
            "ALPACA_PAPER_API_SECRET": "paper-secret",
        }
    )

    cli._drop_new_empty_inactive_broker_credentials(updates, existing_raw={})

    assert "T212_LIVE_API_KEY" in updates
    assert "T212_DEMO_API_KEY" not in updates
    assert "ALPACA_PAPER_API_KEY" in updates
    assert "ALPACA_LIVE_API_KEY" not in updates


def test_existing_inactive_broker_credentials_are_preserved_in_env_review() -> None:
    existing = {
        "T212_DEMO_API_KEY": "existing-demo-key",
        "T212_DEMO_API_SECRET": "existing-demo-secret",
    }
    updates = cli.build_managed_env_values(existing)
    updates.update(
        {
            "BROKER_PROVIDER": "trading212",
            "T212_ENVIRONMENT": "live",
            "T212_LIVE_API_KEY": "live-key",
            "T212_LIVE_API_SECRET": "live-secret",
        }
    )

    cli._drop_new_empty_inactive_broker_credentials(updates, existing_raw=existing)

    assert updates["T212_DEMO_API_KEY"] == "existing-demo-key"
    assert updates["T212_DEMO_API_SECRET"] == "existing-demo-secret"


def test_doctor_returns_zero_for_valid_but_incomplete_defaults(tmp_path, capsys) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")

    exit_code = cli.main(["doctor", "--env-file", str(env_file)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Configuration status: valid" in output
    assert "Run bot preflight: blocked" in output
    assert "- Scheduled processes: available" in output
    assert "- Scheduler notifications: unavailable" in output
    assert "- Scheduler instrument monitor: available" in output
    assert "- Scheduler delegate: unavailable" in output
    assert "- Scheduler company event analyst: unavailable" in output
    assert "- Scheduler market regime monitor: unavailable" in output
    assert "- Scheduler market signal capture: unavailable" in output
    assert "- Scheduler trade setup monitor: unavailable" in output


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


def test_run_scheduler_once_preflight_requires_database(tmp_path, capsys) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=\n", encoding="utf-8")

    exit_code = cli.main(["run", "scheduler-once", "--env-file", str(env_file)])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Scheduler requires DATABASE_URL" in output


def test_run_scheduler_once_invokes_scheduler_runtime(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    calls: dict[str, object] = {}

    class FakeResult:
        def render_text(self) -> str:
            return "scheduler ran"

    class FakeRuntime:
        scheduled_process_service = object()

    monkeypatch.setattr(cli, "build_runtime", lambda settings=None: FakeRuntime())

    def fake_run_scheduler_once(runtime, **kwargs):
        calls["runtime"] = runtime
        calls["kwargs"] = kwargs
        return FakeResult()

    monkeypatch.setattr(cli, "run_scheduler_once", fake_run_scheduler_once)

    exit_code = cli.main(["run", "scheduler-once", "--env-file", str(env_file)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.strip() == "scheduler ran"
    assert isinstance(calls["runtime"], FakeRuntime)
    assert calls["kwargs"]["limit"] == 100


def test_run_scheduler_once_registers_instrument_monitor_adapter(monkeypatch) -> None:
    calls: dict[str, object] = {}

    class FakeWorker:
        def __init__(self, service, *, adapters, notification_service=None, **kwargs):
            calls["service"] = service
            calls["adapters"] = adapters
            calls["notification_service"] = notification_service
            calls["worker_kwargs"] = kwargs

        def run_once(self, *, limit: int = 100):
            calls["limit"] = limit
            return object()

    class FakeRuntime:
        scheduled_process_service = object()
        market_data_service = object()
        scheduler_notification_service = object()
        broker_read_service = object()
        broker_execution_service = object()
        pending_action_service = object()
        proposal_service = object()

    monkeypatch.setattr(cli, "SchedulerWorker", FakeWorker)

    result = cli.run_scheduler_once(FakeRuntime(), limit=7)

    assert result is not None
    assert calls["service"] is FakeRuntime.scheduled_process_service
    assert "instrument_monitor" in calls["adapters"]
    assert "company_event_analyst" in calls["adapters"]
    assert "market_regime_monitor" in calls["adapters"]
    assert "market_signal_capture" in calls["adapters"]
    assert "trade_setup_monitor" in calls["adapters"]
    assert calls["notification_service"] is FakeRuntime.scheduler_notification_service
    assert calls["worker_kwargs"]["lease_seconds"] == 1800
    assert calls["worker_kwargs"]["max_llm_runs_per_pass"] == 0
    assert calls["limit"] == 7


def test_run_scheduler_parses_interval_and_invokes_worker(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    calls: dict[str, object] = {}

    class FakeRuntime:
        scheduled_process_service = object()

    monkeypatch.setattr(cli, "build_runtime", lambda settings=None: FakeRuntime())

    def fake_run_scheduler_worker(runtime, **kwargs) -> int:
        calls["runtime"] = runtime
        calls.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "run_scheduler_worker", fake_run_scheduler_worker)

    exit_code = cli.main(
        ["run", "scheduler", "--env-file", str(env_file), "--poll-every", "15m"]
    )

    assert exit_code == 0
    assert isinstance(calls["runtime"], FakeRuntime)
    assert calls["poll_every_seconds"] == 900
    assert calls["limit"] == 100


def test_scheduler_status_list_show_and_export_commands(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    service = _scheduler_service(tmp_path)
    process = service.create_process(
        title="TSLA watch",
        kind="instrument_monitor",
        execution_mode="deterministic",
        schedule={"type": "polling", "pollEverySeconds": 60},
        trigger={"type": "below_price", "symbol": "TSLA", "value": 180},
        lifecycle={"completionPolicy": "keep_running"},
    )
    output_file = tmp_path / "scheduler-export.json"
    monkeypatch.setattr(
        cli,
        "build_runtime",
        lambda settings=None: _fake_scheduler_runtime(service),
    )

    status_code = cli.main(["scheduler", "status", "--env-file", str(env_file)])
    list_code = cli.main(
        [
            "scheduler",
            "list",
            "--env-file",
            str(env_file),
            "--status",
            "active",
            "--kind",
            "instrument_monitor",
        ]
    )
    show_code = cli.main(
        ["scheduler", "show", process.process_id, "--env-file", str(env_file)]
    )
    export_code = cli.main(
        [
            "scheduler",
            "export",
            "--env-file",
            str(env_file),
            "--output",
            str(output_file),
            "--include-runs",
            "--include-events",
        ]
    )

    output = capsys.readouterr().out
    assert status_code == 0
    assert list_code == 0
    assert show_code == 0
    assert export_code == 0
    assert "brokerai scheduler status" in output
    assert process.process_id in output
    assert "Scheduled process" in output
    exported = json.loads(output_file.read_text(encoding="utf-8"))
    assert exported["schema"] == "brokerai.scheduler.export.v1"
    assert exported["processCount"] == 1


def test_scheduler_recover_and_cleanup_default_to_dry_run_until_apply(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    service = _scheduler_service(tmp_path, "scheduler-cli-maintenance.db")
    process = service.create_process(
        title="TSLA watch",
        kind="instrument_monitor",
        execution_mode="deterministic",
        schedule={"type": "polling", "pollEverySeconds": 60},
        trigger={"type": "below_price", "symbol": "TSLA", "value": 180},
        lifecycle={"completionPolicy": "keep_running"},
    )
    service.record_run_started(process.process_id)
    archived = service.archive_process(process.process_id)
    monkeypatch.setattr(
        cli,
        "build_runtime",
        lambda settings=None: _fake_scheduler_runtime(service),
    )

    recover_dry = cli.main(
        ["scheduler", "recover-stale", "--env-file", str(env_file), "--older-than", "1s"]
    )
    cleanup_dry = cli.main(
        [
            "scheduler",
            "cleanup",
            "--env-file",
            str(env_file),
            "--archived-before",
            "2999-01-01T00:00:00Z",
        ]
    )
    cleanup_apply = cli.main(
        [
            "scheduler",
            "cleanup",
            "--env-file",
            str(env_file),
            "--archived-before",
            "2999-01-01T00:00:00Z",
            "--apply",
        ]
    )

    output = capsys.readouterr().out
    assert recover_dry == 0
    assert cleanup_dry == 0
    assert cleanup_apply == 0
    assert "recover-stale: dry-run" in output
    assert "cleanup: dry-run" in output
    assert "cleanup: applied" in output
    assert service.get_process(archived.process_id) is None


def test_parse_duration_to_seconds_supports_compact_forms() -> None:
    assert cli.parse_duration_to_seconds("5m") == 300
    assert cli.parse_duration_to_seconds("1h") == 3600
    assert cli.parse_duration_to_seconds("45s") == 45
    assert cli.parse_duration_to_seconds("2d") == 172800


def test_package_main_delegates_to_cli(monkeypatch) -> None:
    calls: dict[str, object] = {}

    def fake_cli_main(argv):
        calls["argv"] = argv
        return 7

    monkeypatch.setattr(package_main, "cli_main", fake_cli_main)

    assert package_main.main(["doctor"]) == 7
    assert calls["argv"] == ["doctor"]
