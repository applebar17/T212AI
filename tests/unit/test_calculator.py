from __future__ import annotations

from decimal import Decimal

from t212ai.agent import AgentReasoner
from t212ai.agent.intents import AgentIntent, IntentKind
from t212ai.agent.planner import AgentPlan, StructuredAgentPlan
from t212ai.agent.schemas import AgentRequest
from t212ai.agent.specialists import CalculatorAgent
from t212ai.calculator import CalculatorRequest, CalculatorService
from t212ai.calculator.tools import CalculatorToolRuntime, build_calculator_tool_mapping


class FakeCalculatorGenAIClient:
    def __init__(self, request: CalculatorRequest) -> None:
        self.request = request

    def chat_model_for(self, purpose: str | None = None) -> str:
        return f"{purpose or 'default'}-model"

    def generate_structured(
        self,
        schema: type,
        system_prompt: str,
        chat_message: object,
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> object:
        del system_prompt, chat_message, model, temperature, max_tokens
        if schema in {AgentPlan, StructuredAgentPlan}:
            return StructuredAgentPlan(
                intent={"kind": IntentKind.CALCULATE, "entities": [], "confidence": 0.0},
                summary="Run a deterministic calculator tool.",
                required_context=["calculator request"],
                assumptions=["The user wants an exact arithmetic answer."],
                risks=["Parsing can fail if the expression is malformed."],
            )
        if schema is CalculatorRequest:
            return self.request
        raise AssertionError(f"Unexpected schema: {schema}")


def test_formula_engine_supports_precedence_brackets_percent_and_power() -> None:
    service = CalculatorService()

    simple = service.evaluate_formula("2 + 3 * (4 - 1)")
    percent = service.evaluate_formula("200 x [10% + 0.5]")
    power = service.evaluate_formula("2 ^ 3 ^ 2")

    assert simple.result == Decimal("11")
    assert simple.normalized_expression == "2+3*(4-1)"
    assert percent.result == Decimal("120")
    assert percent.normalized_expression == "200*(10%+0.5)"
    assert power.result == Decimal("512")


def test_calculator_tools_handle_arithmetic_and_errors() -> None:
    runtime = CalculatorToolRuntime(service=CalculatorService())
    mapping = build_calculator_tool_mapping(runtime)

    summed = mapping["calc_sum"]([1, "2*3", "4"])
    divided = mapping["calc_divide"]([Decimal("100"), "5", "2"])
    invalid = mapping["calc_evaluate_formula"]("2 + unknown")

    assert summed.status == "ok"
    assert summed.data["result"] == "11"
    assert divided.status == "ok"
    assert divided.data["result"] == "10"
    assert invalid.status == "error"
    assert invalid.error is not None
    assert "Unsupported token" in invalid.error.message


def test_finance_specific_tools_return_verbose_outputs() -> None:
    runtime = CalculatorToolRuntime(service=CalculatorService())
    mapping = build_calculator_tool_mapping(runtime)

    quantity = mapping["calc_quantity_from_budget_and_price"]("500", "125")
    rebalance = mapping["calc_rebalance_delta"]("200", "12.5", "4000")
    pnl = mapping["calc_pnl_percent"]("100", "112.5", "LONG")

    assert quantity.status == "ok"
    assert quantity.data["quantity"] == "4"
    assert rebalance.status == "ok"
    assert rebalance.data["targetValue"] == "500"
    assert rebalance.data["valueDelta"] == "300"
    assert pnl.status == "ok"
    assert pnl.data["pnlPercent"] == "12.5"


def test_calculator_agent_dispatches_to_deterministic_tools() -> None:
    request = CalculatorRequest(
        operation="evaluate_formula",
        expression="37.75% * 14453",
    )
    reasoner = AgentReasoner(FakeCalculatorGenAIClient(request))  # type: ignore[arg-type]
    agent = CalculatorAgent(reasoner)

    response = agent.handle(
        AgentRequest(user_message="find the 37.75% of 14453", chat_id="chat"),
        intent=AgentIntent(kind=IntentKind.CALCULATE),
    )

    assert response.selected_agent == "calculator_agent"
    assert response.metadata["workflow"] == "calculator"
    assert response.metadata["workflow_status"] == "ok"
    assert "Result:" in response.final_answer
    assert response.artifacts["calculator_result"]["normalizedExpression"] == "37.75%*14453"
