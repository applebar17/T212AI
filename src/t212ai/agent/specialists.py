"""Purpose-defined specialist agents."""

from __future__ import annotations

from typing import Any

from t212ai.brokers.trading212 import (
    T212_ORDER_ACTION_TOOLBOX,
    Trading212BrokerService,
    Trading212ToolRuntime,
    build_trading212_tool_mapping,
)
from t212ai.calculator import (
    CALCULATOR_TOOLBOX,
    CalculatorRequest,
    CalculatorService,
    CalculatorToolRuntime,
    build_calculator_tool_mapping,
)
from t212ai.genai.models import ToolResult
from t212ai.genai.tools import MARKET_ANALYST_TOOLBOX
from t212ai.guidelines.service import GuidelineMemoryService
from t212ai.pending_actions import (
    PendingActionService,
    Trading212OrderAction,
    Trading212OrderActionRequest,
)
from t212ai.proposals import ProposalService
from t212ai.workflows import (
    PendingOrdersReviewWorkflow,
    PortfolioSummaryWorkflow,
    WorkflowExecutionError,
)

from .base import AgentProfile, BaseAgent
from .intents import AgentIntent, IntentKind
from .planner import TaskComplexity
from .prompts import (
    CALCULATOR_REQUEST_SYSTEM_PROMPT,
    ORDER_ACTION_REQUEST_SYSTEM_PROMPT,
    build_calculator_request_user_prompt,
    build_order_action_user_prompt,
)
from .schemas import AgentRequest, AgentResponse


class PortfolioAnalystAgent(BaseAgent):
    def __init__(
        self,
        reasoner,
        guideline_service: GuidelineMemoryService | None = None,
        *,
        portfolio_summary_workflow: PortfolioSummaryWorkflow | None = None,
    ) -> None:
        super().__init__(
            reasoner,
            AgentProfile(
                name="portfolio_analyst",
                purpose=(
                    "Analyze broker portfolio state, exposure, concentration, "
                    "and attention items."
                ),
                guidelines=(
                    "Use Trading 212 as broker-authoritative state. For attention scans, "
                    "request fresh market/news context before making recommendations."
                ),
                toolbox_summary=(
                    "Portfolio snapshot, positions, pending orders, Yahoo market context, "
                    "Alpha Vantage intelligence, web search when needed."
                ),
                task_complexity=TaskComplexity.COMPLEX,
                guideline_scopes=("global", "agent:portfolio"),
                guideline_include_categories=("investment_preference",),
            ),
            guideline_service=guideline_service,
        )
        self.portfolio_summary_workflow = portfolio_summary_workflow

    def resolve_complexity(self, message: str) -> TaskComplexity:
        text = message.lower()
        if any(word in text for word in ("attention", "risk", "rebalance", "exposure")):
            return TaskComplexity.COMPLEX
        return TaskComplexity.EASY

    def execute(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent,
        task_complexity: TaskComplexity,
        plan,
    ) -> AgentResponse | None:
        del request, task_complexity
        if (
            intent.kind != IntentKind.PORTFOLIO_SUMMARY
            or self.portfolio_summary_workflow is None
        ):
            return None

        try:
            summary = self.portfolio_summary_workflow.run()
        except WorkflowExecutionError as exc:
            return AgentResponse(
                final_answer=(
                    "I couldn't retrieve the Trading 212 portfolio summary. "
                    f"Reason: {exc}. Hint: {exc.hint}"
                ),
                selected_agent=self.name,
                plan=plan,
                metadata={
                    "workflow": "portfolio_summary",
                    "workflow_status": "error",
                    "error_code": exc.code,
                },
                artifacts={"workflow_error": exc.to_dict()},
            )

        return AgentResponse(
            final_answer=summary.render_text(),
            selected_agent=self.name,
            plan=plan,
            metadata={
                "workflow": "portfolio_summary",
                "workflow_status": "ok",
                "position_count": str(summary.position_count),
                "pending_order_count": str(summary.pending_order_count),
            },
            artifacts={
                "workflow": "portfolio_summary",
                "portfolio_summary": summary.model_dump(mode="json"),
            },
        )


class OrderAgent(BaseAgent):
    def __init__(
        self,
        reasoner,
        guideline_service: GuidelineMemoryService | None = None,
        *,
        pending_orders_review_workflow: PendingOrdersReviewWorkflow | None = None,
        broker_service: Trading212BrokerService | None = None,
        pending_action_service: PendingActionService | None = None,
        proposal_service: ProposalService | None = None,
    ) -> None:
        super().__init__(
            reasoner,
            AgentProfile(
                name="order_agent",
                purpose="Review, prepare, cancel, and reason about Trading 212 orders.",
                guidelines=(
                    "Treat order submission and cancellation as state-changing. "
                    "Require explicit confirmation before execution. Never retry "
                    "uncertain submissions without reconciliation."
                ),
                toolbox_summary=(
                    "Trading 212 pending orders, order lookup, higher-level prepare "
                    "order-action and prepare-cancel-action tools, plus deterministic "
                    "approval/execution through Telegram."
                ),
                task_complexity=TaskComplexity.CRITICAL,
                guideline_scopes=("global", "agent:order"),
                guideline_include_categories=("investment_preference",),
                toolbox=T212_ORDER_ACTION_TOOLBOX,
            ),
            guideline_service=guideline_service,
        )
        self.pending_orders_review_workflow = pending_orders_review_workflow
        self.broker_service = broker_service
        self.pending_action_service = pending_action_service
        self.proposal_service = proposal_service

    def resolve_complexity(self, message: str) -> TaskComplexity:
        del message
        return TaskComplexity.CRITICAL

    def execute(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent,
        task_complexity: TaskComplexity,
        plan,
    ) -> AgentResponse | None:
        del task_complexity
        if intent.kind == IntentKind.REVIEW_PENDING_ORDERS:
            if self.pending_orders_review_workflow is None:
                return None
            try:
                review = self.pending_orders_review_workflow.run()
            except WorkflowExecutionError as exc:
                return AgentResponse(
                    final_answer=(
                        "I couldn't review pending Trading 212 orders. "
                        f"Reason: {exc}. Hint: {exc.hint}"
                    ),
                    selected_agent=self.name,
                    plan=plan,
                    metadata={
                        "workflow": "pending_orders_review",
                        "workflow_status": "error",
                        "error_code": exc.code,
                    },
                    artifacts={"workflow_error": exc.to_dict()},
                )

            return AgentResponse(
                final_answer=review.render_text(),
                selected_agent=self.name,
                plan=plan,
                metadata={
                    "workflow": "pending_orders_review",
                    "workflow_status": "ok",
                    "order_count": str(review.order_count),
                    "attention_order_count": str(review.attention_order_count),
                },
                artifacts={
                    "workflow": "pending_orders_review",
                    "pending_orders_review": review.model_dump(mode="json"),
                },
            )

        if intent.kind not in {
            IntentKind.PROPOSE_TRADE,
            IntentKind.PLACE_ORDER,
            IntentKind.CANCEL_ORDER,
        }:
            return None
        if self.broker_service is None or self.pending_action_service is None:
            return None

        try:
            action_request = self._build_action_request(request, intent=intent)
        except Exception as exc:
            return AgentResponse(
                final_answer=(
                    "I couldn't translate the request into a deterministic Trading 212 action. "
                    f"Reason: {exc}"
                ),
                selected_agent=self.name,
                plan=plan,
                metadata={"workflow": "order_action", "workflow_status": "error"},
            )

        proposal = None
        if (
            action_request.action == Trading212OrderAction.PREPARE_SUBMIT_ORDER
            and self.proposal_service is not None
        ):
            try:
                proposal = self._create_submit_order_proposal(
                    request,
                    intent=intent,
                    action_request=action_request,
                )
            except Exception as exc:
                return AgentResponse(
                    final_answer=(
                        "I couldn't create the internal proposal record required for "
                        f"this submit-order request. Reason: {exc}"
                    ),
                    selected_agent=self.name,
                    plan=plan,
                    metadata={
                        "workflow": "order_action",
                        "workflow_status": "error",
                        "error_code": "proposal_creation_failed",
                    },
                )

        result = self._execute_action_request(request, action_request)
        return self._response_from_tool_result(
            plan=plan,
            action_request=action_request,
            result=result,
            proposal_id=proposal.proposal_id if proposal is not None else None,
        )

    def _build_action_request(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent,
    ) -> Trading212OrderActionRequest:
        system_prompt = ORDER_ACTION_REQUEST_SYSTEM_PROMPT
        messages = []
        if request.history:
            messages.extend(request.history.to_llm_messages())
        messages.append(
            {
                "role": "user",
                "content": build_order_action_user_prompt(
                    intent_kind=intent.kind.value,
                    user_request=request.user_message,
                ),
            }
        )
        result = self.reasoner.genai.generate_structured(
            Trading212OrderActionRequest,
            system_prompt,
            messages,
            model=self.reasoner.genai.chat_model_for("smart"),
            temperature=0.0,
        )
        return Trading212OrderActionRequest.model_validate(result)

    def _execute_action_request(
        self,
        request: AgentRequest,
        action_request: Trading212OrderActionRequest,
    ) -> ToolResult:
        runtime = Trading212ToolRuntime(
            service=self.broker_service,
            pending_action_service=self.pending_action_service,
            chat_id=request.chat_id,
            user_id=_metadata_user_id(request.metadata),
            user_message=request.user_message,
        )
        tool_mapping = build_trading212_tool_mapping(runtime)
        if action_request.action == Trading212OrderAction.PREPARE_CANCEL_ORDER:
            return tool_mapping["t212_prepare_cancel_action"](
                order_id=action_request.target_order_id,
                selector=(
                    action_request.cancel_selector.value
                    if action_request.cancel_selector is not None
                    else None
                ),
                reason=action_request.reason,
            )
        return tool_mapping["t212_prepare_order_action"](
            order_type=action_request.order_type,
            side=action_request.side,
            ticker=action_request.ticker,
            quantity=action_request.quantity,
            limit_price=action_request.limit_price,
            stop_price=action_request.stop_price,
            time_validity=action_request.time_validity,
            extended_hours=action_request.extended_hours,
        )

    def _create_submit_order_proposal(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent,
        action_request: Trading212OrderActionRequest,
    ):
        if self.proposal_service is None:
            return None
        return self.proposal_service.create_submit_order_proposal(
            chat_id=request.chat_id or "",
            user_id=_metadata_user_id(request.metadata),
            intent_kind=intent.kind.value,
            original_user_message=request.user_message,
            action_summary=_order_action_summary(action_request),
            order_intent=_order_intent_payload(action_request),
            thesis=_proposal_thesis(action_request),
            risks=[str(item).strip() for item in action_request.risks if str(item).strip()],
            confidence=action_request.confidence,
        )

    def _response_from_tool_result(
        self,
        *,
        plan,
        action_request: Trading212OrderActionRequest,
        result: ToolResult,
        proposal_id: str | None,
    ) -> AgentResponse:
        metadata = {
            "workflow": "order_action",
            "workflow_status": result.status,
            "action": action_request.action.value,
        }
        if result.status == "ok":
            artifacts: dict[str, Any] = {"workflow": "order_action"}
            approval = None
            pending_action_id = None
            if isinstance(result.data, dict):
                approval = result.data.get("telegramApproval")
                artifacts["order_action"] = result.data
                pending_action = result.data.get("pendingAction")
                if isinstance(pending_action, dict):
                    pending_action_id = str(pending_action.get("action_id") or pending_action.get("actionId") or "")
            if proposal_id and self.proposal_service is not None:
                if not pending_action_id:
                    self.proposal_service.mark_preparation_failed(
                        proposal_id,
                        error="Order action succeeded without a pending action identifier.",
                    )
                else:
                    self.proposal_service.attach_pending_action(
                        proposal_id,
                        pending_action_id=pending_action_id,
                    )
            if approval:
                if proposal_id:
                    approval = _approval_with_proposal_reference(approval, proposal_id=proposal_id)
                artifacts["telegram_approval_request"] = approval
            if proposal_id:
                metadata["proposal_id"] = proposal_id
                artifacts["proposal_id"] = proposal_id
            return AgentResponse(
                final_answer=(
                    str(approval.get("text"))
                    if isinstance(approval, dict) and approval.get("text")
                    else result.output or "Prepared action awaiting approval."
                ),
                selected_agent=self.name,
                plan=plan,
                metadata=metadata,
                artifacts=artifacts,
            )

        error = result.error
        message = error.message if error is not None else "Order action failed."
        if error is not None and error.hint:
            message = f"{message} Hint: {error.hint}"
            metadata["error_code"] = error.code or "tool_error"
        if proposal_id and self.proposal_service is not None:
            self.proposal_service.mark_preparation_failed(proposal_id, error=message)
            metadata["proposal_id"] = proposal_id
        return AgentResponse(
            final_answer=message,
            selected_agent=self.name,
            plan=plan,
            metadata=metadata,
            artifacts={"workflow": "order_action", "tool_result": result.model_dump(mode="json")},
        )


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
                    "Never do arithmetic freehand. Always route calculation requests to "
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

    def execute(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent,
        task_complexity: TaskComplexity,
        plan,
    ) -> AgentResponse | None:
        del task_complexity
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

    def _build_calculation_request(self, request: AgentRequest) -> CalculatorRequest:
        system_prompt = CALCULATOR_REQUEST_SYSTEM_PROMPT
        messages = []
        if request.history:
            messages.extend(request.history.to_llm_messages())
        messages.append(
            {
                "role": "user",
                "content": build_calculator_request_user_prompt(
                    user_request=request.user_message,
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

    def _execute_calculation_request(self, request: CalculatorRequest) -> ToolResult:
        runtime = CalculatorToolRuntime(service=self.calculator_service)
        tool_mapping = build_calculator_tool_mapping(runtime)
        operation = request.operation.value
        if operation == "evaluate_formula":
            return tool_mapping["calc_evaluate_formula"](request.expression or "")
        if operation == "sum":
            return tool_mapping["calc_sum"](request.operands)
        if operation == "subtract":
            return tool_mapping["calc_subtract"](request.operands)
        if operation == "multiply":
            return tool_mapping["calc_multiply"](request.operands)
        if operation == "divide":
            return tool_mapping["calc_divide"](request.operands)
        if operation == "quantity_from_budget_and_price":
            return tool_mapping["calc_quantity_from_budget_and_price"](
                request.budget,
                request.price,
            )
        if operation == "notional_from_quantity_and_price":
            return tool_mapping["calc_notional_from_quantity_and_price"](
                request.quantity,
                request.price,
            )
        if operation == "position_weight":
            return tool_mapping["calc_position_weight"](
                request.position_value,
                request.portfolio_value,
            )
        if operation == "rebalance_delta":
            return tool_mapping["calc_rebalance_delta"](
                request.current_value,
                request.target_weight_pct,
                request.portfolio_value,
            )
        if operation == "pnl_amount":
            return tool_mapping["calc_pnl_amount"](
                request.entry_price,
                request.current_price,
                request.quantity,
                request.direction.value,
            )
        return tool_mapping["calc_pnl_percent"](
            request.entry_price,
            request.current_price,
            request.direction.value,
        )


class MarketAnalystAgent(BaseAgent):
    def __init__(self, reasoner, guideline_service: GuidelineMemoryService | None = None) -> None:
        super().__init__(
            reasoner,
            AgentProfile(
                name="market_analyst",
                purpose=(
                    "Analyze broad market context, movers, commodities, "
                    "and macro-adjacent signals."
                ),
                guidelines=(
                    "Use market data as context, not broker state. Distinguish latest "
                    "price context from slower research enrichment."
                ),
                toolbox_summary=(
                    "Market analyst toolbox: Yahoo market snapshot and relative-volume monitoring; "
                    "Alpha Vantage most-actively-traded context; SEC EDGAR insider, stake, and "
                    "official disclosure snapshots; web search and article scraping for expansion."
                ),
                task_complexity=TaskComplexity.COMPLEX,
                guideline_scopes=("global", "agent:market"),
                toolbox=MARKET_ANALYST_TOOLBOX,
            ),
            guideline_service=guideline_service,
        )


class CompanyAnalystAgent(BaseAgent):
    def __init__(self, reasoner, guideline_service: GuidelineMemoryService | None = None) -> None:
        super().__init__(
            reasoner,
            AgentProfile(
                name="company_analyst",
                purpose=(
                    "Analyze a company, ETF, or ticker using market, fundamental, "
                    "and research context."
                ),
                guidelines=(
                    "Resolve ticker ambiguity first. Use multiple sources for thesis-level "
                    "claims and keep Yahoo as convenience context."
                ),
                toolbox_summary=(
                    "yahoo_market_context: symbol/quote/options/analyst context; "
                    "research: search and article scraping; "
                    "Alpha Vantage intelligence and fundamentals."
                ),
                task_complexity=TaskComplexity.COMPLEX,
                guideline_scopes=("global", "agent:company"),
                guideline_include_categories=("investment_preference",),
            ),
            guideline_service=guideline_service,
        )


def _metadata_user_id(metadata: dict[str, str]) -> int | None:
    raw = str(metadata.get("telegram_user_id", "")).strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _proposal_thesis(action_request: Trading212OrderActionRequest) -> str:
    thesis = str(action_request.thesis or "").strip()
    if thesis:
        return thesis
    return (
        f"User requested a {str(action_request.side or 'unknown').upper()} "
        f"{str(action_request.order_type or 'order').upper()} order for "
        f"{str(action_request.ticker or 'an instrument').upper()}."
    )


def _order_action_summary(action_request: Trading212OrderActionRequest) -> str:
    return (
        f"{str(action_request.side or 'BUY').upper()} "
        f"{str(action_request.ticker or 'UNKNOWN').upper()} "
        f"via {str(action_request.order_type or 'MARKET').upper()} order"
    )


def _order_intent_payload(action_request: Trading212OrderActionRequest) -> dict[str, Any]:
    return {
        "action": action_request.action.value,
        "order_type": action_request.order_type,
        "side": action_request.side,
        "ticker": action_request.ticker,
        "quantity": action_request.quantity,
        "limit_price": action_request.limit_price,
        "stop_price": action_request.stop_price,
        "time_validity": action_request.time_validity,
        "extended_hours": action_request.extended_hours,
    }


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
