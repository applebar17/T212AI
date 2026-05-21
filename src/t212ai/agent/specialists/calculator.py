"""Calculator specialist agent."""

from __future__ import annotations

import logging
import time

from t212ai.app.logging import log_event
from t212ai.calculator import (
    CALCULATOR_TOOLBOX,
    CalculatorRequest,
    CalculatorService,
    CalculatorToolRuntime,
    build_calculator_tool_mapping,
)
from t212ai.genai.models import ToolError, ToolResult
from t212ai.genai.tracing import set_trace_metadata, set_trace_name, traceable
from t212ai.guidelines.service import GuidelineMemoryService

from ..base import AgentProfile, BaseAgent
from ..intents import AgentIntent, IntentKind
from ..planner import TaskComplexity
from ..prompts import CALCULATOR_REQUEST_SYSTEM_PROMPT, build_calculator_request_user_prompt
from ..schemas import AgentRequest, AgentResponse

LOGGER = logging.getLogger(__name__)


class CalculatorAgent(BaseAgent):
    def __init__(
        self,
        reasoner,
        guideline_service: GuidelineMemoryService | None = None,
        *,
        calculator_service: CalculatorService | None = None,
    ) -> None:
        super().__init__(
            reasoner,
            AgentProfile(
                name="calculator_agent",
                purpose=(
                    "Translate natural-language calculation requests into deterministic "
                    "formula or finance-specific calculations."
                ),
                guidelines=(
                    "Route calculation requests to "
                    "deterministic calculator tools and return concise, auditable results."
                ),
                toolbox_summary=(
                    "Deterministic calculator tools: formula evaluation, arithmetic, "
                    "and finance-specific sizing and P/L helpers."
                ),
                task_complexity=TaskComplexity.EASY,
                guideline_scopes=("global", "agent:calculator"),
                toolbox=CALCULATOR_TOOLBOX,
            ),
            guideline_service=guideline_service,
        )
        self.calculator_service = calculator_service or CalculatorService()

    @traceable(
        name="Calculator Agent Execute",
        run_type="chain"
    )
    def execute(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent,
        task_complexity: TaskComplexity,
        plan,
    ) -> AgentResponse | None:
        set_trace_name(f"{self.__class__.__name__}.execute")
        set_trace_metadata(
            agent_name=self.name,
            agent_step="execute",
            step_kind="execute",
            intent_kind=intent.kind.value,
            task_complexity=task_complexity.value,
            workflow="calculator",
        )
        if intent.kind != IntentKind.CALCULATE:
            return None
        try:
            calculation_request = self._build_calculation_request(request)
            result = self._execute_calculation_request(calculation_request)
        except Exception as exc:
            return AgentResponse(
                final_answer=(
                    "I couldn't translate the request into a deterministic calculation. "
                    f"Reason: {exc}"
                ),
                selected_agent=self.name,
                plan=plan,
                metadata={"workflow": "calculator", "workflow_status": "error"},
            )
        metadata = {
            "workflow": "calculator",
            "workflow_status": result.status,
            "operation": calculation_request.operation.value,
        }
        if result.status == "ok":
            return AgentResponse(
                final_answer=result.output or "Calculation completed.",
                selected_agent=self.name,
                plan=plan,
                metadata=metadata,
                artifacts={
                    "workflow": "calculator",
                    "calculator_result": result.data,
                },
            )
        message = result.error.message if result.error is not None else "Calculation failed."
        if result.error is not None and result.error.hint:
            message = f"{message} Hint: {result.error.hint}"
        return AgentResponse(
            final_answer=message,
            selected_agent=self.name,
            plan=plan,
            metadata=metadata,
            artifacts={
                "workflow": "calculator",
                "tool_result": result.model_dump(mode="json"),
            },
        )

    @traceable(
        name="Calculator Agent Build Calculation Request",
        run_type="chain"
    )
    def _build_calculation_request(self, request: AgentRequest) -> CalculatorRequest:
        set_trace_name(f"{self.__class__.__name__}.build_calculation_request")
        set_trace_metadata(
            agent_name=self.name,
            agent_step="build_calculation_request",
            step_kind="action_request_extraction",
            workflow="calculator",
        )
        system_prompt = CALCULATOR_REQUEST_SYSTEM_PROMPT
        messages = []
        if request.history:
            messages.extend(request.history.to_llm_messages())
        messages.append(
            {
                "role": "user",
                "content": build_calculator_request_user_prompt(
                    user_request=request.user_message,
                    orchestrator_guidance=request.orchestrator_guidance,
                ),
            }
        )
        result = self.reasoner.genai.generate_structured(
            CalculatorRequest,
            system_prompt,
            messages,
            model=self.reasoner.genai.chat_model_for("default"),
            temperature=0.0,
        )
        return CalculatorRequest.model_validate(result)

    @traceable(
        name="Calculator Agent Execute Calculation Request",
        run_type="chain"
    )
    def _execute_calculation_request(self, request: CalculatorRequest) -> ToolResult:
        set_trace_name(f"{self.__class__.__name__}.execute_calculation_request")
        set_trace_metadata(
            agent_name=self.name,
            agent_step="execute_calculation_request",
            step_kind="tool_dispatch",
            workflow="calculator",
            operation=request.operation.value,
        )
        start = time.monotonic()
        runtime = CalculatorToolRuntime(service=self.calculator_service)
        tool_mapping = build_calculator_tool_mapping(runtime)
        operation = request.operation.value
        tool_name = f"calc_{operation}"
        log_event(
            LOGGER,
            "tool.dispatch.start",
            component="tool",
            agent_name=self.name,
            step="execute_calculation_request",
            tool_name=tool_name,
            status="started",
            operation=operation,
        )
        if operation == "evaluate_formula":
            result = tool_mapping["calc_evaluate_formula"](request.expression or "")
        elif operation == "sum":
            result = tool_mapping["calc_sum"](request.operands)
        elif operation == "subtract":
            result = tool_mapping["calc_subtract"](request.operands)
        elif operation == "multiply":
            result = tool_mapping["calc_multiply"](request.operands)
        elif operation == "divide":
            result = tool_mapping["calc_divide"](request.operands)
        elif operation == "quantity_from_budget_and_price":
            result = tool_mapping["calc_quantity_from_budget_and_price"](
                request.budget,
                request.price,
            )
        elif operation == "notional_from_quantity_and_price":
            result = tool_mapping["calc_notional_from_quantity_and_price"](
                request.quantity,
                request.price,
            )
        elif operation == "position_weight":
            result = tool_mapping["calc_position_weight"](
                request.position_value,
                request.portfolio_value,
            )
        elif operation == "rebalance_delta":
            result = tool_mapping["calc_rebalance_delta"](
                request.current_value,
                request.target_weight_pct,
                request.portfolio_value,
            )
        elif operation == "pnl_amount":
            result = tool_mapping["calc_pnl_amount"](
                request.entry_price,
                request.current_price,
                request.quantity,
                request.direction.value,
            )
        else:
            result = tool_mapping["calc_pnl_percent"](
                request.entry_price,
                request.current_price,
                request.direction.value,
            )
        log_event(
            LOGGER,
            "tool.dispatch.end" if result.status == "ok" else "tool.dispatch.error",
            "info" if result.status == "ok" else "warning",
            component="tool",
            agent_name=self.name,
            step="execute_calculation_request",
            tool_name=tool_name,
            status=result.status,
            duration_ms=int((time.monotonic() - start) * 1000),
            error_code=result.error.code if result.error else None,
            error_type=result.error.type if result.error else None,
        )
        return result

