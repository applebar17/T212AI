from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from t212ai.app.bootstrap import assess_settings, ensure_runtime_directories, preflight_scheduler
from t212ai.app.config import load_env_file

from .common import _configure_app_logging, load_settings_from_cli, parse_duration_to_seconds
from .reports import (
    render_scheduler_failure,
    render_scheduler_maintenance_result,
    render_scheduler_process_detail,
    render_scheduler_process_list,
    render_scheduler_status,
)


def _cli_api():
    import t212ai.cli as cli

    return cli


def command_scheduler_status(args: argparse.Namespace) -> int:
    runtime = _build_scheduler_runtime_for_command(args, "scheduler status")
    if runtime is None:
        return 1
    status = runtime.scheduled_process_service.scheduler_status()
    print(render_scheduler_status(status, runtime.settings))
    return 0


def command_scheduler_list(args: argparse.Namespace) -> int:
    runtime = _build_scheduler_runtime_for_command(args, "scheduler list")
    if runtime is None:
        return 1
    try:
        processes = runtime.scheduled_process_service.list_processes(
            statuses=args.statuses,
            kinds=args.kinds,
            limit=args.limit,
        )
    except Exception as exc:
        print(f"brokerai scheduler list failed: {exc}")
        return 1
    print(render_scheduler_process_list(processes))
    return 0


def command_scheduler_show(args: argparse.Namespace) -> int:
    runtime = _build_scheduler_runtime_for_command(args, "scheduler show")
    if runtime is None:
        return 1
    process = runtime.scheduled_process_service.get_process(args.process_id)
    if process is None:
        print(f"brokerai scheduler show failed: process {args.process_id} was not found.")
        return 1
    runs = runtime.scheduled_process_service.list_runs(process.process_id, limit=args.runs)
    events = runtime.scheduled_process_service.list_events(process.process_id, limit=args.events)
    print(render_scheduler_process_detail(process, runs, events))
    return 0


def command_scheduler_recover_stale(args: argparse.Namespace) -> int:
    runtime = _build_scheduler_runtime_for_command(args, "scheduler recover-stale")
    if runtime is None:
        return 1
    try:
        older_than_seconds = parse_duration_to_seconds(args.older_than)
        result = runtime.scheduled_process_service.recover_stale_runs(
            stale_after_seconds=older_than_seconds,
            dry_run=not bool(args.apply),
        )
    except Exception as exc:
        print(f"brokerai scheduler recover-stale failed: {exc}")
        return 1
    print(render_scheduler_maintenance_result("recover-stale", result))
    return 0


def command_scheduler_cleanup(args: argparse.Namespace) -> int:
    runtime = _build_scheduler_runtime_for_command(args, "scheduler cleanup")
    if runtime is None:
        return 1
    try:
        cutoff = _cutoff_from_duration_or_iso(args.archived_before)
        result = runtime.scheduled_process_service.delete_archived_before(
            cutoff,
            dry_run=not bool(args.apply),
        )
    except Exception as exc:
        print(f"brokerai scheduler cleanup failed: {exc}")
        return 1
    print(render_scheduler_maintenance_result("cleanup", result))
    return 0


def command_scheduler_export(args: argparse.Namespace) -> int:
    runtime = _build_scheduler_runtime_for_command(args, "scheduler export")
    if runtime is None:
        return 1
    try:
        payload = runtime.scheduled_process_service.export_processes(
            statuses=args.statuses,
            kinds=args.kinds,
            include_runs=bool(args.include_runs),
            include_events=bool(args.include_events),
            limit=args.limit,
        )
    except Exception as exc:
        print(f"brokerai scheduler export failed: {exc}")
        return 1
    rendered = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        print(f"Exported {payload['processCount']} scheduled process(es) to {args.output}.")
    else:
        print(rendered)
    return 0


def _build_scheduler_runtime_for_command(args: argparse.Namespace, command_name: str):
    settings = load_settings_from_cli(env_file=args.env_file)
    _configure_app_logging(settings)
    assessment = assess_settings(settings)
    preflight = preflight_scheduler(assessment, settings)
    if not preflight.ok:
        print(render_scheduler_failure(preflight))
        return None
    if args.env_file is not None:
        load_env_file(args.env_file, override=True)
    ensure_runtime_directories(settings)
    runtime = _cli_api().build_runtime(settings)
    if runtime.scheduled_process_service is None:
        print(f"brokerai {command_name} failed: scheduler runtime is not available.")
        return None
    return runtime


def _cutoff_from_duration_or_iso(raw: str) -> datetime:
    value = str(raw or "").strip()
    if not value:
        raise ValueError("Cutoff is required.")
    try:
        seconds = parse_duration_to_seconds(value)
    except ValueError:
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError(
                "Cutoff must be a duration such as 30d or an ISO-8601 datetime."
            ) from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)
