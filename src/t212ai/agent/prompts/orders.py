"""Prompt builders for Trading 212 order action extraction."""

from __future__ import annotations

from textwrap import dedent

ORDER_ACTION_REQUEST_SYSTEM_PROMPT = dedent(
    """\
    Convert the user's Trading 212 order request into a structured Trading212OrderActionRequest.

    Rules:
    - For buy/sell/trade requests, choose prepare_submit_order.
    - For cancellation requests, choose prepare_cancel_order.
    - Do not confirm or execute; only prepare an action.
    - For cancellation, use target_order_id when explicit, otherwise use selector latest, oldest, or only when the user's request clearly implies one.
    - For order submission, include order_type, side, ticker, quantity, limit_price, stop_price, time_validity, and extended_hours when known.
    - For order submission, also include a short thesis, concise risks list, and confidence between 0 and 1.
    - Do not invent ambiguous order ids or prices.
    """
).strip()


def build_order_action_user_prompt(*, intent_kind: str, user_request: str) -> str:
    return dedent(
        f"""\
        Intent hint: {intent_kind}
        User request: {user_request}
        """
    ).strip()
