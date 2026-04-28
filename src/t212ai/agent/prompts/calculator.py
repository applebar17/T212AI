"""Prompt builders for calculator request extraction."""

from __future__ import annotations

from textwrap import dedent

CALCULATOR_REQUEST_SYSTEM_PROMPT = dedent(
    """\
    Convert the user's message into a structured CalculatorRequest.

    Rules:
    - Choose evaluate_formula when the request is best expressed as a single formula string.
    - Choose sum, subtract, multiply, or divide only when the user clearly wants one of those operations.
    - Choose finance-specific operations when the request is about order sizing, notional, portfolio weight, rebalance deltas, or P/L.
    - Do not perform the calculation yourself.
    - Populate only the fields needed by the chosen operation.
    - Direction for P/L must be LONG or SHORT.
    - Keep numeric values as plain decimal-friendly strings or numbers.
    """
).strip()


def build_calculator_request_user_prompt(*, user_request: str) -> str:
    return dedent(
        f"""\
        User request: {user_request}
        """
    ).strip()
