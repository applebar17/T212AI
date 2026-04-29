"""Purpose-defined specialist agents."""

from __future__ import annotations

import re
from typing import Any

from t212ai.brokers.models import (
    BrokerOrderAction,
    BrokerOrderActionRequest,
)
from t212ai.brokers.tools import BrokerToolRuntime, build_broker_tool_mapping
from t212ai.calculator import (
    CALCULATOR_TOOLBOX,
    CalculatorRequest,
    CalculatorService,
    CalculatorToolRuntime,
    build_calculator_tool_mapping,
)
from t212ai.genai.tools.base import ToolBox
from t212ai.genai.models import ToolError, ToolResult
from t212ai.guidelines.service import GuidelineMemoryService
from t212ai.pending_actions import (
    PendingActionService,
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


def _empty_toolbox(name: str) -> ToolBox:
    return ToolBox(name=name, tools=[], tools_by_name={})


class PortfolioAnalystAgent(BaseAgent):
    def __init__(
        self,
        reasoner,
        guideline_service: GuidelineMemoryService | None = None,
        *,
        portfolio_summary_workflow: PortfolioSummaryWorkflow | None = None,
        toolbox_summary: str | None = None,
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
                    "Use the configured broker as account-authoritative state. For attention scans, "
                    "request fresh market/news context before making recommendations."
                ),
                toolbox_summary=toolbox_summary or (
                    "Portfolio snapshot, positions, pending orders, market data context, "
                    "active-movers intelligence, official disclosure activity, and web research when needed."
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
                    "I couldn't retrieve the broker portfolio summary. "
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
        broker_service=None,
        broker_read_service=None,
        broker_execution_service=None,
        broker_provider: str = "broker",
        pending_action_service: PendingActionService | None = None,
        proposal_service: ProposalService | None = None,
        toolbox: ToolBox | None = None,
        toolbox_summary: str | None = None,
    ) -> None:
        super().__init__(
            reasoner,
            AgentProfile(
                name="order_agent",
                purpose="Review, prepare, cancel, and reason about broker orders.",
                guidelines=(
                    "Treat order submission and cancellation as state-changing. "
                    "Require explicit confirmation before execution. Never retry "
                    "uncertain submissions without reconciliation."
                ),
                toolbox_summary=toolbox_summary or (
                    "Broker pending orders, order lookup, generic order preparation and "
                    "cancellation preparation tools, direct confirmed execution tools, plus "
                    "deterministic approval/execution through Telegram."
                ),
                task_complexity=TaskComplexity.CRITICAL,
                guideline_scopes=("global", "agent:order"),
                guideline_include_categories=("investment_preference",),
                toolbox=toolbox or _empty_toolbox("broker_execution"),
            ),
            guideline_service=guideline_service,
        )
        self.pending_orders_review_workflow = pending_orders_review_workflow
        resolved_read_service = broker_read_service or broker_service
        resolved_execution_service = broker_execution_service or broker_service
        resolved_provider = broker_provider
        if broker_service is not None and broker_provider == "broker":
            resolved_provider = getattr(broker_service, "provider_name", "broker")
        self.broker_read_service = resolved_read_service
        self.broker_execution_service = resolved_execution_service
        self.broker_provider = resolved_provider
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
                        "I couldn't review pending broker orders. "
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
        if (
            self.broker_execution_service is None
            or self.pending_action_service is None
        ):
            return None

        try:
            action_request = self._build_action_request(request, intent=intent)
        except Exception as exc:
            return AgentResponse(
                final_answer=(
                    "I couldn't translate the request into a deterministic broker action. "
                    f"Reason: {exc}"
                ),
                selected_agent=self.name,
                plan=plan,
                metadata={"workflow": "order_action", "workflow_status": "error"},
            )

        resolved_action_request = self._resolve_position_backed_submit_request(
            request,
            action_request=action_request,
            intent=intent,
        )
        if isinstance(resolved_action_request, ToolResult):
            return self._response_from_tool_result(
                plan=plan,
                action_request=action_request,
                result=resolved_action_request,
                proposal_id=None,
            )

        proposal = None
        if (
            resolved_action_request.action == BrokerOrderAction.PREPARE_SUBMIT_ORDER
            and self.proposal_service is not None
        ):
            try:
                proposal = self._create_submit_order_proposal(
                    request,
                    intent=intent,
                    action_request=resolved_action_request,
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

        result = self._execute_action_request(request, resolved_action_request)
        return self._response_from_tool_result(
            plan=plan,
            action_request=resolved_action_request,
            result=result,
            proposal_id=proposal.proposal_id if proposal is not None else None,
        )

    def _build_action_request(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent,
    ) -> BrokerOrderActionRequest:
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
                    orchestrator_guidance=request.orchestrator_guidance,
                ),
            }
        )
        result = self.reasoner.genai.generate_structured(
            BrokerOrderActionRequest,
            system_prompt,
            messages,
            model=self.reasoner.genai.chat_model_for("smart"),
            temperature=0.0,
        )
        return BrokerOrderActionRequest.model_validate(result)

    def _execute_action_request(
        self,
        request: AgentRequest,
        action_request: BrokerOrderActionRequest,
    ) -> ToolResult:
        runtime = BrokerToolRuntime(
            broker_read_service=self.broker_read_service,
            broker_execution_service=self.broker_execution_service,
            broker_provider=self.broker_provider,
            pending_action_service=self.pending_action_service,
            chat_id=request.chat_id,
            user_id=_metadata_user_id(request.metadata),
            user_message=request.user_message,
        )
        tool_mapping = build_broker_tool_mapping(runtime)
        if action_request.action == BrokerOrderAction.PREPARE_CANCEL_ORDER:
            return tool_mapping["broker_prepare_cancel_action"](
                order_ref=action_request.target_order_ref,
                selector=(
                    action_request.cancel_selector.value
                    if action_request.cancel_selector is not None
                    else None
                ),
                reason=action_request.reason,
            )
        return tool_mapping["broker_prepare_order_action"](
            order_type=action_request.order_type,
            side=action_request.side,
            ticker=action_request.ticker,
            quantity=action_request.quantity,
            limit_price=action_request.limit_price,
            stop_price=action_request.stop_price,
            time_in_force=action_request.time_in_force,
            extended_hours=action_request.extended_hours,
        )

    def _resolve_position_backed_submit_request(
        self,
        request: AgentRequest,
        *,
        action_request: BrokerOrderActionRequest,
        intent: AgentIntent,
    ) -> BrokerOrderActionRequest | ToolResult:
        if action_request.action != BrokerOrderAction.PREPARE_SUBMIT_ORDER:
            return action_request
        liquidation_requested = action_request.use_full_position_size or (
            str(intent.entities.get("action", "")).strip().lower() == "liquidate"
        )
        if not liquidation_requested:
            return action_request
        if self.broker_read_service is None:
            return _local_order_error(
                "I recognized this as a full-position liquidation request, but broker "
                "position data is unavailable so I can't resolve the live share quantity.",
                code="missing_broker_read_service",
                hint="Configure broker read access, then retry the liquidation request.",
            )
        try:
            snapshot = self.broker_read_service.get_portfolio_snapshot()
        except Exception as exc:
            return _local_order_error(
                "I recognized this as a full-position liquidation request, but I "
                f"couldn't load the current broker positions. Reason: {exc}",
                code="portfolio_snapshot_unavailable",
            )
        position = _match_position_for_liquidation(
            snapshot.positions,
            ticker_hint=action_request.ticker,
            user_message=request.user_message,
        )
        if position is None:
            return _local_order_error(
                "I recognized this as a full-position liquidation request, but I couldn't "
                "match the target holding in the live broker positions.",
                code="position_match_not_found",
                hint="Retry using the broker ticker symbol, for example GOOGL instead of Alphabet.",
            )
        available_quantity = position.quantity_available_for_trading or position.quantity
        if available_quantity is None or available_quantity <= 0:
            return _local_order_error(
                "I matched the target holding, but there is no positive quantity available to trade.",
                code="position_quantity_unavailable",
            )
        resolved_ticker = (
            str(position.instrument.ticker or "").strip()
            if position.instrument is not None
            else ""
        ) or str(action_request.ticker or "").strip()
        return action_request.model_copy(
            update={
                "side": "SELL",
                "ticker": resolved_ticker,
                "quantity": str(available_quantity),
                "use_full_position_size": True,
            }
        )

    def _create_submit_order_proposal(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent,
        action_request: BrokerOrderActionRequest,
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
        action_request: BrokerOrderActionRequest,
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
        message = (
            _render_tool_error_message(error)
            if error is not None
            else (result.output or "Order action failed.")
        )
        if error is not None:
            metadata["error_code"] = error.code or "tool_error"
        elif result.meta:
            metadata["error_code"] = str(result.meta.get("error_code") or "tool_error")
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
    def __init__(
        self,
        reasoner,
        guideline_service: GuidelineMemoryService | None = None,
        *,
        toolbox: ToolBox | None = None,
        toolbox_summary: str | None = None,
    ) -> None:
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
                toolbox_summary=toolbox_summary or (
                    "Market analyst toolbox: market snapshot and relative-volume monitoring; "
                    "active-movers intelligence; official disclosure activity; web search "
                    "and article scraping for expansion."
                ),
                task_complexity=TaskComplexity.COMPLEX,
                guideline_scopes=("global", "agent:market"),
                toolbox=toolbox or _empty_toolbox("market_analyst"),
            ),
            guideline_service=guideline_service,
        )


class CompanyAnalystAgent(BaseAgent):
    def __init__(
        self,
        reasoner,
        guideline_service: GuidelineMemoryService | None = None,
        *,
        toolbox_summary: str | None = None,
    ) -> None:
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
                    "claims and keep market-data providers as convenience context."
                ),
                toolbox_summary=toolbox_summary or (
                    "market-data context: symbol, quote, and chart-ready context; "
                    "research: search and article scraping; "
                    "specialist provider context when needed; market intelligence and fundamentals."
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


def _proposal_thesis(action_request: BrokerOrderActionRequest) -> str:
    thesis = str(action_request.thesis or "").strip()
    if thesis:
        return thesis
    return (
        f"User requested a {str(action_request.side or 'unknown').upper()} "
        f"{str(action_request.order_type or 'order').upper()} order for "
        f"{str(action_request.ticker or 'an instrument').upper()}."
    )


def _order_action_summary(action_request: BrokerOrderActionRequest) -> str:
    return (
        f"{str(action_request.side or 'BUY').upper()} "
        f"{str(action_request.ticker or 'UNKNOWN').upper()} "
        f"via {str(action_request.order_type or 'MARKET').upper()} order"
    )


def _order_intent_payload(action_request: BrokerOrderActionRequest) -> dict[str, Any]:
    return {
        "action": action_request.action.value,
        "order_type": action_request.order_type,
        "side": action_request.side,
        "ticker": action_request.ticker,
        "quantity": action_request.quantity,
        "limit_price": action_request.limit_price,
        "stop_price": action_request.stop_price,
        "time_in_force": action_request.time_in_force,
        "extended_hours": action_request.extended_hours,
        "use_full_position_size": action_request.use_full_position_size,
    }


def _local_order_error(
    message: str,
    *,
    code: str,
    hint: str | None = None,
) -> ToolResult:
    return ToolResult(
        status="error",
        error=ToolError(
            message=message,
            code=code,
            hint=hint,
            retryable=False,
        ),
    )


def _render_tool_error_message(error: ToolError) -> str:
    message = str(error.message or "Tool execution failed.").strip()
    if error.code:
        message = f"{message}\nCode: {error.code}"
    if error.hint:
        message = f"{message}\nHint: {error.hint}"
    details = _compact_tool_error_details(error.details)
    if details:
        message = f"{message}\nDetails: {details}"
    return message


def _compact_tool_error_details(details: dict[str, Any] | None) -> str | None:
    if not details:
        return None
    parts: list[str] = []
    for key in ("operation", "provider", "status_code", "error_type", "error", "expected_fingerprint"):
        value = details.get(key)
        if value is None:
            continue
        raw = str(value).strip()
        if raw:
            parts.append(f"{key}={raw}")
    return "; ".join(parts) if parts else None


def _match_position_for_liquidation(
    positions: list[Any],
    *,
    ticker_hint: str | None,
    user_message: str,
):
    hint = _normalize_position_text(ticker_hint)
    message = _normalize_position_text(user_message)
    candidates: list[tuple[int, Any]] = []
    for position in positions:
        best_score = 0
        for name in _position_match_texts(position):
            normalized = _normalize_position_text(name)
            if not normalized:
                continue
            if hint and (hint == normalized or hint in normalized or normalized in hint):
                best_score = max(best_score, 4)
            if normalized and re.search(rf"\b{re.escape(normalized)}\b", message):
                best_score = max(best_score, 3)
            if _has_meaningful_token_overlap(normalized, message):
                best_score = max(best_score, 2)
            if hint and any(token == normalized for token in hint.split()):
                best_score = max(best_score, 2)
        if best_score > 0:
            candidates.append((best_score, position))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _position_match_texts(position: Any) -> list[str]:
    instrument = getattr(position, "instrument", None)
    values = [
        getattr(position, "ticker", None),
        getattr(instrument, "ticker", None) if instrument is not None else None,
        getattr(instrument, "name", None) if instrument is not None else None,
    ]
    return [str(value).strip() for value in values if str(value or "").strip()]


def _normalize_position_text(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", raw).strip()


def _has_meaningful_token_overlap(candidate: str, message: str) -> bool:
    candidate_tokens = {token for token in candidate.split() if len(token) >= 3}
    message_tokens = {token for token in message.split() if len(token) >= 3}
    return bool(candidate_tokens & message_tokens)


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
