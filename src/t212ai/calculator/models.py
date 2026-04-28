"""Structured calculator request models."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class CalculatorOperation(StrEnum):
    EVALUATE_FORMULA = "evaluate_formula"
    SUM = "sum"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"
    QUANTITY_FROM_BUDGET_AND_PRICE = "quantity_from_budget_and_price"
    NOTIONAL_FROM_QUANTITY_AND_PRICE = "notional_from_quantity_and_price"
    POSITION_WEIGHT = "position_weight"
    REBALANCE_DELTA = "rebalance_delta"
    PNL_AMOUNT = "pnl_amount"
    PNL_PERCENT = "pnl_percent"


class CalculatorDirection(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class CalculatorRequest(BaseModel):
    operation: CalculatorOperation
    expression: str | None = None
    operands: list[str | int | float] = Field(default_factory=list)
    budget: str | int | float | None = None
    price: str | int | float | None = None
    quantity: str | int | float | None = None
    position_value: str | int | float | None = None
    portfolio_value: str | int | float | None = None
    current_value: str | int | float | None = None
    target_weight_pct: str | int | float | None = None
    entry_price: str | int | float | None = None
    current_price: str | int | float | None = None
    direction: CalculatorDirection = CalculatorDirection.LONG
