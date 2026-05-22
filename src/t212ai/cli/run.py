from __future__ import annotations

import argparse
import asyncio
import logging
import time

from t212ai.app.bootstrap import (
    assess_settings,
    ensure_runtime_directories,
    preflight_reconcile,
    preflight_run_bot,
    preflight_scheduler,
)
from t212ai.app.config import load_env_file
from t212ai.app.scheduler_worker import run_scheduler_once as run_runtime_scheduler_once

from .common import _configure_app_logging, load_settings_from_cli, parse_duration_to_seconds
from .reports import render_reconcile_failure, render_run_bot_failure, render_scheduler_failure


def _cli_api():
    import t212ai.cli as cli

    return cli


def command_run_bot(args: argparse.Namespace) -> int:
    settings = load_settings_from_cli(env_file=args.env_file)
    _configure_app_logging(settings)
    logger = logging.getLogger(__name__)
    assessment = assess_settings(settings)
    preflight = preflight_run_bot(assessment)
    if not preflight.ok:
        print(render_run_bot_failure(preflight))
        return 1

    if args.env_file is not None:
        load_env_file(args.env_file, override=True)
    ensure_runtime_directories(settings)
    runtime = _cli_api().build_runtime(settings)
    logger.info(
        "Starting Telegram bot broker_provider=%s llm_provider=%s log_file=%s",
        settings.broker_provider,
        settings.llm_provider,
        settings.app_log_file_path,
    )

    try:
        from t212ai.telegram import TelegramBotService

        TelegramBotService.from_settings(settings, runtime=runtime).run_polling()
    except Exception as exc:  # pragma: no cover - startup safety net
        print(f"brokerai run bot failed: {exc}")
        return 1
    return 0


def command_run_reconcile_once(args: argparse.Namespace) -> int:
    settings = load_settings_from_cli(env_file=args.env_file)
    _configure_app_logging(settings)
    assessment = assess_settings(settings)
    preflight = preflight_reconcile(assessment, settings)
    if not preflight.ok:
        print(render_reconcile_failure(preflight))
        return 1
    if args.env_file is not None:
        load_env_file(args.env_file, override=True)
    ensure_runtime_directories(settings)
    runtime = _cli_api().build_runtime(settings)
    if runtime.reconciliation_service is None:
        print("brokerai run reconcile-once failed: reconciliation runtime is not available.")
        return 1
    try:
        result = _cli_api().run_reconcile_once(runtime)
    except Exception as exc:  # pragma: no cover - startup safety net
        print(f"brokerai run reconcile-once failed: {exc}")
        return 1
    print(result.render_text())
    return 0


def command_run_worker(args: argparse.Namespace) -> int:
    settings = load_settings_from_cli(env_file=args.env_file)
    _configure_app_logging(settings)
    assessment = assess_settings(settings)
    preflight = preflight_reconcile(assessment, settings)
    if not preflight.ok:
        print(render_reconcile_failure(preflight))
        return 1
    try:
        interval_seconds = parse_duration_to_seconds(args.reconcile_every)
    except ValueError as exc:
        print(f"brokerai run worker failed: {exc}")
        return 1
    if args.env_file is not None:
        load_env_file(args.env_file, override=True)
    ensure_runtime_directories(settings)
    runtime = _cli_api().build_runtime(settings)
    if runtime.reconciliation_service is None:
        print("brokerai run worker failed: reconciliation runtime is not available.")
        return 1
    try:
        return _cli_api().run_reconcile_worker(runtime, interval_seconds=interval_seconds)
    except KeyboardInterrupt:
        print("brokerai worker stopped.")
        return 0
    except Exception as exc:  # pragma: no cover - startup safety net
        print(f"brokerai run worker failed: {exc}")
        return 1


def command_run_scheduler_once(args: argparse.Namespace) -> int:
    settings = load_settings_from_cli(env_file=args.env_file)
    _configure_app_logging(settings)
    assessment = assess_settings(settings)
    preflight = preflight_scheduler(assessment, settings)
    if not preflight.ok:
        print(render_scheduler_failure(preflight))
        return 1
    if args.env_file is not None:
        load_env_file(args.env_file, override=True)
    ensure_runtime_directories(settings)
    runtime = _cli_api().build_runtime(settings)
    if runtime.scheduled_process_service is None:
        print("brokerai run scheduler-once failed: scheduler runtime is not available.")
        return 1
    try:
        result = _cli_api().run_scheduler_once(
            runtime,
            limit=args.limit,
            lease_seconds=args.lease_seconds,
            stale_run_after_seconds=(
                parse_duration_to_seconds(args.stale_run_after)
                if args.stale_run_after
                else None
            ),
            max_llm_runs_per_pass=args.max_llm_runs_per_pass,
        )
    except Exception as exc:  # pragma: no cover - startup safety net
        print(f"brokerai run scheduler-once failed: {exc}")
        return 1
    print(result.render_text())
    return 0


def command_run_scheduler_worker(args: argparse.Namespace) -> int:
    settings = load_settings_from_cli(env_file=args.env_file)
    _configure_app_logging(settings)
    assessment = assess_settings(settings)
    preflight = preflight_scheduler(assessment, settings)
    if not preflight.ok:
        print(render_scheduler_failure(preflight))
        return 1
    try:
        poll_every_seconds = parse_duration_to_seconds(args.poll_every)
    except ValueError as exc:
        print(f"brokerai run scheduler failed: {exc}")
        return 1
    if args.env_file is not None:
        load_env_file(args.env_file, override=True)
    ensure_runtime_directories(settings)
    runtime = _cli_api().build_runtime(settings)
    if runtime.scheduled_process_service is None:
        print("brokerai run scheduler failed: scheduler runtime is not available.")
        return 1
    try:
        return _cli_api().run_scheduler_worker(
            runtime,
            poll_every_seconds=poll_every_seconds,
            limit=args.limit,
            lease_seconds=args.lease_seconds,
            stale_run_after_seconds=(
                parse_duration_to_seconds(args.stale_run_after)
                if args.stale_run_after
                else None
            ),
            max_llm_runs_per_pass=args.max_llm_runs_per_pass,
        )
    except KeyboardInterrupt:
        print("brokerai scheduler stopped.")
        return 0
    except Exception as exc:  # pragma: no cover - startup safety net
        print(f"brokerai run scheduler failed: {exc}")
        return 1


def command_run_alpaca_news_stream(args: argparse.Namespace) -> int:
    settings = load_settings_from_cli(env_file=args.env_file)
    _configure_app_logging(settings)
    if not settings.alpaca_api_key or not settings.alpaca_api_secret:
        print(
            "brokerai run alpaca-news-stream failed: Alpaca API credentials are missing."
        )
        return 1
    try:
        from t212ai.alpaca import AlpacaStreamClient, capture_alpaca_news_stream

        client = AlpacaStreamClient.from_settings(settings)
        result = asyncio.run(
            capture_alpaca_news_stream(
                client,
                args.output,
                symbols=args.symbols or [],
                max_events=args.max_events,
                seconds=args.seconds,
                sandbox=bool(args.sandbox),
            )
        )
    except KeyboardInterrupt:
        print("brokerai alpaca news stream stopped.")
        return 0
    except Exception as exc:  # pragma: no cover - live stream safety net
        print(f"brokerai run alpaca-news-stream failed: {exc}")
        return 1
    print(result.render_text())
    return 0


def run_reconcile_once(runtime) -> object:
    if runtime.reconciliation_service is None:
        raise RuntimeError("Reconciliation service is not configured.")
    return runtime.reconciliation_service.reconcile_once()


def run_reconcile_worker(runtime, *, interval_seconds: int) -> int:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than zero.")
    while True:
        result = _cli_api().run_reconcile_once(runtime)
        print(result.render_text())
        time.sleep(interval_seconds)


def run_scheduler_once(
    runtime,
    *,
    limit: int = 100,
    lease_seconds: int | None = None,
    stale_run_after_seconds: int | None = None,
    max_llm_runs_per_pass: int | None = None,
) -> object:
    return run_runtime_scheduler_once(
        runtime,
        limit=limit,
        lease_seconds=lease_seconds,
        stale_run_after_seconds=stale_run_after_seconds,
        max_llm_runs_per_pass=max_llm_runs_per_pass,
    )


def run_scheduler_worker(
    runtime,
    *,
    poll_every_seconds: int,
    limit: int = 100,
    lease_seconds: int | None = None,
    stale_run_after_seconds: int | None = None,
    max_llm_runs_per_pass: int | None = None,
) -> int:
    if poll_every_seconds <= 0:
        raise ValueError("poll_every_seconds must be greater than zero.")
    while True:
        result = _cli_api().run_scheduler_once(
            runtime,
            limit=limit,
            lease_seconds=lease_seconds,
            stale_run_after_seconds=stale_run_after_seconds,
            max_llm_runs_per_pass=max_llm_runs_per_pass,
        )
        print(result.render_text())
        time.sleep(poll_every_seconds)
