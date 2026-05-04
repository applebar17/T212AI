"""SEC EDGAR filing-intelligence tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from t212ai.genai.models import ToolError, ToolResult, ToolSpec
from t212ai.genai.tools.base import ToolBox, build_tool_index
from t212ai.genai.tracing import (
    _trace_tool_function_inputs,
    _trace_tool_function_outputs,
    set_trace_metadata,
    traceable,
)

from .client import SecEdgarApiError, SecEdgarClient
from .service import EdgarInsiderManager


@dataclass(slots=True)
class SecEdgarToolRuntime:
    manager: EdgarInsiderManager


_COMMON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "symbol": {
            "type": "string",
            "description": "US public-company ticker symbol, for example AAPL.",
        },
        "since_days": {
            "type": "integer",
            "minimum": 1,
            "maximum": 365,
            "description": "Lookback window in calendar days.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 50,
            "description": "Maximum filings to return in the recent list.",
        },
    },
    "required": ["symbol", "since_days", "limit"],
    "additionalProperties": False,
}


EDGAR_OWNERSHIP_ACTIVITY_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "edgar_recent_ownership_activity",
        "description": (
            "Fetch recent SEC EDGAR insider ownership filing activity (Forms 3, 4, 5) "
            "for a US public company ticker."
        ),
        "strict": True,
        "parameters": _COMMON_SCHEMA,
    },
}

EDGAR_MAJOR_STAKE_ACTIVITY_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "edgar_recent_major_stake_activity",
        "description": (
            "Fetch recent SEC EDGAR significant stake disclosure activity "
            "(13D and 13G style filings) for a US public company ticker."
        ),
        "strict": True,
        "parameters": _COMMON_SCHEMA,
    },
}

EDGAR_COMPANY_DISCLOSURE_SNAPSHOT_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "edgar_company_disclosure_snapshot",
        "description": (
            "Fetch a compact SEC EDGAR disclosure snapshot including 8-K, 10-Q, 10-K, "
            "insider ownership, and major stake filing activity."
        ),
        "strict": True,
        "parameters": _COMMON_SCHEMA,
    },
}


def build_sec_edgar_tool_mapping(
    runtime: SecEdgarToolRuntime | None = None,
) -> dict[str, Callable[..., ToolResult]]:
    resolved_runtime = runtime or SecEdgarToolRuntime(
        manager=EdgarInsiderManager(SecEdgarClient.from_settings())
    )
    return {
        "edgar_recent_ownership_activity": lambda **kwargs: edgar_recent_ownership_activity(
            runtime=resolved_runtime,
            **kwargs,
        ),
        "edgar_recent_major_stake_activity": lambda **kwargs: edgar_recent_major_stake_activity(
            runtime=resolved_runtime,
            **kwargs,
        ),
        "edgar_company_disclosure_snapshot": lambda **kwargs: edgar_company_disclosure_snapshot(
            runtime=resolved_runtime,
            **kwargs,
        ),
    }


@traceable(
    name="edgar_recent_ownership_activity",
    run_type="tool"
)
def edgar_recent_ownership_activity(
    *,
    symbol: str,
    since_days: int,
    limit: int,
    runtime: SecEdgarToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider="sec_edgar", tool_name="edgar_recent_ownership_activity")
    return _run_edgar_call(
        "recent ownership activity",
        runtime.manager.recent_ownership_activity,
        symbol=symbol,
        since_days=since_days,
        limit=limit,
    )


@traceable(
    name="edgar_recent_major_stake_activity",
    run_type="tool"
)
def edgar_recent_major_stake_activity(
    *,
    symbol: str,
    since_days: int,
    limit: int,
    runtime: SecEdgarToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider="sec_edgar", tool_name="edgar_recent_major_stake_activity")
    return _run_edgar_call(
        "recent major stake activity",
        runtime.manager.recent_major_stake_activity,
        symbol=symbol,
        since_days=since_days,
        limit=limit,
    )


@traceable(
    name="edgar_company_disclosure_snapshot",
    run_type="tool"
)
def edgar_company_disclosure_snapshot(
    *,
    symbol: str,
    since_days: int,
    limit: int,
    runtime: SecEdgarToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider="sec_edgar", tool_name="edgar_company_disclosure_snapshot")
    return _run_edgar_call(
        "company disclosure snapshot",
        runtime.manager.company_disclosure_snapshot,
        symbol=symbol,
        since_days=since_days,
        limit=limit,
    )


def _run_edgar_call(
    label: str,
    fn: Callable[..., Any],
    **kwargs: Any,
) -> ToolResult:
    try:
        result = fn(**kwargs)
    except SecEdgarApiError as exc:
        return ToolResult(
            status="error",
            output=(
                f"SEC EDGAR {label} failed. Reason: {exc}. "
                "Retry later or reduce the scope of the request."
            ),
            error=ToolError(
                message=str(exc),
                code="sec_edgar_api_error",
                type=exc.__class__.__name__,
                hint="Retry later and make sure the ticker resolves to a US public company.",
                retryable=True,
            ),
        )
    except Exception as exc:
        return ToolResult(
            status="error",
            output=(
                f"SEC EDGAR {label} failed before a usable result was produced. "
                "Validate the ticker symbol and lookback window."
            ),
            error=ToolError(
                message=str(exc),
                code="sec_edgar_tool_error",
                type=exc.__class__.__name__,
                hint="Use a valid US public-company ticker and a positive lookback window.",
                retryable=False,
            ),
        )

    return ToolResult(
        status="ok",
        output=result.render_text(),
        data=result.model_dump(mode="json"),
    )


SEC_EDGAR_DISCLOSURE_TOOLBOX = ToolBox(
    name="sec_edgar_disclosure",
    tools=[
        EDGAR_OWNERSHIP_ACTIVITY_TOOL,
        EDGAR_MAJOR_STAKE_ACTIVITY_TOOL,
        EDGAR_COMPANY_DISCLOSURE_SNAPSHOT_TOOL,
    ],
    tools_by_name=build_tool_index(
        [
            EDGAR_OWNERSHIP_ACTIVITY_TOOL,
            EDGAR_MAJOR_STAKE_ACTIVITY_TOOL,
            EDGAR_COMPANY_DISCLOSURE_SNAPSHOT_TOOL,
        ]
    ),
)
