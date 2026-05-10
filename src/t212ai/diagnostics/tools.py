"""Read-only diagnostic tools for navigating application logs."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any, Callable

from t212ai.genai.models import ToolError, ToolResult, ToolSpec
from t212ai.genai.tools.base import ToolBox, build_tool_index

from .logs import LogFileNavigator, LogQueryResult


_FILTER_PROPERTIES: dict[str, dict[str, Any]] = {
    "level": {
        "type": ["string", "null"],
        "default": None,
        "description": "Exact log level filter, for example INFO, WARNING, or ERROR.",
    },
    "logger": {
        "type": ["string", "null"],
        "default": None,
        "description": "Exact logger name filter.",
    },
    "event": {
        "type": ["string", "null"],
        "default": None,
        "description": "Exact structured event name filter.",
    },
    "component": {
        "type": ["string", "null"],
        "default": None,
        "description": "Exact app component filter.",
    },
    "agent_name": {
        "type": ["string", "null"],
        "default": None,
        "description": "Exact agent name filter.",
    },
    "selected_agent": {
        "type": ["string", "null"],
        "default": None,
        "description": "Exact selected agent filter.",
    },
    "step": {
        "type": ["string", "null"],
        "default": None,
        "description": "Exact workflow or agent step filter.",
    },
    "tool_name": {
        "type": ["string", "null"],
        "default": None,
        "description": "Exact tool name filter.",
    },
    "status": {
        "type": ["string", "null"],
        "default": None,
        "description": "Exact status filter, for example started, ok, error, or partial.",
    },
    "error_type": {
        "type": ["string", "null"],
        "default": None,
        "description": "Exact exception or provider error type filter.",
    },
    "error_code": {
        "type": ["string", "null"],
        "default": None,
        "description": "Exact machine-readable error code filter.",
    },
    "chat_id": {
        "type": ["string", "null"],
        "default": None,
        "description": "Exact Telegram chat id filter when present.",
    },
    "message_id": {
        "type": ["string", "null"],
        "default": None,
        "description": "Exact Telegram message id filter when present.",
    },
    "request_id": {
        "type": ["string", "null"],
        "default": None,
        "description": "Exact request id filter when present.",
    },
    "contains": {
        "type": ["string", "null"],
        "default": None,
        "description": "Safe case-insensitive text search across sanitized summary fields.",
    },
}


def _schema(
    *,
    properties: dict[str, dict[str, Any]],
    required: list[str],
) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


def _query_properties() -> dict[str, dict[str, Any]]:
    return {
        "since": {
            "type": ["string", "null"],
            "default": None,
            "description": "Start timestamp filter. ISO-8601 UTC is preferred.",
        },
        "until": {
            "type": ["string", "null"],
            "default": None,
            "description": "End timestamp filter. ISO-8601 UTC is preferred.",
        },
        "limit": {
            "type": "integer",
            "default": 100,
            "description": "Maximum records to return, capped by diagnostic settings.",
        },
        **_FILTER_PROPERTIES,
    }


DIAGNOSTIC_LOGS_TAIL_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "diagnostic_logs_tail",
        "description": (
            "Read the most recent sanitized application log records matching optional "
            "structured filters."
        ),
        "parameters": _schema(
            properties={
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "description": "Maximum recent records to return.",
                },
                **_FILTER_PROPERTIES,
            },
            required=["limit", *_FILTER_PROPERTIES.keys()],
        ),
        "strict": True,
    },
}


DIAGNOSTIC_LOGS_QUERY_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "diagnostic_logs_query",
        "description": (
            "Search sanitized application log records by time window and structured "
            "fields."
        ),
        "parameters": _schema(
            properties=_query_properties(),
            required=["since", "until", "limit", *_FILTER_PROPERTIES.keys()],
        ),
        "strict": True,
    },
}


DIAGNOSTIC_LOGS_CONTEXT_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "diagnostic_logs_context",
        "description": (
            "Return bounded sanitized log context around a known line number from a "
            "previous diagnostic query."
        ),
        "parameters": _schema(
            properties={
                "line_number": {
                    "type": "integer",
                    "description": "Line number returned by a previous diagnostic log result.",
                },
                "before": {
                    "type": "integer",
                    "default": 5,
                    "description": "Number of preceding lines to include, capped safely.",
                },
                "after": {
                    "type": "integer",
                    "default": 5,
                    "description": "Number of following lines to include, capped safely.",
                },
            },
            required=["line_number", "before", "after"],
        ),
        "strict": True,
    },
}


DIAGNOSTIC_LOGS_COUNTS_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "diagnostic_logs_counts",
        "description": (
            "Summarize frequencies of sanitized application log records by event, "
            "error_code, agent_name, or another supported structured field."
        ),
        "parameters": _schema(
            properties={
                "group_by": {
                    "type": "string",
                    "default": "event",
                    "description": "Structured field to group by, for example event or error_code.",
                },
                **_query_properties(),
            },
            required=[
                "group_by",
                "since",
                "until",
                "limit",
                *_FILTER_PROPERTIES.keys(),
            ],
        ),
        "strict": True,
    },
}


DIAGNOSTIC_LOGS_TOOLBOX = ToolBox(
    name="diagnostic_logs",
    tools=[
        DIAGNOSTIC_LOGS_TAIL_TOOL,
        DIAGNOSTIC_LOGS_QUERY_TOOL,
        DIAGNOSTIC_LOGS_CONTEXT_TOOL,
        DIAGNOSTIC_LOGS_COUNTS_TOOL,
    ],
    tools_by_name=build_tool_index(
        [
            DIAGNOSTIC_LOGS_TAIL_TOOL,
            DIAGNOSTIC_LOGS_QUERY_TOOL,
            DIAGNOSTIC_LOGS_CONTEXT_TOOL,
            DIAGNOSTIC_LOGS_COUNTS_TOOL,
        ]
    ),
)


def build_diagnostic_logs_tool_mapping(
    navigator: LogFileNavigator,
) -> dict[str, Callable[..., ToolResult]]:
    return {
        "diagnostic_logs_tail": partial(diagnostic_logs_tail, navigator=navigator),
        "diagnostic_logs_query": partial(diagnostic_logs_query, navigator=navigator),
        "diagnostic_logs_context": partial(diagnostic_logs_context, navigator=navigator),
        "diagnostic_logs_counts": partial(diagnostic_logs_counts, navigator=navigator),
    }


def diagnostic_logs_tail(
    *,
    navigator: LogFileNavigator,
    limit: int = 50,
    **filters: Any,
) -> ToolResult:
    unavailable = _unavailable(navigator)
    if unavailable:
        return unavailable
    result = navigator.tail(limit=limit, **_clean_filters(filters))
    return _records_result(
        "Returned recent diagnostic log records.",
        result,
        operation="tail",
    )


def diagnostic_logs_query(
    *,
    navigator: LogFileNavigator,
    since: str | None = None,
    until: str | None = None,
    limit: int = 100,
    **filters: Any,
) -> ToolResult:
    unavailable = _unavailable(navigator)
    if unavailable:
        return unavailable
    result = navigator.query(
        since=since,
        until=until,
        limit=limit,
        **_clean_filters(filters),
    )
    return _records_result(
        "Returned matching diagnostic log records.",
        result,
        operation="query",
    )


def diagnostic_logs_context(
    *,
    navigator: LogFileNavigator,
    line_number: int,
    before: int = 5,
    after: int = 5,
) -> ToolResult:
    unavailable = _unavailable(navigator)
    if unavailable:
        return unavailable
    result = navigator.context(line_number=line_number, before=before, after=after)
    return _records_result(
        "Returned bounded diagnostic log context.",
        result,
        operation="context",
    )


def diagnostic_logs_counts(
    *,
    navigator: LogFileNavigator,
    group_by: str = "event",
    since: str | None = None,
    until: str | None = None,
    limit: int = 50,
    **filters: Any,
) -> ToolResult:
    unavailable = _unavailable(navigator)
    if unavailable:
        return unavailable
    counts = navigator.counts(
        group_by=group_by,
        since=since,
        until=until,
        limit=limit,
        **_clean_filters(filters),
    )
    return ToolResult(
        status="ok",
        output="Returned diagnostic log frequency counts.",
        data=counts,
        meta={"operation": "counts", "group_by": counts.get("groupBy")},
    )


def _records_result(
    output: str,
    result: LogQueryResult,
    *,
    operation: str,
) -> ToolResult:
    payload = result.model_dump(mode="json", exclude_none=True)
    return ToolResult(
        status="ok",
        output=output,
        data=payload,
        meta={
            "operation": operation,
            "returned_count": len(result.records),
            "matched_count": result.matched_count,
            "truncated": result.truncated,
        },
    )


def _unavailable(navigator: LogFileNavigator) -> ToolResult | None:
    if navigator.available():
        return None
    path = str(Path(navigator.path).expanduser())
    return ToolResult(
        status="error",
        error=ToolError(
            message="Application log file is unavailable.",
            code="log_file_unavailable",
            hint="Verify APP_LOG_FILE_PATH and that logging has written a current log file.",
            retryable=False,
            details={"path": path},
        ),
        meta={"operation": "availability_check"},
    )


def _clean_filters(filters: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in filters.items()
        if value not in (None, "")
    }
