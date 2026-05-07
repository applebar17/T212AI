"""Deterministic scheduler management helpers.

These functions are intentionally narrow and typed so they can later be exposed
behind a bounded scheduler delegate without giving the main orchestrator direct
access to arbitrary scheduler internals.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Any, Callable

from t212ai.genai.models import ToolError, ToolResult, ToolSpec
from t212ai.genai.tools.base import ToolBox, build_tool_index
from t212ai.genai.tracing import set_trace_metadata, traceable

from .models import ScheduledProcess
from .service import ScheduledProcessService


@dataclass(slots=True)
class SchedulerManagementRuntime:
    service: ScheduledProcessService | None = None


SCHEDULER_CREATE_PROCESS_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "scheduler_create_process",
        "description": (
            "Create one validated scheduled process from an already-typed process "
            "spec. Use only with explicit user intent or a configured scheduler "
            "workflow. Direct broker execution is rejected by the scheduler service."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string", "default": ""},
                "kind": {
                    "type": "string",
                    "enum": [
                        "instrument_monitor",
                        "company_event_analyst",
                        "market_regime_monitor",
                        "trade_setup_monitor",
                        "market_signal_capture",
                        "watchlist_briefing",
                        "filing_or_insider_monitor",
                        "portfolio_attention_monitor",
                    ],
                },
                "execution_mode": {
                    "type": "string",
                    "enum": ["deterministic", "llm_assisted", "llm_planned"],
                },
                "schedule": {
                    "type": "object",
                    "description": "Validated schedule spec object.",
                },
                "trigger": {
                    "type": "object",
                    "default": {},
                    "description": "Process-specific trigger configuration.",
                },
                "inputs": {
                    "type": "object",
                    "default": {},
                    "description": "Process-specific input payload.",
                },
                "llm_scope": {
                    "type": "object",
                    "default": {},
                    "description": "Optional bounded LLM scope for later LLM-assisted adapters.",
                },
                "action": {
                    "type": "object",
                    "default": {},
                    "description": "Validated action policy. Broker execution fields are rejected.",
                },
                "notification": {
                    "type": "object",
                    "default": {},
                    "description": "Notification preference/configuration for the process.",
                },
                "lifecycle": {
                    "type": "object",
                    "description": "Validated lifecycle spec object.",
                },
                "safety": {
                    "type": "object",
                    "default": {},
                    "description": "Safety policy. brokerActionsAllowed must remain false in v1.",
                },
            },
            "required": [
                "title",
                "description",
                "kind",
                "execution_mode",
                "schedule",
                "trigger",
                "inputs",
                "llm_scope",
                "action",
                "notification",
                "lifecycle",
                "safety",
            ],
            "additionalProperties": False,
        },
    },
}

SCHEDULER_LIST_PROCESSES_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "scheduler_list_processes",
        "description": (
            "List scheduled processes with optional status/kind filters. Prefer broad "
            "listing before pausing or archiving when the exact process id is unknown."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "statuses": {
                    "type": ["array", "null"],
                    "items": {
                        "type": "string",
                        "enum": ["active", "paused", "completed", "expired", "archived", "failed"],
                    },
                    "default": None,
                },
                "kinds": {
                    "type": ["array", "null"],
                    "items": {
                        "type": "string",
                        "enum": [
                            "instrument_monitor",
                            "company_event_analyst",
                            "market_regime_monitor",
                            "trade_setup_monitor",
                            "market_signal_capture",
                            "watchlist_briefing",
                            "filing_or_insider_monitor",
                            "portfolio_attention_monitor",
                        ],
                    },
                    "default": None,
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
            },
            "required": ["statuses", "kinds", "limit"],
            "additionalProperties": False,
        },
    },
}


def _process_id_tool(name: str, description: str) -> ToolSpec:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "process_id": {
                        "type": "string",
                        "description": "Exact scheduled process id, such as sched_...",
                    }
                },
                "required": ["process_id"],
                "additionalProperties": False,
            },
        },
    }


SCHEDULER_PAUSE_PROCESS_TOOL = _process_id_tool(
    "scheduler_pause_process",
    "Pause one explicit scheduled process id. This keeps the spec and audit history.",
)
SCHEDULER_RESUME_PROCESS_TOOL = _process_id_tool(
    "scheduler_resume_process",
    "Resume one explicit paused scheduled process id and recompute its next run.",
)
SCHEDULER_ARCHIVE_PROCESS_TOOL = _process_id_tool(
    "scheduler_archive_process",
    "Archive one explicit scheduled process id. Archive never deletes process records.",
)

SCHEDULER_MANAGEMENT_TOOLS: list[ToolSpec] = [
    SCHEDULER_CREATE_PROCESS_TOOL,
    SCHEDULER_LIST_PROCESSES_TOOL,
    SCHEDULER_PAUSE_PROCESS_TOOL,
    SCHEDULER_RESUME_PROCESS_TOOL,
    SCHEDULER_ARCHIVE_PROCESS_TOOL,
]

SCHEDULER_MANAGEMENT_TOOLBOX = ToolBox(
    name="scheduler_management",
    tools=SCHEDULER_MANAGEMENT_TOOLS,
    tools_by_name=build_tool_index(SCHEDULER_MANAGEMENT_TOOLS),
)


def build_scheduler_management_tool_mapping(
    service: ScheduledProcessService | None,
) -> dict[str, Callable[..., ToolResult]]:
    runtime = SchedulerManagementRuntime(service=service)
    return {
        "scheduler_create_process": partial(scheduler_create_process, runtime=runtime),
        "scheduler_list_processes": partial(scheduler_list_processes, runtime=runtime),
        "scheduler_pause_process": partial(scheduler_pause_process, runtime=runtime),
        "scheduler_resume_process": partial(scheduler_resume_process, runtime=runtime),
        "scheduler_archive_process": partial(scheduler_archive_process, runtime=runtime),
    }


@traceable(name="scheduler_create_process", run_type="tool")
def scheduler_create_process(
    *,
    title: str,
    description: str,
    kind: str,
    execution_mode: str,
    schedule: dict[str, Any],
    trigger: dict[str, Any],
    inputs: dict[str, Any],
    llm_scope: dict[str, Any],
    action: dict[str, Any],
    notification: dict[str, Any],
    lifecycle: dict[str, Any],
    safety: dict[str, Any],
    runtime: SchedulerManagementRuntime,
) -> ToolResult:
    set_trace_metadata(provider="scheduler", tool_name="scheduler_create_process")
    if runtime.service is None:
        return _missing_service()
    try:
        process = runtime.service.create_process(
            title=title,
            description=description,
            kind=kind,
            execution_mode=execution_mode,
            schedule=schedule,
            trigger=trigger,
            inputs=inputs,
            llm_scope=llm_scope,
            action=action,
            notification=notification,
            lifecycle=lifecycle,
            safety=safety,
        )
    except Exception as exc:
        return _tool_exception(exc, operation="create_process")
    return ToolResult(
        status="ok",
        output=(
            f"Created scheduled process {process.process_id}: {process.title}. "
            f"status={process.status.value} nextRunAt={process.next_run_at}."
        ),
        data={"process": _process_payload(process)},
    )


@traceable(name="scheduler_list_processes", run_type="tool")
def scheduler_list_processes(
    *,
    statuses: list[str] | None,
    kinds: list[str] | None,
    limit: int,
    runtime: SchedulerManagementRuntime,
) -> ToolResult:
    set_trace_metadata(provider="scheduler", tool_name="scheduler_list_processes")
    if runtime.service is None:
        return _missing_service()
    try:
        processes = runtime.service.list_processes(
            statuses=statuses,
            kinds=kinds,
            limit=limit,
        )
    except Exception as exc:
        return _tool_exception(exc, operation="list_processes")
    return ToolResult(
        status="ok",
        output=_list_output(processes),
        data={"count": len(processes), "processes": [_process_payload(item) for item in processes]},
    )


@traceable(name="scheduler_pause_process", run_type="tool")
def scheduler_pause_process(
    *,
    process_id: str,
    runtime: SchedulerManagementRuntime,
) -> ToolResult:
    return _lifecycle_tool(
        process_id,
        runtime=runtime,
        operation="pause_process",
        verb="Paused",
        action=lambda service, resolved_id: service.pause_process(resolved_id),
    )


@traceable(name="scheduler_resume_process", run_type="tool")
def scheduler_resume_process(
    *,
    process_id: str,
    runtime: SchedulerManagementRuntime,
) -> ToolResult:
    return _lifecycle_tool(
        process_id,
        runtime=runtime,
        operation="resume_process",
        verb="Resumed",
        action=lambda service, resolved_id: service.resume_process(resolved_id),
    )


@traceable(name="scheduler_archive_process", run_type="tool")
def scheduler_archive_process(
    *,
    process_id: str,
    runtime: SchedulerManagementRuntime,
) -> ToolResult:
    return _lifecycle_tool(
        process_id,
        runtime=runtime,
        operation="archive_process",
        verb="Archived",
        action=lambda service, resolved_id: service.archive_process(resolved_id),
    )


def _lifecycle_tool(
    process_id: str,
    *,
    runtime: SchedulerManagementRuntime,
    operation: str,
    verb: str,
    action: Callable[[ScheduledProcessService, str], ScheduledProcess],
) -> ToolResult:
    set_trace_metadata(provider="scheduler", tool_name=f"scheduler_{operation}")
    if runtime.service is None:
        return _missing_service()
    try:
        process = action(runtime.service, str(process_id).strip())
    except Exception as exc:
        return _tool_exception(exc, operation=operation)
    return ToolResult(
        status="ok",
        output=f"{verb} scheduled process {process.process_id}: {process.title}.",
        data={"process": _process_payload(process)},
    )


def _process_payload(process: ScheduledProcess) -> dict[str, Any]:
    return process.model_dump(by_alias=True, exclude_none=True, mode="json")


def _list_output(processes: list[ScheduledProcess]) -> str:
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
                ]
            )
        )
    return "\n".join(lines)


def _missing_service() -> ToolResult:
    return ToolResult(
        status="error",
        output="Scheduled processes are not configured.",
        error=ToolError(
            message="Scheduled processes are not configured.",
            code="scheduled_processes_unavailable",
            hint="Configure DATABASE_URL and ensure the scheduler database schema is available.",
            retryable=False,
        ),
    )


def _tool_exception(exc: Exception, *, operation: str) -> ToolResult:
    return ToolResult(
        status="error",
        output=f"Scheduler {operation} failed. Reason: {exc}.",
        error=ToolError(
            message=str(exc),
            code="scheduler_management_error",
            type=exc.__class__.__name__,
            hint=(
                "Use an exact process id for lifecycle operations, and for creation "
                "provide a supported kind, schedule, lifecycle, and safe action policy."
            ),
            retryable=False,
            details={"operation": operation},
        ),
    )
