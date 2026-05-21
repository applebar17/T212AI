"""Proposal and approval payload helpers for broker orders."""

from __future__ import annotations

from typing import Any

from t212ai.brokers.models import BrokerOrderActionRequest


def _proposal_thesis(action_request: BrokerOrderActionRequest) -> str:
    thesis = str(action_request.thesis or "").strip()
    if thesis:
        return thesis
    return (
        f"User requested a {str(action_request.side or 'unknown').upper()} "
        f"{str(action_request.order_type or 'order').upper()} order for "
        f"{str(action_request.ticker or 'an instrument').upper()}."
    )


def _order_action_summary(action_request: BrokerOrderActionRequest) -> str:
    return (
        f"{str(action_request.side or 'BUY').upper()} "
        f"{str(action_request.ticker or 'UNKNOWN').upper()} "
        f"via {str(action_request.order_type or 'MARKET').upper()} order"
    )


def _order_intent_payload(action_request: BrokerOrderActionRequest) -> dict[str, Any]:
    payload = action_request.model_dump(mode="json")
    return {
        "action": action_request.action.value,
        "order_type": payload.get("order_type"),
        "side": payload.get("side"),
        "ticker": payload.get("ticker"),
        "quantity": payload.get("quantity"),
        "notional_amount": payload.get("notional_amount"),
        "notional_currency": payload.get("notional_currency"),
        "limit_price": payload.get("limit_price"),
        "stop_price": payload.get("stop_price"),
        "time_in_force": payload.get("time_in_force"),
        "extended_hours": payload.get("extended_hours"),
        "use_full_position_size": payload.get("use_full_position_size"),
    }

def _approval_payload_from_grouped_execution(execution_result: Any) -> dict[str, Any] | None:
    group_executions = list(getattr(execution_result, "group_executions", []) or [])
    for group in reversed(group_executions):
        actions = list(getattr(group, "actions", []) or [])
        for action in reversed(actions):
            tool_calls = list(getattr(action, "tool_calls", []) or [])
            for tool_call in reversed(tool_calls):
                if not isinstance(tool_call, dict):
                    continue
                approval = tool_call.get("telegramApproval")
                if isinstance(approval, dict):
                    return approval
    return None

def _approval_with_proposal_reference(
    approval: dict[str, Any],
    *,
    proposal_id: str,
) -> dict[str, Any]:
    text = str(approval.get("text", "")).rstrip()
    if f"Proposal ref: {proposal_id}" not in text:
        text = f"{text}\nProposal ref: {proposal_id}"
    updated = dict(approval)
    updated["proposalId"] = proposal_id
    updated["text"] = text
    return updated
