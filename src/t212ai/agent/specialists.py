"""Purpose-defined specialist agents."""

from __future__ import annotations

from typing import Any

from t212ai.brokers.trading212 import (
    T212_ORDER_ACTION_TOOLBOX,
    Trading212BrokerService,
    Trading212ToolRuntime,
    build_trading212_tool_mapping,
)
from t212ai.genai.models import ToolResult
from t212ai.guidelines.service import GuidelineMemoryService
from t212ai.pending_actions import (
    PendingActionService,
    Trading212OrderAction,
    Trading212OrderActionRequest,
)
from t212ai.workflows import (
    PendingOrdersReviewWorkflow,
    PortfolioSummaryWorkflow,
    WorkflowExecutionError,
)

from .base import AgentProfile, BaseAgent
from .intents import AgentIntent, IntentKind
from .planner import TaskComplexity
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

        result = self._execute_action_request(request, action_request)
        return self._response_from_tool_result(plan=plan, action_request=action_request, result=result)

    def _build_action_request(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent,
    ) -> Trading212OrderActionRequest:
        system_prompt = (
            "Convert the user's Trading 212 order request into a structured "
            "Trading212OrderActionRequest.\n\n"
            "Rules:\n"
            "- For buy/sell/trade requests, choose prepare_submit_order.\n"
            "- For cancellation requests, choose prepare_cancel_order.\n"
            "- Do not confirm or execute; only prepare an action.\n"
            "- For cancellation, use target_order_id when explicit, otherwise use selector "
            "latest, oldest, or only when the user's request clearly implies one.\n"
            "- For order submission, include order_type, side, ticker, quantity, "
            "limit_price, stop_price, time_validity, and extended_hours when known.\n"
            "- Do not invent ambiguous order ids or prices."
        )
        messages = []
        if request.history:
            messages.extend(request.history.to_llm_messages())
        messages.append(
            {
                "role": "user",
                "content": (
                    f"Intent hint: {intent.kind.value}\n"
                    f"User request: {request.user_message}"
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

    def _response_from_tool_result(
        self,
        *,
        plan,
        action_request: Trading212OrderActionRequest,
        result: ToolResult,
    ) -> AgentResponse:
        metadata = {
            "workflow": "order_action",
            "workflow_status": result.status,
            "action": action_request.action.value,
        }
        if result.status == "ok":
            artifacts: dict[str, Any] = {"workflow": "order_action"}
            approval = None
            if isinstance(result.data, dict):
                approval = result.data.get("telegramApproval")
                artifacts["order_action"] = result.data
            if approval:
                artifacts["telegram_approval_request"] = approval
            return AgentResponse(
                final_answer=result.output or "Prepared action awaiting approval.",
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
        return AgentResponse(
            final_answer=message,
            selected_agent=self.name,
            plan=plan,
            metadata=metadata,
            artifacts={"workflow": "order_action", "tool_result": result.model_dump(mode="json")},
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
                    "market_data: Yahoo market data and analytics; "
                    "Alpha Vantage commodities and intelligence; web search for source expansion."
                ),
                task_complexity=TaskComplexity.COMPLEX,
                guideline_scopes=("global", "agent:market"),
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
