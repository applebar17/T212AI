"""Deterministic calculator tools."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

from t212ai.genai.models import ToolError, ToolResult, ToolSpec
from t212ai.genai.tools.tools import ToolBox, build_tool_index
from t212ai.genai.tracing import (
    _trace_tool_function_inputs,
    _trace_tool_function_outputs,
    set_trace_metadata,
    traceable,
)

from .service import CalculatorService


@dataclass(slots=True)
class CalculatorToolRuntime:
    service: CalculatorService


CALC_EVALUATE_FORMULA_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "calc_evaluate_formula",
        "description": (
            "Safely evaluate a mathematical formula string with Decimal arithmetic. "
            "Supports +, -, *, /, ^, unary minus, parentheses, [], x or × as "
            "multiplication, and postfix %."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Formula string to evaluate deterministically.",
                }
            },
            "required": ["expression"],
            "additionalProperties": False,
        },
    },
}

_OPERANDS_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "operands": {
            "type": "array",
            "items": {
                "anyOf": [{"type": "number"}, {"type": "string"}],
            },
            "description": "Numbers or sub-expression strings to evaluate deterministically.",
        }
    },
    "required": ["operands"],
    "additionalProperties": False,
}

CALC_SUM_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "calc_sum",
        "description": "Sum multiple operands deterministically.",
        "strict": True,
        "parameters": _OPERANDS_PARAMETERS,
    },
}

CALC_SUBTRACT_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "calc_subtract",
        "description": "Subtract multiple operands left to right.",
        "strict": True,
        "parameters": _OPERANDS_PARAMETERS,
    },
}

CALC_MULTIPLY_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "calc_multiply",
        "description": "Multiply multiple operands deterministically.",
        "strict": True,
        "parameters": _OPERANDS_PARAMETERS,
    },
}

CALC_DIVIDE_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "calc_divide",
        "description": "Divide multiple operands left to right.",
        "strict": True,
        "parameters": _OPERANDS_PARAMETERS,
    },
}

CALC_QUANTITY_FROM_BUDGET_AND_PRICE_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "calc_quantity_from_budget_and_price",
        "description": "Compute quantity as budget divided by unit price.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "budget": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                "price": {"anyOf": [{"type": "number"}, {"type": "string"}]},
            },
            "required": ["budget", "price"],
            "additionalProperties": False,
        },
    },
}

CALC_NOTIONAL_FROM_QUANTITY_AND_PRICE_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "calc_notional_from_quantity_and_price",
        "description": "Compute notional as quantity multiplied by unit price.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "quantity": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                "price": {"anyOf": [{"type": "number"}, {"type": "string"}]},
            },
            "required": ["quantity", "price"],
            "additionalProperties": False,
        },
    },
}

CALC_POSITION_WEIGHT_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "calc_position_weight",
        "description": "Compute a position weight percentage relative to a portfolio value.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "position_value": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                "portfolio_value": {"anyOf": [{"type": "number"}, {"type": "string"}]},
            },
            "required": ["position_value", "portfolio_value"],
            "additionalProperties": False,
        },
    },
}

CALC_REBALANCE_DELTA_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "calc_rebalance_delta",
        "description": (
            "Compute the target position value and value delta needed to reach a target portfolio weight."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "current_value": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                "target_weight_pct": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                "portfolio_value": {"anyOf": [{"type": "number"}, {"type": "string"}]},
            },
            "required": ["current_value", "target_weight_pct", "portfolio_value"],
            "additionalProperties": False,
        },
    },
}

CALC_PNL_AMOUNT_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "calc_pnl_amount",
        "description": "Compute absolute P/L from entry price, current price, quantity, and direction.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "entry_price": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                "current_price": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                "quantity": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                "direction": {"type": "string", "enum": ["LONG", "SHORT"], "default": "LONG"},
            },
            "required": ["entry_price", "current_price", "quantity", "direction"],
            "additionalProperties": False,
        },
    },
}

CALC_PNL_PERCENT_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "calc_pnl_percent",
        "description": "Compute percentage P/L from entry price, current price, and direction.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "entry_price": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                "current_price": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                "direction": {"type": "string", "enum": ["LONG", "SHORT"], "default": "LONG"},
            },
            "required": ["entry_price", "current_price", "direction"],
            "additionalProperties": False,
        },
    },
}

CALCULATOR_TOOLS: list[ToolSpec] = [
    CALC_EVALUATE_FORMULA_TOOL,
    CALC_SUM_TOOL,
    CALC_SUBTRACT_TOOL,
    CALC_MULTIPLY_TOOL,
    CALC_DIVIDE_TOOL,
    CALC_QUANTITY_FROM_BUDGET_AND_PRICE_TOOL,
    CALC_NOTIONAL_FROM_QUANTITY_AND_PRICE_TOOL,
    CALC_POSITION_WEIGHT_TOOL,
    CALC_REBALANCE_DELTA_TOOL,
    CALC_PNL_AMOUNT_TOOL,
    CALC_PNL_PERCENT_TOOL,
]

CALCULATOR_TOOLBOX = ToolBox(
    name="calculator",
    tools=CALCULATOR_TOOLS,
    tools_by_name=build_tool_index(CALCULATOR_TOOLS),
)


def build_calculator_tool_mapping(
    runtime: CalculatorToolRuntime,
) -> dict[str, Callable[..., ToolResult]]:
    return {
        "calc_evaluate_formula": lambda expression: calc_evaluate_formula(
            expression=expression,
            runtime=runtime,
        ),
        "calc_sum": lambda operands: calc_sum(operands=operands, runtime=runtime),
        "calc_subtract": lambda operands: calc_subtract(operands=operands, runtime=runtime),
        "calc_multiply": lambda operands: calc_multiply(operands=operands, runtime=runtime),
        "calc_divide": lambda operands: calc_divide(operands=operands, runtime=runtime),
        "calc_quantity_from_budget_and_price": lambda budget, price: calc_quantity_from_budget_and_price(
            budget=budget,
            price=price,
            runtime=runtime,
        ),
        "calc_notional_from_quantity_and_price": lambda quantity, price: calc_notional_from_quantity_and_price(
            quantity=quantity,
            price=price,
            runtime=runtime,
        ),
        "calc_position_weight": lambda position_value, portfolio_value: calc_position_weight(
            position_value=position_value,
            portfolio_value=portfolio_value,
            runtime=runtime,
        ),
        "calc_rebalance_delta": lambda current_value, target_weight_pct, portfolio_value: calc_rebalance_delta(
            current_value=current_value,
            target_weight_pct=target_weight_pct,
            portfolio_value=portfolio_value,
            runtime=runtime,
        ),
        "calc_pnl_amount": lambda entry_price, current_price, quantity, direction="LONG": calc_pnl_amount(
            entry_price=entry_price,
            current_price=current_price,
            quantity=quantity,
            direction=direction,
            runtime=runtime,
        ),
        "calc_pnl_percent": lambda entry_price, current_price, direction="LONG": calc_pnl_percent(
            entry_price=entry_price,
            current_price=current_price,
            direction=direction,
            runtime=runtime,
        ),
    }


@traceable(
    name="calc_evaluate_formula",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def calc_evaluate_formula(*, expression: str, runtime: CalculatorToolRuntime) -> ToolResult:
    set_trace_metadata(provider="calculator", tool_name="calc_evaluate_formula")
    return _wrap_tool_call(
        lambda: _formula_result(runtime.service.evaluate_formula(expression)),
        hint="Provide a valid arithmetic expression using numbers, operators, and parentheses only.",
    )


@traceable(
    name="calc_sum",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def calc_sum(*, operands: list[Any], runtime: CalculatorToolRuntime) -> ToolResult:
    set_trace_metadata(provider="calculator", tool_name="calc_sum")
    return _wrap_tool_call(
        lambda: runtime.service.sum_operands(operands),
        hint="Pass at least one numeric operand or sub-expression.",
    )


@traceable(
    name="calc_subtract",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def calc_subtract(*, operands: list[Any], runtime: CalculatorToolRuntime) -> ToolResult:
    set_trace_metadata(provider="calculator", tool_name="calc_subtract")
    return _wrap_tool_call(
        lambda: runtime.service.subtract_operands(operands),
        hint="Pass at least two numeric operands or sub-expressions for subtraction.",
    )


@traceable(
    name="calc_multiply",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def calc_multiply(*, operands: list[Any], runtime: CalculatorToolRuntime) -> ToolResult:
    set_trace_metadata(provider="calculator", tool_name="calc_multiply")
    return _wrap_tool_call(
        lambda: runtime.service.multiply_operands(operands),
        hint="Pass at least one numeric operand or sub-expression.",
    )


@traceable(
    name="calc_divide",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def calc_divide(*, operands: list[Any], runtime: CalculatorToolRuntime) -> ToolResult:
    set_trace_metadata(provider="calculator", tool_name="calc_divide")
    return _wrap_tool_call(
        lambda: runtime.service.divide_operands(operands),
        hint="Pass at least two numeric operands or sub-expressions and avoid zero divisors.",
    )


@traceable(
    name="calc_quantity_from_budget_and_price",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def calc_quantity_from_budget_and_price(
    *,
    budget: Any,
    price: Any,
    runtime: CalculatorToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider="calculator", tool_name="calc_quantity_from_budget_and_price")
    return _wrap_tool_call(
        lambda: runtime.service.quantity_from_budget_and_price(budget=budget, price=price),
        hint="Pass positive numeric values for both budget and price.",
    )


@traceable(
    name="calc_notional_from_quantity_and_price",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def calc_notional_from_quantity_and_price(
    *,
    quantity: Any,
    price: Any,
    runtime: CalculatorToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider="calculator", tool_name="calc_notional_from_quantity_and_price")
    return _wrap_tool_call(
        lambda: runtime.service.notional_from_quantity_and_price(
            quantity=quantity,
            price=price,
        ),
        hint="Pass numeric quantity and a positive numeric price.",
    )


@traceable(
    name="calc_position_weight",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def calc_position_weight(
    *,
    position_value: Any,
    portfolio_value: Any,
    runtime: CalculatorToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider="calculator", tool_name="calc_position_weight")
    return _wrap_tool_call(
        lambda: runtime.service.position_weight(
            position_value=position_value,
            portfolio_value=portfolio_value,
        ),
        hint="Pass numeric position and portfolio values, with portfolio value greater than zero.",
    )


@traceable(
    name="calc_rebalance_delta",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def calc_rebalance_delta(
    *,
    current_value: Any,
    target_weight_pct: Any,
    portfolio_value: Any,
    runtime: CalculatorToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider="calculator", tool_name="calc_rebalance_delta")
    return _wrap_tool_call(
        lambda: runtime.service.rebalance_delta(
            current_value=current_value,
            target_weight_pct=target_weight_pct,
            portfolio_value=portfolio_value,
        ),
        hint="Pass numeric current value, target weight percentage, and a positive portfolio value.",
    )


@traceable(
    name="calc_pnl_amount",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def calc_pnl_amount(
    *,
    entry_price: Any,
    current_price: Any,
    quantity: Any,
    direction: str = "LONG",
    runtime: CalculatorToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider="calculator", tool_name="calc_pnl_amount")
    return _wrap_tool_call(
        lambda: runtime.service.pnl_amount(
            entry_price=entry_price,
            current_price=current_price,
            quantity=quantity,
            direction=direction,
        ),
        hint="Pass positive numeric entry/current prices, positive quantity, and direction LONG or SHORT.",
    )


@traceable(
    name="calc_pnl_percent",
    run_type="tool",
    process_inputs=_trace_tool_function_inputs,
    process_outputs=_trace_tool_function_outputs,
)
def calc_pnl_percent(
    *,
    entry_price: Any,
    current_price: Any,
    direction: str = "LONG",
    runtime: CalculatorToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider="calculator", tool_name="calc_pnl_percent")
    return _wrap_tool_call(
        lambda: runtime.service.pnl_percent(
            entry_price=entry_price,
            current_price=current_price,
            direction=direction,
        ),
        hint="Pass positive numeric entry/current prices and direction LONG or SHORT.",
    )


def _wrap_tool_call(
    fn: Callable[[], Any],
    *,
    hint: str,
) -> ToolResult:
    try:
        payload = fn()
    except Exception as exc:
        return ToolResult(
            status="error",
            error=ToolError(
                message=str(exc),
                code="calculator_tool_error",
                type=exc.__class__.__name__,
                hint=hint,
                retryable=False,
            ),
            meta={"provider": "calculator"},
        )
    result_payload = _json_safe(payload)
    if isinstance(result_payload, dict):
        explanation = str(result_payload.get("explanation") or "Calculation completed.")
        if "result" in result_payload:
            preview = result_payload["result"]
            output = f"{explanation} Result: {preview}."
        elif "quantity" in result_payload:
            output = f"{explanation} Quantity: {result_payload['quantity']}."
        elif "notional" in result_payload:
            output = f"{explanation} Notional: {result_payload['notional']}."
        elif "weightPct" in result_payload:
            output = f"{explanation} Weight: {result_payload['weightPct']}%."
        elif "valueDelta" in result_payload:
            output = f"{explanation} Rebalance delta: {result_payload['valueDelta']}."
        elif "pnlAmount" in result_payload:
            output = f"{explanation} P/L amount: {result_payload['pnlAmount']}."
        elif "pnlPercent" in result_payload:
            output = f"{explanation} P/L percent: {result_payload['pnlPercent']}%."
        else:
            output = explanation
    else:
        output = "Calculation completed."
    return ToolResult(
        status="ok",
        output=output,
        data=result_payload,
        meta={"provider": "calculator"},
    )


def _formula_result(payload) -> dict[str, Any]:
    return {
        "operation": "evaluate_formula",
        "normalizedExpression": payload.normalized_expression,
        "result": payload.result,
        "explanation": payload.explanation,
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value
