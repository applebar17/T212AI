"""Output helpers for news judge execution results."""

from __future__ import annotations

from typing import Any

from .schemas import NewsJudgeResult


def _approval_payload_from_execution(execution: Any) -> dict[str, Any] | None:
    for group in reversed(list(getattr(execution, "group_executions", []) or [])):
        for action in reversed(list(getattr(group, "actions", []) or [])):
            for tool_call in reversed(list(getattr(action, "tool_calls", []) or [])):
                if isinstance(tool_call, dict) and isinstance(
                    tool_call.get("telegramApproval"),
                    dict,
                ):
                    return tool_call["telegramApproval"]
    return None


def _result_text(result: NewsJudgeResult) -> str:
    if result.outcome and result.summary:
        return f"{result.summary}\n\n{result.outcome}"
    return result.summary or result.outcome
