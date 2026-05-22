from __future__ import annotations

import json
from typing import Mapping

from t212ai.app.bootstrap import ConfigAssessment, ProviderAssessment
from t212ai.app.config import AppSettings

from .common import _display_env_value
from .constants import MANAGED_ENV_SECTIONS


def render_configuration_review(updates: Mapping[str, str]) -> str:
    lines = ["Configuration review"]
    for section_name, keys in MANAGED_ENV_SECTIONS:
        relevant = [key for key in keys if key in updates]
        if not relevant:
            continue
        lines.append("")
        lines.append(f"{section_name}:")
        for key in relevant:
            lines.append(f"- {key}={_display_env_value(key, updates[key])}")
    return "\n".join(lines)


def render_doctor_report(
    settings: AppSettings,
    assessment: ConfigAssessment,
    preflight,
    *,
    smoke_results: Mapping[str, object] | None = None,
) -> str:
    lines = [
        "brokerai doctor",
        "",
        f"Configuration status: {'valid' if assessment.is_valid else 'invalid'}",
        f"Run bot preflight: {'ready' if preflight.ok else 'blocked'}",
        "",
        "Providers:",
    ]
    for key in (
        "llm",
        "broker",
        "telegram",
        "yahoo",
        "alpaca",
        "alpha_vantage",
        "reddit",
        "searxng",
        "sec_edgar",
    ):
        provider = assessment.providers[key]
        lines.extend(_render_provider(provider))

    lines.append("")
    lines.append("Capabilities:")
    for key in (
        "llm_reasoning",
        "telegram_bridge",
        "broker_read",
        "broker_execution_eligibility",
        "market_data",
        "market_intelligence",
        "disclosure",
        "research_community_context",
        "search",
        "persistent_guideline_memory",
        "market_signal_memory",
        "scheduled_processes",
        "scheduler_notifications",
        "scheduler_instrument_monitor",
        "scheduler_delegate",
        "scheduler_company_event_analyst",
        "scheduler_market_regime_monitor",
        "scheduler_market_signal_capture",
        "scheduler_trade_setup_monitor",
    ):
        capability = assessment.capabilities[key]
        lines.append(
            f"- {capability.label}: {'available' if capability.available else 'unavailable'}"
        )
        if capability.selected_provider:
            lines.append(f"  provider: {capability.selected_provider}")
        for reason in capability.reasons:
            lines.append(f"  reason: {reason}")

    if assessment.configuration_errors:
        lines.append("")
        lines.append("Configuration errors:")
        for error in assessment.configuration_errors:
            lines.append(f"- {error}")

    if preflight.blocking_errors:
        lines.append("")
        lines.append("Run bot blockers:")
        for error in preflight.blocking_errors:
            lines.append(f"- {error}")

    if assessment.warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in assessment.warnings:
            lines.append(f"- {warning}")

    if smoke_results:
        lines.append("")
        lines.append("Provider smoke checks:")
        lines.append(render_provider_smoke_report(smoke_results))

    lines.append("")
    lines.append(f"LLM provider selection: {settings.llm_provider}")
    lines.append(f"GenAI context fallback tokens: {settings.genai_context_fallback_tokens}")
    lines.append(f"Broker provider selection: {settings.broker_provider}")
    lines.append(f"Market data provider selection: {settings.market_data_provider}")
    lines.append(
        f"Market intelligence provider selection: {settings.market_intelligence_provider}"
    )
    lines.append(f"Disclosure provider selection: {settings.disclosure_provider}")
    lines.append(f"Community provider selection: {settings.community_provider}")
    lines.append(f"Search provider selection: {settings.search_provider}")
    lines.append(f"Scheduler worker id: {settings.scheduler_worker_id or 'auto'}")
    lines.append(f"App log format: {settings.app_log_format}")
    lines.append(f"App log retention days: {settings.app_log_retention_days}")
    lines.append(f"Third-party log level: {settings.app_log_third_party_level}")
    lines.append(f"Scheduler lease seconds: {settings.scheduler_lease_seconds}")
    lines.append(
        f"Scheduler stale run after seconds: {settings.scheduler_stale_run_after_seconds}"
    )
    lines.append(
        "Scheduler max LLM runs per pass: "
        f"{settings.scheduler_max_llm_runs_per_pass or 'unlimited'}"
    )
    return "\n".join(lines)


def render_run_bot_failure(preflight) -> str:
    lines = ["brokerai run bot cannot start.", ""]
    lines.append("Blocking issues:")
    for error in preflight.blocking_errors:
        lines.append(f"- {error}")
    if preflight.warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in preflight.warnings:
            lines.append(f"- {warning}")
    return "\n".join(lines)


def render_reconcile_failure(preflight) -> str:
    lines = ["brokerai reconciliation cannot start.", ""]
    lines.append("Blocking issues:")
    for error in preflight.blocking_errors:
        lines.append(f"- {error}")
    if preflight.warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in preflight.warnings:
            lines.append(f"- {warning}")
    return "\n".join(lines)


def render_scheduler_failure(preflight) -> str:
    lines = ["brokerai scheduler cannot start.", ""]
    lines.append("Blocking issues:")
    for error in preflight.blocking_errors:
        lines.append(f"- {error}")
    if preflight.warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in preflight.warnings:
            lines.append(f"- {warning}")
    return "\n".join(lines)


def render_scheduler_status(status: Mapping[str, object], settings: AppSettings) -> str:
    lines = [
        "brokerai scheduler status",
        f"asOf: {status.get('asOf')}",
        f"processes: {status.get('processCount', 0)}",
        f"due: {status.get('dueCount', 0)}",
        f"startedRuns: {status.get('startedRunCount', 0)}",
        f"activeLeases: {status.get('activeLeaseCount', 0)}",
        f"nextRunAt: {status.get('nextRunAt') or 'none'}",
        f"oldestStartedRunAt: {status.get('oldestStartedRunAt') or 'none'}",
        "",
        "operational defaults:",
        f"- workerId: {settings.scheduler_worker_id or 'auto'}",
        f"- leaseSeconds: {settings.scheduler_lease_seconds}",
        f"- staleRunAfterSeconds: {settings.scheduler_stale_run_after_seconds}",
        f"- maxLlmRunsPerPass: {settings.scheduler_max_llm_runs_per_pass or 'unlimited'}",
    ]
    by_status = status.get("processesByStatus") or {}
    if isinstance(by_status, Mapping) and by_status:
        lines.append("")
        lines.append("by status:")
        for key, value in by_status.items():
            lines.append(f"- {key}: {value}")
    by_kind = status.get("processesByKind") or {}
    if isinstance(by_kind, Mapping) and by_kind:
        lines.append("")
        lines.append("by kind:")
        for key, value in by_kind.items():
            lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def render_scheduler_process_list(processes) -> str:
    if not processes:
        return "No scheduled processes matched the provided filters."
    lines = [f"Found {len(processes)} scheduled process(es)."]
    for process in processes:
        lines.append(
            "- "
            + " | ".join(
                [
                    process.process_id,
                    process.kind.value,
                    process.status.value,
                    f"title={process.title}",
                    f"nextRunAt={process.next_run_at}",
                    f"lastStatus={process.last_status.value if process.last_status else None}",
                ]
            )
        )
    return "\n".join(lines)


def render_scheduler_process_detail(process, runs, events) -> str:
    schedule_json = json.dumps(
        process.schedule.model_dump(by_alias=True, exclude_none=True, mode="json"),
        sort_keys=True,
    )
    lifecycle_json = json.dumps(
        process.lifecycle.model_dump(by_alias=True, exclude_none=True, mode="json"),
        sort_keys=True,
    )
    lines = [
        f"Scheduled process {process.process_id}",
        f"title: {process.title}",
        f"kind: {process.kind.value}",
        f"status: {process.status.value}",
        f"executionMode: {process.execution_mode.value}",
        f"nextRunAt: {process.next_run_at}",
        f"lastStatus: {process.last_status.value if process.last_status else None}",
        f"failureCount: {process.failure_count}",
        f"schedule: {schedule_json}",
        f"trigger: {json.dumps(process.trigger, sort_keys=True)}",
        f"lifecycle: {lifecycle_json}",
        "",
        f"Runs ({len(runs)}):",
    ]
    for run in runs:
        code = run.error_code or "none"
        lines.append(
            f"- {run.run_id} {run.status.value} matched={run.matched} "
            f"code={code} startedAt={run.started_at}"
        )
    lines.append("")
    lines.append(f"Events ({len(events)}):")
    for event in events:
        lines.append(
            f"- {event.created_at} {event.event_type.value}: {event.message}"
        )
    return "\n".join(lines)


def render_scheduler_maintenance_result(operation: str, result) -> str:
    mode = "dry-run" if result.dry_run else "applied"
    lines = [
        f"brokerai scheduler {operation}: {mode}",
        f"matched={result.matched_count} changed={result.changed_count}",
    ]
    if result.run_count:
        lines.append(f"runs={result.run_count}")
    if result.event_count:
        lines.append(f"events={result.event_count}")
    if result.process_ids:
        lines.append("processes: " + ", ".join(result.process_ids))
    if result.run_ids:
        lines.append("runs: " + ", ".join(result.run_ids))
    return "\n".join(lines)


def _render_provider(provider: ProviderAssessment) -> list[str]:
    if provider.ready:
        status = "ready"
    elif provider.enabled:
        status = "misconfigured"
    elif provider.configured:
        status = "configured"
    else:
        status = "disabled"
    lines = [f"- {provider.label}: {status}"]
    if provider.missing_keys:
        lines.append("  missing: " + ", ".join(provider.missing_keys))
    for note in provider.notes:
        lines.append(f"  note: {note}")
    return lines


def render_provider_smoke_report(smoke_results: Mapping[str, object]) -> str:
    lines: list[str] = []
    for result in smoke_results.values():
        status = str(getattr(result, "status", "unknown"))
        label = str(getattr(result, "label", "provider"))
        message = str(getattr(result, "message", "")).strip()
        lines.append(f"- {label}: {status}")
        if message:
            lines.append(f"  note: {message}")
        for warning in getattr(result, "warnings", ()) or ():
            lines.append(f"  warning: {warning}")
    return "\n".join(lines)
