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
    - For liquidation / close-position requests, set side=SELL.
    - If the user wants to exit the full position and does not provide a quantity,
      set use_full_position_size=true.
    - If the user gives an explicit share quantity for a sell/liquidation request,
      preserve that quantity.
    - For cancellation, use target_order_ref when explicit. Otherwise use selector
      latest, oldest, or only when the user's request clearly implies one.
    - For order submission, include order_type, side, ticker, quantity, notional_amount,
      notional_currency, limit_price, stop_price, time_in_force, and extended_hours
      when known.
    - If the user specifies a cash amount/value such as "around 200 euros" rather
      than a share count, put that value in notional_amount/notional_currency and
      leave quantity unset. Deterministic sizing will resolve the share quantity.
    - Only set quantity, notional_amount, limit_price, or stop_price when the value
      is already a resolved decimal-compatible number.
    - For relative cash sizing such as "half the available cash", "25% of buying
      power", or any amount that depends on broker state, do not put the phrase,
      formula, or percentage in notional_amount. The agentic flow must first
      gather broker cash, calculate the exact decimal amount, and only then
      prepare the order with that resolved value. If this extraction step does not have the
      broker state yet, leave notional_amount unset and explain the missing broker
      context in reason/risks instead of inventing a value.
    - Prefer broker-native asset identifiers when known. For Trading 212 this means
      the instrument ticker from metadata, not necessarily the public exchange symbol.
    - If only a public symbol or company name is known, put the best available
      identifier in ticker; deterministic broker metadata resolution will validate it
      before any approval is created.
    - For order submission, also include a short thesis, concise risks list, and
      confidence between 0 and 1.
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
