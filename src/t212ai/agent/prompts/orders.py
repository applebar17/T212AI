"""Prompt builders for generic broker order action extraction."""

from __future__ import annotations

from textwrap import dedent

ORDER_ACTION_REQUEST_SYSTEM_PROMPT = dedent(
    """\
    Convert the user's broker order request into a structured BrokerOrderActionRequest.

    Rules:
    - For buy/sell/trade requests, choose prepare_submit_order.
    - For cancellation requests, choose prepare_cancel_order.
    - Do not confirm or execute; only prepare an action.
    - For cancellation, use target_order_ref when explicit, otherwise use selector latest, oldest, or only when the user's request clearly implies one.
    - For order submission, include order_type, side, ticker, quantity, limit_price, stop_price, time_in_force, and extended_hours when known.
    - For order submission, also include a short thesis, concise risks list, and confidence between 0 and 1.
    - Do not invent ambiguous order references or prices.
    """
).strip()


def build_order_action_user_prompt(
    *,
    intent_kind: str,
    user_request: str,
    orchestrator_guidance: str | None = None,
) -> str:
    prompt = dedent(
        f"""\
        Intent hint: {intent_kind}
        User request: {user_request}
        """
    ).strip()
    if orchestrator_guidance:
        prompt = f"{prompt}\nOrchestrator guidance: {orchestrator_guidance}"
    return prompt
