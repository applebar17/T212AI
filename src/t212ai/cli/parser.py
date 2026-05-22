"""Argument parser construction for the brokerai CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from t212ai.app.config import DEFAULT_ENV_FILE_NAME

from .config_metadata import (
    command_config_explain,
    command_config_list,
    command_config_sample,
    command_config_validate,
)
from .config_wizard import command_configure, command_onboard
from .doctor import command_doctor
from .run import (
    command_run_alpaca_news_stream,
    command_run_bot,
    command_run_reconcile_once,
    command_run_scheduler_once,
    command_run_scheduler_worker,
    command_run_worker,
)
from .scheduler import (
    command_scheduler_cleanup,
    command_scheduler_export,
    command_scheduler_list,
    command_scheduler_recover_stale,
    command_scheduler_show,
    command_scheduler_status,
)


def build_parser(prog: str | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog or _default_prog_name(),
        description="brokerai operator CLI for configuring, validating, and running T212AI.",
        epilog=(
            "Examples:\n"
            "  brokerai onboard --env-file .env\n"
            "  brokerai configure --env-file .env\n"
            "  brokerai config explain SCHEDULER_LEASE_SECONDS\n"
            "  brokerai config sample demo > .env\n"
            "  brokerai doctor --env-file .env --smoke\n"
            "  brokerai run bot --env-file .env\n"
            "  brokerai scheduler status --env-file .env"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")

    configure_parser = subparsers.add_parser(
        "configure",
        help="Run the styled interactive configuration wizard.",
    )
    configure_parser.add_argument(
        "--env-file",
        default=DEFAULT_ENV_FILE_NAME,
        help="Path to the .env file to create or update.",
    )
    configure_parser.set_defaults(handler=command_configure)

    onboard_parser = subparsers.add_parser(
        "onboard",
        help="Show the first-run safety notice and launch configuration.",
    )
    onboard_parser.add_argument(
        "--env-file",
        default=DEFAULT_ENV_FILE_NAME,
        help="Path to the .env file to create or update.",
    )
    onboard_parser.set_defaults(handler=command_onboard)

    _add_config_parser(subparsers)

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Inspect configuration, enabled providers, and run-bot readiness.",
    )
    doctor_parser.add_argument(
        "--env-file",
        default=None,
        help="Optional path to inspect instead of the active process environment.",
    )
    doctor_parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run optional live smoke probes for enabled providers.",
    )
    doctor_parser.set_defaults(handler=command_doctor)

    _add_scheduler_parser(subparsers)
    _add_run_parser(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return int(handler(args))


def _add_config_parser(subparsers: argparse._SubParsersAction) -> None:
    config_parser = subparsers.add_parser(
        "config",
        help="Explain, sample, and validate brokerai configuration.",
    )
    config_subparsers = config_parser.add_subparsers(dest="config_target")

    list_parser = config_subparsers.add_parser(
        "list",
        help="List known configuration keys grouped by section.",
    )
    list_parser.add_argument("--section", default=None, help="Filter by section name.")
    list_parser.add_argument("--format", choices=("text", "json"), default="text")
    list_parser.set_defaults(handler=command_config_list)

    explain_parser = config_subparsers.add_parser(
        "explain",
        help="Explain the purpose, default, example, and scenario for one key.",
    )
    explain_parser.add_argument("key")
    explain_parser.add_argument("--format", choices=("text", "json"), default="text")
    explain_parser.set_defaults(handler=command_config_explain)

    sample_parser = config_subparsers.add_parser(
        "sample",
        help="Print a sample .env profile.",
    )
    sample_parser.add_argument(
        "profile",
        choices=("demo", "research", "alpaca-paper", "live-guarded"),
    )
    sample_parser.set_defaults(handler=command_config_sample)

    validate_parser = config_subparsers.add_parser(
        "validate",
        help="Validate configuration without starting a runtime process.",
    )
    validate_parser.add_argument("--env-file", default=None)
    validate_parser.set_defaults(handler=command_config_validate)


def _add_scheduler_parser(subparsers: argparse._SubParsersAction) -> None:
    scheduler_parser = subparsers.add_parser(
        "scheduler",
        help="Inspect and maintain scheduled processes.",
    )
    scheduler_subparsers = scheduler_parser.add_subparsers(dest="scheduler_target")
    scheduler_status_parser = scheduler_subparsers.add_parser(
        "status",
        help="Show scheduler operational status.",
    )
    scheduler_status_parser.add_argument("--env-file", default=None)
    scheduler_status_parser.set_defaults(handler=command_scheduler_status)

    scheduler_list_parser = scheduler_subparsers.add_parser(
        "list",
        help="List scheduled processes.",
    )
    scheduler_list_parser.add_argument("--env-file", default=None)
    scheduler_list_parser.add_argument("--status", action="append", dest="statuses")
    scheduler_list_parser.add_argument("--kind", action="append", dest="kinds")
    scheduler_list_parser.add_argument("--limit", type=int, default=50)
    scheduler_list_parser.set_defaults(handler=command_scheduler_list)

    scheduler_show_parser = scheduler_subparsers.add_parser(
        "show",
        help="Show one scheduled process with recent runs/events.",
    )
    scheduler_show_parser.add_argument("process_id")
    scheduler_show_parser.add_argument("--env-file", default=None)
    scheduler_show_parser.add_argument("--runs", type=int, default=10)
    scheduler_show_parser.add_argument("--events", type=int, default=20)
    scheduler_show_parser.set_defaults(handler=command_scheduler_show)

    scheduler_recover_parser = scheduler_subparsers.add_parser(
        "recover-stale",
        help="Recover stale started scheduler runs.",
    )
    scheduler_recover_parser.add_argument("--env-file", default=None)
    scheduler_recover_parser.add_argument("--older-than", default="1h")
    scheduler_recover_parser.add_argument("--dry-run", action="store_true")
    scheduler_recover_parser.add_argument("--apply", action="store_true")
    scheduler_recover_parser.set_defaults(handler=command_scheduler_recover_stale)

    scheduler_cleanup_parser = scheduler_subparsers.add_parser(
        "cleanup",
        help="Delete archived scheduler records older than a cutoff.",
    )
    scheduler_cleanup_parser.add_argument("--env-file", default=None)
    scheduler_cleanup_parser.add_argument("--archived-before", default="30d")
    scheduler_cleanup_parser.add_argument("--dry-run", action="store_true")
    scheduler_cleanup_parser.add_argument("--apply", action="store_true")
    scheduler_cleanup_parser.set_defaults(handler=command_scheduler_cleanup)

    scheduler_export_parser = scheduler_subparsers.add_parser(
        "export",
        help="Export scheduler process definitions and optional audit rows as JSON.",
    )
    scheduler_export_parser.add_argument("--env-file", default=None)
    scheduler_export_parser.add_argument("--output", default=None)
    scheduler_export_parser.add_argument("--status", action="append", dest="statuses")
    scheduler_export_parser.add_argument("--kind", action="append", dest="kinds")
    scheduler_export_parser.add_argument("--include-runs", action="store_true")
    scheduler_export_parser.add_argument("--include-events", action="store_true")
    scheduler_export_parser.add_argument("--limit", type=int, default=500)
    scheduler_export_parser.set_defaults(handler=command_scheduler_export)


def _add_run_parser(subparsers: argparse._SubParsersAction) -> None:
    run_parser = subparsers.add_parser(
        "run",
        help="Run operational entrypoints.",
    )
    run_subparsers = run_parser.add_subparsers(dest="run_target")
    run_bot_parser = run_subparsers.add_parser(
        "bot",
        help="Start the Telegram bot in polling mode.",
    )
    run_bot_parser.add_argument(
        "--env-file",
        default=None,
        help="Optional .env file to load before starting the bot.",
    )
    run_bot_parser.set_defaults(handler=command_run_bot)

    run_reconcile_parser = run_subparsers.add_parser(
        "reconcile-once",
        help="Run one broker reconciliation pass.",
    )
    run_reconcile_parser.add_argument(
        "--env-file",
        default=None,
        help="Optional .env file to load before running reconciliation.",
    )
    run_reconcile_parser.set_defaults(handler=command_run_reconcile_once)

    run_scheduler_once_parser = run_subparsers.add_parser(
        "scheduler-once",
        help="Run one scheduler worker pass.",
    )
    run_scheduler_once_parser.add_argument(
        "--env-file",
        default=None,
        help="Optional .env file to load before running the scheduler.",
    )
    run_scheduler_once_parser.add_argument("--limit", type=int, default=100)
    run_scheduler_once_parser.add_argument("--lease-seconds", type=int, default=None)
    run_scheduler_once_parser.add_argument("--stale-run-after", default=None)
    run_scheduler_once_parser.add_argument("--max-llm-runs-per-pass", type=int, default=None)
    run_scheduler_once_parser.set_defaults(handler=command_run_scheduler_once)

    for name in ("scheduler", "scheduler-worker"):
        run_scheduler_parser = run_subparsers.add_parser(
            name,
            help="Run the scheduler worker loop.",
        )
        run_scheduler_parser.add_argument(
            "--env-file",
            default=None,
            help="Optional .env file to load before running the scheduler.",
        )
        run_scheduler_parser.add_argument(
            "--poll-every",
            default="1m",
            help="Scheduler polling interval such as 30s, 1m, 15m, or 1h.",
        )
        run_scheduler_parser.add_argument("--limit", type=int, default=100)
        run_scheduler_parser.add_argument("--lease-seconds", type=int, default=None)
        run_scheduler_parser.add_argument("--stale-run-after", default=None)
        run_scheduler_parser.add_argument("--max-llm-runs-per-pass", type=int, default=None)
        run_scheduler_parser.set_defaults(handler=command_run_scheduler_worker)

    run_alpaca_news_stream_parser = run_subparsers.add_parser(
        "alpaca-news-stream",
        help="Capture Alpaca real-time news websocket events to a JSONL file.",
    )
    run_alpaca_news_stream_parser.add_argument(
        "--env-file",
        default=None,
        help="Optional .env file to load before connecting to Alpaca.",
    )
    run_alpaca_news_stream_parser.add_argument(
        "--symbols",
        action="append",
        default=None,
        help="Optional local symbol filter. Can be passed multiple times.",
    )
    run_alpaca_news_stream_parser.add_argument(
        "--output",
        default="data/alpaca_stream/news_stream.jsonl",
        help="JSONL output file path.",
    )
    run_alpaca_news_stream_parser.add_argument(
        "--max-events",
        type=int,
        default=None,
        help="Stop after writing this many matching news events.",
    )
    run_alpaca_news_stream_parser.add_argument(
        "--seconds",
        type=float,
        default=None,
        help="Stop after this many seconds if no max-events limit is reached.",
    )
    run_alpaca_news_stream_parser.add_argument(
        "--sandbox",
        action="store_true",
        help="Use Alpaca's sandbox stream host.",
    )
    run_alpaca_news_stream_parser.set_defaults(handler=command_run_alpaca_news_stream)

    for name in ("worker", "reconcile-worker"):
        run_worker_parser = run_subparsers.add_parser(
            name,
            help="Run the broker reconciliation worker loop.",
        )
        run_worker_parser.add_argument(
            "--env-file",
            default=None,
            help="Optional .env file to load before running the worker.",
        )
        run_worker_parser.add_argument(
            "--reconcile-every",
            default="1h",
            help="Reconciliation interval such as 5m, 15m, or 1h.",
        )
        run_worker_parser.set_defaults(handler=command_run_worker)


def _default_prog_name() -> str:
    argv0 = Path(sys.argv[0]).name if sys.argv else ""
    return argv0 or "brokerai"
