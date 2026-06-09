"""Broker order specialist agent."""

from __future__ import annotations

import logging
import time
from typing import Any

from t212ai.app.logging import log_event
from t212ai.brokers.models import BrokerOrderAction, BrokerOrderActionRequest
from t212ai.brokers.references import BrokerReferenceMap
from t212ai.brokers.tools import BrokerToolRuntime, build_broker_tool_mapping
from t212ai.genai.models import ToolResult
from t212ai.genai.tools.base import ToolBox, render_tool_descriptions
from t212ai.genai.tracing import set_trace_metadata, set_trace_name, traceable
from t212ai.guidelines.service import GuidelineMemoryService
from t212ai.pending_actions import PendingActionService
from t212ai.proposals import ProposalService
from t212ai.workflows import PendingOrdersReviewWorkflow, WorkflowExecutionError

from ...base import AgentProfile, BaseAgent
from ...configurable import ConfigurablePlannerAgent, ConfigurableReasonerAgent
from ...execution import GroupedPlanExecutor
from ...intents import AgentIntent, IntentKind
from ...planner import TaskComplexity
from ...prompts import (
    ORDER_ACTION_REQUEST_SYSTEM_PROMPT,
    build_order_action_user_prompt,
)
from ...schemas import AgentInvocationContext, AgentRequest, AgentResponse
from ..shared import _empty_toolbox
from .context import (
    _broker_snapshot_order_context,
    _match_position_for_liquidation,
    _metadata_user_id,
)
from .errors import _local_order_error, _render_tool_error_message
from .guidance import (
    _broker_order_planning_examples,
    _broker_order_planning_guidelines,
    _broker_order_reasoning_examples,
    _broker_order_reasoning_guidelines,
)
from .proposals import (
    _approval_payload_from_grouped_execution,
    _approval_with_proposal_reference,
    _order_action_summary,
    _order_intent_payload,
    _proposal_thesis,
)

LOGGER = logging.getLogger(__name__)


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
        symbol_reference_service=None,
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
        self.symbol_reference_service = symbol_reference_service
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
            symbol_reference_service=self.symbol_reference_service,
            chat_id=request.chat_id,
            user_id=_metadata_user_id(request.metadata),
            user_message=request.user_message,
            reference_map=BrokerReferenceMap(),
        )
        tools_mapping = build_broker_tool_mapping(runtime)
        execution_result = self.grouped_plan_executor.execute(
            invocation=invocation,
            reasoning_context=reasoning_context,
            grouped_plan=grouped_plan,
            toolbox=self.profile.toolbox,
            tools_mapping=tools_mapping,
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
        start = time.monotonic()
        tool_name = (
            "broker_prepare_cancel_action"
            if action_request.action == BrokerOrderAction.PREPARE_CANCEL_ORDER
            else "broker_prepare_order_action"
        )
        log_event(
            LOGGER,
            "tool.dispatch.start",
            component="tool",
            agent_name=self.name,
            step="execute_action_request",
            tool_name=tool_name,
            status="started",
            action=action_request.action.value,
            chat_id=request.chat_id,
        )
        runtime = BrokerToolRuntime(
            broker_read_service=self.broker_read_service,
            broker_execution_service=self.broker_execution_service,
            broker_provider=self.broker_provider,
            pending_action_service=self.pending_action_service,
            market_data_service=self.market_data_service,
            symbol_reference_service=self.symbol_reference_service,
            chat_id=request.chat_id,
            user_id=_metadata_user_id(request.metadata),
            user_message=request.user_message,
            reference_map=BrokerReferenceMap(),
        )
        tool_mapping = build_broker_tool_mapping(runtime)
        if action_request.action == BrokerOrderAction.PREPARE_CANCEL_ORDER:
            result = tool_mapping["broker_prepare_cancel_action"](
                order_ref=action_request.target_order_ref,
                selector=(
                    action_request.cancel_selector.value
                    if action_request.cancel_selector is not None
                    else None
                ),
                reason=action_request.reason,
            )
        else:
            result = tool_mapping["broker_prepare_order_action"](
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
        log_event(
            LOGGER,
            "tool.dispatch.end" if result.status == "ok" else "tool.dispatch.error",
            "info" if result.status == "ok" else "warning",
            component="tool",
            agent_name=self.name,
            step="execute_action_request",
            tool_name=tool_name,
            status=result.status,
            chat_id=request.chat_id,
            duration_ms=int((time.monotonic() - start) * 1000),
            error_code=result.error.code if result.error else None,
            error_type=result.error.type if result.error else None,
        )
        return result

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
