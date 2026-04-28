"""Deterministic calculator service and safe formula evaluator."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True, slots=True)
class FormulaEvaluation:
    normalized_expression: str
    result: Decimal
    explanation: str


class CalculatorService:
    def evaluate_formula(self, expression: str) -> FormulaEvaluation:
        normalized, result = _FormulaParser(str(expression or "")).evaluate()
        return FormulaEvaluation(
            normalized_expression=normalized,
            result=result,
            explanation="Evaluated the normalized formula deterministically with Decimal arithmetic.",
        )

    def sum_operands(self, operands: list[Any]) -> dict[str, Any]:
        resolved = _resolve_operands(operands)
        result = sum(resolved["values"], start=Decimal("0"))
        return {
            "operation": "sum",
            "normalizedOperands": resolved["normalized_operands"],
            "result": result,
            "explanation": f"Summed {len(resolved['values'])} operand(s) left to right.",
        }

    def subtract_operands(self, operands: list[Any]) -> dict[str, Any]:
        resolved = _resolve_operands(operands, minimum=2)
        values = resolved["values"]
        result = values[0]
        for value in values[1:]:
            result -= value
        return {
            "operation": "subtract",
            "normalizedOperands": resolved["normalized_operands"],
            "result": result,
            "explanation": "Subtracted operands left to right.",
        }

    def multiply_operands(self, operands: list[Any]) -> dict[str, Any]:
        resolved = _resolve_operands(operands)
        result = Decimal("1")
        for value in resolved["values"]:
            result *= value
        return {
            "operation": "multiply",
            "normalizedOperands": resolved["normalized_operands"],
            "result": result,
            "explanation": f"Multiplied {len(resolved['values'])} operand(s) left to right.",
        }

    def divide_operands(self, operands: list[Any]) -> dict[str, Any]:
        resolved = _resolve_operands(operands, minimum=2)
        values = resolved["values"]
        result = values[0]
        for value in values[1:]:
            if value == 0:
                raise ValueError("Division by zero is not allowed.")
            result /= value
        return {
            "operation": "divide",
            "normalizedOperands": resolved["normalized_operands"],
            "result": result,
            "explanation": "Divided operands left to right.",
        }

    def quantity_from_budget_and_price(
        self,
        *,
        budget: Any,
        price: Any,
    ) -> dict[str, Any]:
        resolved_budget = _positive_decimal(budget, "budget")
        resolved_price = _positive_decimal(price, "price")
        quantity = resolved_budget / resolved_price
        return {
            "operation": "quantity_from_budget_and_price",
            "budget": resolved_budget,
            "price": resolved_price,
            "quantity": quantity,
            "explanation": "Computed quantity as budget divided by unit price.",
        }

    def notional_from_quantity_and_price(
        self,
        *,
        quantity: Any,
        price: Any,
    ) -> dict[str, Any]:
        resolved_quantity = _decimal_value(quantity, "quantity")
        resolved_price = _positive_decimal(price, "price")
        notional = resolved_quantity * resolved_price
        return {
            "operation": "notional_from_quantity_and_price",
            "quantity": resolved_quantity,
            "price": resolved_price,
            "notional": notional,
            "explanation": "Computed notional as quantity multiplied by unit price.",
        }

    def position_weight(
        self,
        *,
        position_value: Any,
        portfolio_value: Any,
    ) -> dict[str, Any]:
        resolved_position = _decimal_value(position_value, "position_value")
        resolved_portfolio = _positive_decimal(portfolio_value, "portfolio_value")
        weight_pct = (resolved_position / resolved_portfolio) * Decimal("100")
        return {
            "operation": "position_weight",
            "positionValue": resolved_position,
            "portfolioValue": resolved_portfolio,
            "weightPct": weight_pct,
            "explanation": "Computed position weight as position value divided by portfolio value.",
        }

    def rebalance_delta(
        self,
        *,
        current_value: Any,
        target_weight_pct: Any,
        portfolio_value: Any,
    ) -> dict[str, Any]:
        resolved_current = _decimal_value(current_value, "current_value")
        resolved_target_weight = _decimal_value(target_weight_pct, "target_weight_pct")
        resolved_portfolio = _positive_decimal(portfolio_value, "portfolio_value")
        target_value = (resolved_target_weight / Decimal("100")) * resolved_portfolio
        value_delta = target_value - resolved_current
        return {
            "operation": "rebalance_delta",
            "currentValue": resolved_current,
            "targetWeightPct": resolved_target_weight,
            "portfolioValue": resolved_portfolio,
            "targetValue": target_value,
            "valueDelta": value_delta,
            "explanation": (
                "Computed the target position value from the requested portfolio weight, "
                "then derived the rebalance delta versus the current position value."
            ),
        }

    def pnl_amount(
        self,
        *,
        entry_price: Any,
        current_price: Any,
        quantity: Any,
        direction: str = "LONG",
    ) -> dict[str, Any]:
        resolved_entry = _positive_decimal(entry_price, "entry_price")
        resolved_current = _positive_decimal(current_price, "current_price")
        resolved_quantity = _positive_decimal(quantity, "quantity")
        resolved_direction = _direction_sign(direction)
        pnl = (resolved_current - resolved_entry) * resolved_quantity * resolved_direction
        return {
            "operation": "pnl_amount",
            "entryPrice": resolved_entry,
            "currentPrice": resolved_current,
            "quantity": resolved_quantity,
            "direction": "LONG" if resolved_direction > 0 else "SHORT",
            "pnlAmount": pnl,
            "explanation": "Computed absolute P/L from entry price, current price, quantity, and direction.",
        }

    def pnl_percent(
        self,
        *,
        entry_price: Any,
        current_price: Any,
        direction: str = "LONG",
    ) -> dict[str, Any]:
        resolved_entry = _positive_decimal(entry_price, "entry_price")
        resolved_current = _positive_decimal(current_price, "current_price")
        resolved_direction = _direction_sign(direction)
        pnl_pct = ((resolved_current - resolved_entry) / resolved_entry) * Decimal("100")
        pnl_pct *= resolved_direction
        return {
            "operation": "pnl_percent",
            "entryPrice": resolved_entry,
            "currentPrice": resolved_current,
            "direction": "LONG" if resolved_direction > 0 else "SHORT",
            "pnlPercent": pnl_pct,
            "explanation": "Computed percentage P/L from entry price, current price, and direction.",
        }


class _FormulaParser:
    def __init__(self, expression: str) -> None:
        self.expression = str(expression or "")
        self.tokens = _tokenize(self.expression)
        self.index = 0

    def evaluate(self) -> tuple[str, Decimal]:
        if not self.tokens:
            raise ValueError("Expression is empty.")
        result = self._parse_expression()
        if self._peek() is not None:
            raise ValueError(f"Unexpected token '{self._peek()}' in formula.")
        normalized = "".join(self.tokens)
        return normalized, result

    def _parse_expression(self) -> Decimal:
        value = self._parse_term()
        while self._peek() in {"+", "-"}:
            operator = self._consume()
            rhs = self._parse_term()
            value = value + rhs if operator == "+" else value - rhs
        return value

    def _parse_term(self) -> Decimal:
        value = self._parse_power()
        while self._peek() in {"*", "/"}:
            operator = self._consume()
            rhs = self._parse_power()
            if operator == "*":
                value *= rhs
                continue
            if rhs == 0:
                raise ValueError("Division by zero is not allowed.")
            value /= rhs
        return value

    def _parse_power(self) -> Decimal:
        value = self._parse_unary()
        if self._peek() == "^":
            self._consume()
            rhs = self._parse_power()
            value = _decimal_power(value, rhs)
        return value

    def _parse_unary(self) -> Decimal:
        if self._peek() == "-":
            self._consume()
            return -self._parse_unary()
        return self._parse_postfix()

    def _parse_postfix(self) -> Decimal:
        value = self._parse_primary()
        while self._peek() == "%":
            self._consume()
            value /= Decimal("100")
        return value

    def _parse_primary(self) -> Decimal:
        token = self._peek()
        if token is None:
            raise ValueError("Unexpected end of expression.")
        if token == "(":
            self._consume()
            value = self._parse_expression()
            self._expect(")")
            return value
        try:
            self._consume()
            return Decimal(token)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Unexpected token '{token}' in formula.") from exc

    def _peek(self) -> str | None:
        if self.index >= len(self.tokens):
            return None
        return self.tokens[self.index]

    def _consume(self) -> str:
        token = self._peek()
        if token is None:
            raise ValueError("Unexpected end of expression.")
        self.index += 1
        return token

    def _expect(self, token: str) -> None:
        actual = self._consume()
        if actual != token:
            raise ValueError(f"Expected '{token}' but found '{actual}'.")


def _tokenize(expression: str) -> list[str]:
    normalized = (
        str(expression or "")
        .replace("×", "*")
        .replace("x", "*")
        .replace("X", "*")
        .replace("[", "(")
        .replace("]", ")")
    )
    tokens: list[str] = []
    index = 0
    while index < len(normalized):
        char = normalized[index]
        if char.isspace():
            index += 1
            continue
        if char in "+-*/^()%()":
            tokens.append(char)
            index += 1
            continue
        if char.isdigit() or char == ".":
            end = index + 1
            decimal_points = 1 if char == "." else 0
            while end < len(normalized):
                current = normalized[end]
                if current == ".":
                    decimal_points += 1
                    if decimal_points > 1:
                        raise ValueError("Invalid decimal literal in formula.")
                    end += 1
                    continue
                if current.isdigit():
                    end += 1
                    continue
                break
            token = normalized[index:end]
            if token == ".":
                raise ValueError("Invalid standalone decimal point in formula.")
            tokens.append(token)
            index = end
            continue
        raise ValueError(f"Unsupported token '{char}' in formula.")
    return tokens


def _resolve_operands(
    operands: list[Any],
    *,
    minimum: int = 1,
) -> dict[str, Any]:
    if len(operands) < minimum:
        raise ValueError(f"At least {minimum} operand(s) are required.")
    values: list[Decimal] = []
    normalized_operands: list[str] = []
    for operand in operands:
        value, normalized = _resolve_operand(operand)
        values.append(value)
        normalized_operands.append(normalized)
    return {"values": values, "normalized_operands": normalized_operands}


def _resolve_operand(operand: Any) -> tuple[Decimal, str]:
    if isinstance(operand, str):
        stripped = operand.strip()
        if not stripped:
            raise ValueError("Operands must not be empty.")
        normalized, value = _FormulaParser(stripped).evaluate()
        return value, normalized
    value = _decimal_value(operand, "operand")
    return value, _format_decimal(value)


def _direction_sign(direction: str) -> Decimal:
    if str(direction or "").strip().upper() == "SHORT":
        return Decimal("-1")
    return Decimal("1")


def _decimal_value(value: Any, field_name: str) -> Decimal:
    if value is None or value == "":
        raise ValueError(f"{field_name} is required.")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field_name} must be a valid decimal number.") from exc


def _positive_decimal(value: Any, field_name: str) -> Decimal:
    resolved = _decimal_value(value, field_name)
    if resolved <= 0:
        raise ValueError(f"{field_name} must be greater than zero.")
    return resolved


def _decimal_power(base: Decimal, exponent: Decimal) -> Decimal:
    if exponent == exponent.to_integral_value():
        return base ** int(exponent)
    return Decimal(str(float(base) ** float(exponent)))


def _format_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")
