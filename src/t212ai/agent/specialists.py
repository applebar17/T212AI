"""Purpose-defined specialist agents."""

from __future__ import annotations

import re
from typing import Any

from t212ai.brokers.models import (
    BrokerOrderAction,
    BrokerOrderActionRequest,
)
from t212ai.brokers.references import BrokerReferenceMap
from t212ai.brokers.tools import BrokerToolRuntime, build_broker_tool_mapping
from t212ai.calculator import (
    CALCULATOR_TOOLBOX,
    CalculatorRequest,
    CalculatorService,
    CalculatorToolRuntime,
    build_calculator_tool_mapping,
)
from t212ai.genai.models import ToolError, ToolResult
from t212ai.genai.tools import build_tool_mapping_for
from t212ai.genai.tools.base import ToolBox, render_tool_descriptions
from t212ai.genai.tracing import (
    _trace_agent_action_inputs,
    _trace_agent_action_outputs,
    _trace_agent_execute_inputs,
    _trace_agent_handle_inputs,
    _trace_agent_response_outputs,
    set_trace_metadata,
    set_trace_name,
    traceable,
)
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
from .configurable import ConfigurablePlannerAgent, ConfigurableReasonerAgent
from .execution import GroupedPlanExecutor
from .intents import AgentIntent, IntentKind
from .planner import TaskComplexity
from .prompts import (
    CALCULATOR_REQUEST_SYSTEM_PROMPT,
    ORDER_ACTION_REQUEST_SYSTEM_PROMPT,
    build_calculator_request_user_prompt,
    build_order_action_user_prompt,
)
from .schemas import AgentInvocationContext, AgentRequest, AgentResponse


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

    @traceable(
        name="Portfolio Analyst Execute",
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
        del request
        set_trace_name(f"{self.__class__.__name__}.execute")
        set_trace_metadata(
            agent_name=self.name,
            agent_step="execute",
            step_kind="execute",
            intent_kind=intent.kind.value,
            task_complexity=task_complexity.value,
            workflow="portfolio_summary",
        )
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
        market_data_service=None,
        broker_provider: str = "broker",
        pending_action_service: PendingActionService | None = None,
        proposal_service: ProposalService | None = None,
        toolbox: ToolBox | None = None,
        toolbox_summary: str | None = None,
        configurable_reasoner_agent: ConfigurableReasonerAgent | None = None,
        configurable_planner_agent: ConfigurablePlannerAgent | None = None,
        grouped_plan_executor: GroupedPlanExecutor | None = None,
    ) -> None:
        super().__init__(
            reasoner,
            AgentProfile(
                name="order_agent",
                purpose="Review, prepare, cancel, and reason about broker orders.",
                guidelines=(
                    "Treat order submission and cancellation as state-changing. "
                    "Require explicit Telegram button approval before execution. "
                    "Typed chat messages are conversation, not approval or rejection. "
                    "Retry uncertain submissions only after reconciliation. "
                    "When summarizing broker read outputs for later plan actions, preserve "
                    "exact numeric cash, quantity, price, and order-reference values."
                ),
                toolbox_summary=toolbox_summary or (
                    "Broker pending orders, order lookup, generic order preparation and "
                    "cancellation preparation tools, direct confirmed execution tools, plus "
                    "deterministic approval/execution through Telegram."
                ),
                task_complexity=TaskComplexity.CRITICAL,
                guideline_scopes=("global", "agent:order"),
                guideline_include_categories=("investment_preference",),
                toolbox=toolbox or _empty_toolbox("broker_order_actions"),
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
        self.market_data_service = market_data_service
        self.broker_provider = resolved_provider
        self.pending_action_service = pending_action_service
        self.proposal_service = proposal_service
        self.configurable_reasoner_agent = configurable_reasoner_agent
        self.configurable_planner_agent = configurable_planner_agent
        self.grouped_plan_executor = grouped_plan_executor

    def resolve_complexity(self, message: str) -> TaskComplexity:
        del message
        return TaskComplexity.CRITICAL

    @traceable(
        name="Order Agent Handle",
        run_type="chain"
    )
    def handle(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent | None = None,
        task_complexity: TaskComplexity | None = None,
    ) -> AgentResponse:
        resolved_intent = intent or AgentIntent(kind=IntentKind.UNKNOWN)
        if (
            resolved_intent.kind
            in {IntentKind.PROPOSE_TRADE, IntentKind.PLACE_ORDER, IntentKind.CANCEL_ORDER}
            and self._can_use_configurable_loop()
        ):
            complexity = task_complexity or self.resolve_complexity(request.user_message)
            set_trace_name(f"{self.__class__.__name__}.handle")
            set_trace_metadata(
                agent_name=self.name,
                agent_kind="specialist",
                intent_kind=resolved_intent.kind.value,
                task_complexity=complexity.value,
                workflow="order_action",
                execution_mode="grouped_plan",
            )
            try:
                return self._handle_configurable_order_action(
                    request,
                    intent=resolved_intent,
                    task_complexity=complexity,
                )
            except Exception as exc:  # pragma: no cover - live LLM/provider safety net
                return AgentResponse(
                    final_answer=(
                        "I couldn't complete the configurable broker-order loop. "
                        f"Reason: {exc.__class__.__name__}: {exc}"
                    ),
                    selected_agent=self.name,
                    metadata={
                        "workflow": "order_action",
                        "workflow_status": "error",
                        "execution_mode": "grouped_plan",
                        "error_type": exc.__class__.__name__,
                    },
                    artifacts={
                        "workflow": "order_action",
                        "order_action": {
                            "status": "error",
                            "error": str(exc),
                            "error_type": exc.__class__.__name__,
                        },
                    },
                )
        return super().handle(
            request,
            intent=resolved_intent,
            task_complexity=task_complexity,
        )

    @traceable(
        name="Order Agent Configurable Order Action",
        run_type="chain"
    )
    def _handle_configurable_order_action(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent,
        task_complexity: TaskComplexity,
    ) -> AgentResponse:
        set_trace_name(f"{self.__class__.__name__}.configurable_order_action")
        set_trace_metadata(
            agent_name=self.name,
            agent_step="configurable_order_action",
            step_kind="agentic_flow",
            intent_kind=intent.kind.value,
            task_complexity=task_complexity.value,
            workflow="order_action",
            execution_mode="grouped_plan",
        )
        invocation = AgentInvocationContext(
            user_request=request.user_message,
            chat_history=self._history_for_prompt(request.history),
            invocation_reason=(
                request.orchestrator_guidance
                or "Order agent handling the current broker order request."
            ),
            intent=intent,
            persistent_guidance=self._persistent_guidance(),
            agent_name=self.profile.name,
            purpose=self.profile.purpose,
            guidelines=self.profile.guidelines,
            toolbox_summary=self.profile.toolbox_summary,
            tool_descriptions=render_tool_descriptions(self.profile.toolbox),
            reasoning_guidelines=_broker_order_reasoning_guidelines(),
            planning_guidelines=_broker_order_planning_guidelines(),
            reasoning_examples=_broker_order_reasoning_examples(),
            planning_examples=_broker_order_planning_examples(),
            task_complexity=task_complexity,
        )
        assert self.configurable_reasoner_agent is not None
        assert self.configurable_planner_agent is not None
        assert self.grouped_plan_executor is not None
        assert self.profile.toolbox is not None

        reasoning_context = self.configurable_reasoner_agent.reason(invocation)
        if not reasoning_context.can_proceed and reasoning_context.clarifying_questions:
            return AgentResponse(
                final_answer="I need one clarification: "
                + " ".join(reasoning_context.clarifying_questions),
                selected_agent=self.name,
                metadata={
                    "workflow": "order_action",
                    "workflow_status": "needs_clarification",
                    "execution_mode": "grouped_plan",
                },
                artifacts={
                    "workflow": "order_action",
                    "order_action": {
                        "reasoning_context": reasoning_context.model_dump(mode="json"),
                    },
                },
            )

        grouped_plan = self.configurable_planner_agent.plan(
            invocation,
            reasoning_context=reasoning_context,
        )
        runtime = BrokerToolRuntime(
            broker_read_service=self.broker_read_service,
            broker_execution_service=self.broker_execution_service,
            broker_provider=self.broker_provider,
            pending_action_service=self.pending_action_service,
            market_data_service=self.market_data_service,
            chat_id=request.chat_id,
            user_id=_metadata_user_id(request.metadata),
            user_message=request.user_message,
            reference_map=BrokerReferenceMap(),
        )
        execution_result = self.grouped_plan_executor.execute(
            invocation=invocation,
            reasoning_context=reasoning_context,
            grouped_plan=grouped_plan,
            toolbox=self.profile.toolbox,
            tools_mapping=build_broker_tool_mapping(runtime),
        )
        compatible_plan = grouped_plan.to_agent_plan()
        artifacts: dict[str, Any] = {
            "workflow": "order_action",
            "order_action": {
                "reasoning_context": reasoning_context.model_dump(mode="json"),
                "grouped_plan": grouped_plan.model_dump(mode="json"),
                "execution": execution_result.model_dump(mode="json"),
                "final_synthesis": execution_result.final_answer,
            },
        }
        approval_payload = _approval_payload_from_grouped_execution(execution_result)
        if approval_payload is not None:
            artifacts["telegram_approval_request"] = approval_payload
        return AgentResponse(
            final_answer=execution_result.final_answer,
            selected_agent=self.name,
            plan=compatible_plan,
            metadata={
                "workflow": "order_action",
                "workflow_status": execution_result.status,
                "execution_mode": "grouped_plan",
                "group_count": str(len(grouped_plan.action_groups)),
                "action_count": str(execution_result.action_count),
            },
            artifacts=artifacts,
        )

    def _can_use_configurable_loop(self) -> bool:
        return (
            self.configurable_reasoner_agent is not None
            and self.configurable_planner_agent is not None
            and self.grouped_plan_executor is not None
            and self.profile.toolbox is not None
            and bool(self.profile.toolbox.tools)
        )

    @traceable(
        name="Order Agent Execute",
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
            workflow="order_action",
            execution_mode="direct_action",
        )
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

    @traceable(
        name="Order Agent Build Action Request",
        run_type="chain"
    )
    def _build_action_request(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent,
    ) -> BrokerOrderActionRequest:
        set_trace_name(f"{self.__class__.__name__}.build_action_request")
        set_trace_metadata(
            agent_name=self.name,
            agent_step="build_action_request",
            step_kind="action_request_extraction",
            intent_kind=intent.kind.value,
            workflow="order_action",
        )
        system_prompt = ORDER_ACTION_REQUEST_SYSTEM_PROMPT
        messages = []
        if request.history:
            messages.extend(request.history.to_llm_messages())
        broker_context = self._broker_state_context_for_order_request()
        if broker_context:
            messages.append({"role": "assistant", "content": broker_context})
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

    def _broker_state_context_for_order_request(self) -> str | None:
        if self.broker_read_service is None:
            return None
        try:
            snapshot = self.broker_read_service.get_portfolio_snapshot()
        except Exception as exc:
            return (
                "Broker state context could not be loaded before order reasoning. "
                f"Broker cash, holdings, and available quantities are unavailable. Error: {exc}"
            )
        return _broker_snapshot_order_context(snapshot)

    @traceable(
        name="Order Agent Execute Action Request",
        run_type="chain"
    )
    def _execute_action_request(
        self,
        request: AgentRequest,
        action_request: BrokerOrderActionRequest,
    ) -> ToolResult:
        set_trace_name(f"{self.__class__.__name__}.execute_action_request")
        set_trace_metadata(
            agent_name=self.name,
            agent_step="execute_action_request",
            step_kind="tool_dispatch",
            workflow="order_action",
            action=action_request.action.value,
        )
        runtime = BrokerToolRuntime(
            broker_read_service=self.broker_read_service,
            broker_execution_service=self.broker_execution_service,
            broker_provider=self.broker_provider,
            pending_action_service=self.pending_action_service,
            market_data_service=self.market_data_service,
            chat_id=request.chat_id,
            user_id=_metadata_user_id(request.metadata),
            user_message=request.user_message,
            reference_map=BrokerReferenceMap(),
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
            notional_amount=action_request.notional_amount,
            notional_currency=action_request.notional_currency,
            limit_price=action_request.limit_price,
            stop_price=action_request.stop_price,
            time_in_force=action_request.time_in_force,
            extended_hours=action_request.extended_hours,
        )

    @traceable(
        name="Order Agent Resolve Position Backed Submit Request",
        run_type="chain"
    )
    def _resolve_position_backed_submit_request(
        self,
        request: AgentRequest,
        *,
        action_request: BrokerOrderActionRequest,
        intent: AgentIntent,
    ) -> BrokerOrderActionRequest | ToolResult:
        set_trace_name(f"{self.__class__.__name__}.resolve_position_backed_submit_request")
        set_trace_metadata(
            agent_name=self.name,
            agent_step="resolve_position_backed_submit_request",
            step_kind="broker_state_resolution",
            workflow="order_action",
            action=action_request.action.value,
            intent_kind=intent.kind.value,
        )
        if action_request.action != BrokerOrderAction.PREPARE_SUBMIT_ORDER:
            return action_request
        side = str(action_request.side or "").strip().upper()
        liquidation_intent = str(intent.entities.get("action", "")).strip().lower() == "liquidate"
        full_position_requested = action_request.use_full_position_size or (
            liquidation_intent
            and action_request.quantity in {None, ""}
            and action_request.notional_amount in {None, ""}
        )
        position_lookup_requested = full_position_requested or side == "SELL"
        if not position_lookup_requested:
            return action_request
        if self.broker_read_service is None:
            return _local_order_error(
                "I recognized this as a sell/liquidation request, but broker "
                "position data is unavailable so I can't resolve the live holding details.",
                code="missing_broker_read_service",
                hint="Configure broker read access, then retry the sell/liquidation request.",
            )
        try:
            snapshot = self.broker_read_service.get_portfolio_snapshot()
        except Exception as exc:
            return _local_order_error(
                "I recognized this as a sell/liquidation request, but I "
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
                "I recognized this as a sell/liquidation request, but I couldn't "
                "match the target holding in the live broker positions.",
                code="position_match_not_found",
                hint="Retry using the broker ticker symbol, for example GOOGL instead of Alphabet.",
            )
        resolved_ticker = (
            str(position.instrument.ticker or "").strip()
            if position.instrument is not None
            else ""
        ) or str(action_request.ticker or "").strip()
        updates: dict[str, Any] = {
            "side": "SELL" if side == "SELL" or liquidation_intent else action_request.side,
            "ticker": resolved_ticker,
        }
        if full_position_requested:
            available_quantity = position.quantity_available_for_trading or position.quantity
            if available_quantity is None or available_quantity <= 0:
                return _local_order_error(
                    "I matched the target holding, but there is no positive quantity available to trade.",
                    code="position_quantity_unavailable",
                )
            updates["quantity"] = str(available_quantity)
            updates["use_full_position_size"] = True
        return action_request.model_copy(update=updates)

    @traceable(
        name="Order Agent Create Submit Order Proposal",
        run_type="chain"
    )
    def _create_submit_order_proposal(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent,
        action_request: BrokerOrderActionRequest,
    ):
        set_trace_name(f"{self.__class__.__name__}.create_submit_order_proposal")
        set_trace_metadata(
            agent_name=self.name,
            agent_step="create_submit_order_proposal",
            step_kind="proposal_persistence",
            workflow="order_action",
            action=action_request.action.value,
            intent_kind=intent.kind.value,
        )
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

    @traceable(
        name="Order Agent Response From Tool Result",
        run_type="chain"
    )
    def _response_from_tool_result(
        self,
        *,
        plan,
        action_request: BrokerOrderActionRequest,
        result: ToolResult,
        proposal_id: str | None,
    ) -> AgentResponse:
        set_trace_name(f"{self.__class__.__name__}.response_from_tool_result")
        set_trace_metadata(
            agent_name=self.name,
            agent_step="response_from_tool_result",
            step_kind="return",
            workflow="order_action",
            action=action_request.action.value,
            tool_status=result.status,
        )
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
            result.output
            or (_render_tool_error_message(error) if error is not None else None)
            or "Order action failed."
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
        market_data_service=None,
        toolbox: ToolBox | None = None,
        toolbox_summary: str | None = None,
        configurable_reasoner_agent: ConfigurableReasonerAgent | None = None,
        configurable_planner_agent: ConfigurablePlannerAgent | None = None,
        grouped_plan_executor: GroupedPlanExecutor | None = None,
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
                    "price context from slower research enrichment. For broad live market "
                    "scans, movers, gainers, losers, or watchlists, use available market "
                    "tools and proceed with reasonable defaults instead of asking broker "
                    "execution-risk or volatility-preference questions."
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
        self.market_data_service = market_data_service
        self.configurable_reasoner_agent = configurable_reasoner_agent
        self.configurable_planner_agent = configurable_planner_agent
        self.grouped_plan_executor = grouped_plan_executor

    @traceable(
        name="Market Analyst Handle",
        run_type="chain"
    )
    def handle(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent | None = None,
        task_complexity: TaskComplexity | None = None,
    ) -> AgentResponse:
        if not self._can_use_configurable_loop():
            return super().handle(
                request,
                intent=intent,
                task_complexity=task_complexity,
            )

        resolved_intent = intent or AgentIntent(kind=IntentKind.UNKNOWN)
        complexity = task_complexity or self.resolve_complexity(request.user_message)
        set_trace_name(f"{self.__class__.__name__}.handle")
        set_trace_metadata(
            agent_name=self.name,
            agent_kind="specialist",
            intent_kind=resolved_intent.kind.value,
            task_complexity=complexity.value,
            workflow="market_analysis",
            execution_mode="grouped_plan",
        )
        try:
            return self._handle_configurable_market_analysis(
                request,
                intent=resolved_intent,
                task_complexity=complexity,
            )
        except Exception as exc:  # pragma: no cover - live LLM/provider safety net
            return AgentResponse(
                final_answer=(
                    "I couldn't complete the configurable market-analysis loop. "
                    f"Reason: {exc.__class__.__name__}: {exc}"
                ),
                selected_agent=self.name,
                metadata={
                    "workflow": "market_analysis",
                    "workflow_status": "error",
                    "execution_mode": "grouped_plan",
                    "error_type": exc.__class__.__name__,
                },
                artifacts={
                    "workflow": "market_analysis",
                    "market_analysis": {
                        "status": "error",
                        "error": str(exc),
                        "error_type": exc.__class__.__name__,
                    },
                },
            )

    @traceable(
        name="Market Analyst Configurable Market Analysis",
        run_type="chain"
    )
    def _handle_configurable_market_analysis(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent,
        task_complexity: TaskComplexity,
    ) -> AgentResponse:
        set_trace_name(f"{self.__class__.__name__}.configurable_market_analysis")
        set_trace_metadata(
            agent_name=self.name,
            agent_step="configurable_market_analysis",
            step_kind="agentic_flow",
            intent_kind=intent.kind.value,
            task_complexity=task_complexity.value,
            workflow="market_analysis",
            execution_mode="grouped_plan",
        )
        invocation = AgentInvocationContext(
            user_request=request.user_message,
            chat_history=self._history_for_prompt(request.history),
            invocation_reason=(
                request.orchestrator_guidance
                or "Market analyst handling the current user request."
            ),
            intent=intent,
            persistent_guidance=self._persistent_guidance(),
            agent_name=self.profile.name,
            purpose=self.profile.purpose,
            guidelines=self.profile.guidelines,
            toolbox_summary=self.profile.toolbox_summary,
            tool_descriptions=render_tool_descriptions(self.profile.toolbox),
            task_complexity=task_complexity,
        )
        assert self.configurable_reasoner_agent is not None
        assert self.configurable_planner_agent is not None
        assert self.grouped_plan_executor is not None
        assert self.profile.toolbox is not None

        reasoning_context = self.configurable_reasoner_agent.reason(invocation)
        if not reasoning_context.can_proceed and reasoning_context.clarifying_questions:
            return AgentResponse(
                final_answer="I need one clarification: "
                + " ".join(reasoning_context.clarifying_questions),
                selected_agent=self.name,
                metadata={
                    "workflow": "market_analysis",
                    "workflow_status": "needs_clarification",
                    "execution_mode": "grouped_plan",
                },
                artifacts={
                    "workflow": "market_analysis",
                    "market_analysis": {
                        "reasoning_context": reasoning_context.model_dump(mode="json"),
                    },
                },
            )

        grouped_plan = self.configurable_planner_agent.plan(
            invocation,
            reasoning_context=reasoning_context,
        )
        tools_mapping = build_tool_mapping_for(
            self.profile.toolbox,
            market_data_service=self.market_data_service,
        )
        execution_result = self.grouped_plan_executor.execute(
            invocation=invocation,
            reasoning_context=reasoning_context,
            grouped_plan=grouped_plan,
            toolbox=self.profile.toolbox,
            tools_mapping=tools_mapping,
        )
        compatible_plan = grouped_plan.to_agent_plan()
        group_count = len(grouped_plan.action_groups)
        return AgentResponse(
            final_answer=execution_result.final_answer,
            selected_agent=self.name,
            plan=compatible_plan,
            metadata={
                "workflow": "market_analysis",
                "workflow_status": execution_result.status,
                "execution_mode": "grouped_plan",
                "group_count": str(group_count),
                "action_count": str(execution_result.action_count),
            },
            artifacts={
                "workflow": "market_analysis",
                "market_analysis": {
                    "reasoning_context": reasoning_context.model_dump(mode="json"),
                    "grouped_plan": grouped_plan.model_dump(mode="json"),
                    "execution": execution_result.model_dump(mode="json"),
                    "final_synthesis": execution_result.final_answer,
                },
            },
        )

    def _can_use_configurable_loop(self) -> bool:
        return (
            self.configurable_reasoner_agent is not None
            and self.configurable_planner_agent is not None
            and self.grouped_plan_executor is not None
            and self.profile.toolbox is not None
            and bool(self.profile.toolbox.tools)
        )

    @traceable(
        name="Market Analyst Execute",
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
            workflow="market_analysis",
            execution_mode="tool_orchestration",
        )
        if self.profile.toolbox is None or not self.profile.toolbox.tools:
            return None

        final_answer = self.reasoner.orchestrate_with_tools(
            agent_name=self.profile.name,
            purpose=self.profile.purpose,
            guidelines=self.profile.guidelines,
            toolbox_summary=self.profile.toolbox_summary,
            user_request=request.user_message,
            toolbox=self.profile.toolbox,
            tools_mapping=build_tool_mapping_for(
                self.profile.toolbox,
                market_data_service=self.market_data_service,
            ),
            chat_history=self._history_for_prompt(request.history),
            persistent_guidance=self._persistent_guidance(),
        )
        if not final_answer.strip():
            return None
        return AgentResponse(
            final_answer=final_answer,
            selected_agent=self.name,
            plan=plan,
            metadata={"workflow": "market_analysis", "workflow_status": "ok"},
            artifacts={"workflow": "market_analysis"},
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
    payload = action_request.model_dump(mode="json")
    return {
        "action": action_request.action.value,
        "order_type": payload.get("order_type"),
        "side": payload.get("side"),
        "ticker": payload.get("ticker"),
        "quantity": payload.get("quantity"),
        "notional_amount": payload.get("notional_amount"),
        "notional_currency": payload.get("notional_currency"),
        "limit_price": payload.get("limit_price"),
        "stop_price": payload.get("stop_price"),
        "time_in_force": payload.get("time_in_force"),
        "extended_hours": payload.get("extended_hours"),
        "use_full_position_size": payload.get("use_full_position_size"),
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


def _approval_payload_from_grouped_execution(execution_result: Any) -> dict[str, Any] | None:
    group_executions = list(getattr(execution_result, "group_executions", []) or [])
    for group in reversed(group_executions):
        actions = list(getattr(group, "actions", []) or [])
        for action in reversed(actions):
            tool_calls = list(getattr(action, "tool_calls", []) or [])
            for tool_call in reversed(tool_calls):
                if not isinstance(tool_call, dict):
                    continue
                approval = tool_call.get("telegramApproval")
                if isinstance(approval, dict):
                    return approval
    return None


def _broker_order_reasoning_guidelines() -> list[str]:
    return [
        "Treat broker reads as the only authority for cash, positions, pending orders, and order references.",
        "Treat user-supplied public symbols, company names, and ISINs as unverified for broker execution "
        "until broker_resolve_instrument or broker portfolio context confirms the broker-native instrument.",
        "Detect broker-state dependent values such as available-cash fractions, full-position exits, and protective orders that depend on a prior fill.",
        "Record unresolved or ambiguous broker instruments as required evidence, not assumptions; "
        "broker-native tradable identifiers come from broker tools or broker portfolio context.",
        "Approval and rejection are Telegram callback-button events; typed chat text is ordinary conversation.",
        "Numeric broker fields must be resolved decimal values before order preparation.",
    ]


def _broker_order_planning_guidelines() -> list[str]:
    return [
        "Use broker_get_portfolio_snapshot before preparing orders that depend on cash, holdings, or available quantities.",
        "Use broker_resolve_instrument before broker_prepare_order_action when the user supplied a public ticker, "
        "company name, ISIN, or any identifier not already confirmed as broker-native by broker data.",
        "Skip instrument-resolution when a prior broker tool output already provides the exact "
        "broker-native ticker; depend on that output instead.",
        "If broker_resolve_instrument returns ambiguous or not_found, stop before order preparation and ask for "
        "confirmation or a more precise ticker/exchange/currency rather than guessing.",
        "If broker_prepare_order_action returns an instrument-resolution error, use the tool output as the final "
        "failure explanation: no order was prepared, no approval was created, and the user must choose or provide "
        "a broker-native ticker.",
        "Add no-tool calculation actions for simple arithmetic from prior tool outputs, then pass the resolved decimal value into broker_prepare_order_action.",
        "Use broker_prepare_order_action or broker_prepare_cancel_action for Telegram flows; broker_place_order is outside the natural-language preparation flow.",
        "State-changing broker preparation actions must be sequential and dependent on all broker reads/calculations they require.",
        "If a protective stop or stop-limit depends on the buy fill price or executed quantity, model it as a dependent follow-up requiring that execution/fill context.",
    ]


def _broker_order_reasoning_examples() -> list[str]:
    return [
        (
            "User asks: 'Prepare a market buy for COIN using half my available cash.' "
            "Reasoning context should note that the notional amount is broker-state dependent, "
            "available cash must be read from broker_get_portfolio_snapshot, and notional_amount "
            "must remain unset until half of available_to_trade is calculated."
        ),
        (
            "User asks: 'Buy GOOGL.' Reasoning context should note that the public "
            "symbol may not be the broker-native tradable ticker, so broker instrument "
            "resolution is required before order preparation unless broker context "
            "already confirmed the ticker."
        )
    ]


def _broker_order_planning_examples() -> list[str]:
    return [
        (
            "Example grouped plan for cash-relative buy: "
            "group 1 sequential action broker_get_portfolio_snapshot with output_key=portfolio; "
            "group 2 sequential no-tool action calculate_notional_from_cash depending on portfolio, "
            "expected_output='resolved decimal notional amount and currency'; "
            "group 3 sequential action broker_resolve_instrument if needed; "
            "group 4 sequential action broker_prepare_order_action depending on the cash calculation "
            "and instrument resolution, passing notional_amount as a concrete decimal number."
        ),
        (
            "Example grouped plan for public-symbol buy: "
            "group 1 sequential action broker_resolve_instrument with query set to the "
            "user-provided symbol/name and output_key=instrument_resolution; "
            "group 2 sequential action broker_prepare_order_action depending on "
            "instrument_resolution, using resolvedTicker only when resolution.status is resolved. "
            "If resolution is ambiguous or not_found, stop before order preparation and ask for confirmation."
        )
    ]


def _broker_snapshot_order_context(snapshot: Any) -> str:
    account = getattr(snapshot, "account", None)
    cash = getattr(account, "cash", None) if account is not None else None
    currency = getattr(account, "currency", None)
    lines = [
        "Broker state context for order reasoning. Use these values only as current "
        "broker-provided context; calculate any relative order sizing before filling "
        "numeric order fields."
    ]
    if account is not None:
        lines.append(
            "Account: "
            f"currency={_context_value(currency)}, "
            f"total_value={_context_value(getattr(account, 'total_value', None))}."
        )
    if cash is not None:
        lines.append(
            "Cash: "
            f"available_to_trade={_context_value(getattr(cash, 'available_to_trade', None))}, "
            f"reserved_for_orders={_context_value(getattr(cash, 'reserved_for_orders', None))}, "
            f"in_pies={_context_value(getattr(cash, 'in_pies', None))}."
        )
    positions = list(getattr(snapshot, "positions", []) or [])
    if positions:
        summarized_positions = []
        for position in positions[:8]:
            instrument = getattr(position, "instrument", None)
            ticker = getattr(instrument, "ticker", None) if instrument is not None else None
            summarized_positions.append(
                "{ticker}: quantity={quantity}, available={available}".format(
                    ticker=_context_value(ticker or getattr(position, "ticker", None)),
                    quantity=_context_value(getattr(position, "quantity", None)),
                    available=_context_value(
                        getattr(position, "quantity_available_for_trading", None)
                    ),
                )
            )
        lines.append("Positions: " + "; ".join(summarized_positions) + ".")
    pending_orders = list(getattr(snapshot, "pending_orders", []) or [])
    lines.append(f"Pending orders count: {len(pending_orders)}.")
    return "\n".join(lines)


def _context_value(value: Any) -> str:
    if value is None:
        return "unknown"
    raw = str(value).strip()
    return raw if raw else "unknown"


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
