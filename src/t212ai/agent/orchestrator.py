"""Top-level agent orchestration."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from pydantic import ValidationError
from t212ai.capabilities.protocols import BrokerExecutionService, BrokerReadService
from t212ai.genai.models import ToolError, ToolResult, ToolSpec
from t212ai.genai.tools.base import ToolBox, build_tool_index
from t212ai.genai.tracing import (
    _trace_agent_action_inputs,
    _trace_agent_action_outputs,
    _trace_agent_handle_inputs,
    _trace_agent_response_outputs,
    _trace_tool_function_inputs,
    _trace_tool_function_outputs,
    set_trace_metadata,
    set_trace_name,
    traceable,
)
from t212ai.guidelines.service import GuidelineMemoryService
from t212ai.pending_actions import PendingActionService
from t212ai.proposals import ProposalService
from t212ai.workflows import PendingOrdersReviewWorkflow, PortfolioSummaryWorkflow

from .base import AgentProfile, BaseAgent
from .configurable import ConfigurablePlannerAgent, ConfigurableReasonerAgent
from .execution import GroupedPlanExecutor
from .guideline_memory import GuidelineMemoryAgent
from .intents import AgentIntent, IntentKind
from .planner import TaskComplexity
from .reasoning import AgentReasoner
from .schemas import AgentRequest, AgentResponse, OrchestratorDelegationRequest
from .specialists import (
    CalculatorAgent,
    CompanyAnalystAgent,
    MarketAnalystAgent,
    OrderAgent,
    PortfolioAnalystAgent,
)


@dataclass(slots=True)
class SpecialistAgents:
    portfolio: PortfolioAnalystAgent
    order: OrderAgent
    market: MarketAnalystAgent
    company: CompanyAnalystAgent
    guideline_memory: GuidelineMemoryAgent
    calculator: CalculatorAgent

    def by_key(self) -> dict[str, BaseAgent]:
        return {
            "portfolio": self.portfolio,
            "order": self.order,
            "market": self.market,
            "company": self.company,
            "guideline_memory": self.guideline_memory,
            "calculator": self.calculator,
        }


@dataclass(slots=True)
class SpecialistToolRun:
    tool_name: str
    specialist_key: str
    task_brief: str
    expected_output: str
    intent: AgentIntent
    response: AgentResponse


_SPECIALIST_TOOL_CONFIGS: tuple[tuple[str, str, tuple[IntentKind, ...]], ...] = (
    (
        "delegate_to_portfolio_analyst",
        "portfolio",
        (
            IntentKind.PORTFOLIO_SUMMARY,
            IntentKind.PORTFOLIO_ATTENTION_SCAN,
            IntentKind.REBALANCE,
        ),
    ),
    (
        "delegate_to_order_agent",
        "order",
        (
            IntentKind.PLACE_ORDER,
            IntentKind.CANCEL_ORDER,
            IntentKind.REVIEW_PENDING_ORDERS,
            IntentKind.PROPOSE_TRADE,
        ),
    ),
    (
        "delegate_to_market_analyst",
        "market",
        (IntentKind.UNKNOWN,),
    ),
    (
        "delegate_to_company_analyst",
        "company",
        (IntentKind.ANALYZE_INSTRUMENT,),
    ),
    (
        "delegate_to_guideline_memory_agent",
        "guideline_memory",
        (IntentKind.MANAGE_GUIDELINES,),
    ),
    (
        "delegate_to_calculator_agent",
        "calculator",
        (IntentKind.CALCULATE,),
    ),
)


class MainOrchestratorAgent(BaseAgent):
    def __init__(
        self,
        reasoner: AgentReasoner,
        *,
        guideline_service: GuidelineMemoryService | None = None,
        specialists: SpecialistAgents | None = None,
    ) -> None:
        super().__init__(
            reasoner,
            AgentProfile(
                name="main_orchestrator",
                purpose=(
                    "Hold the user-facing conversation, decide whether to answer directly, "
                    "ask for clarification, or delegate to the right specialist."
                ),
                guidelines=(
                    "Use a concise, professional tone with friendly teammate energy. Keep "
                    "replies calm, direct, and helpful without sounding stiff. Avoid emojis "
                    "unless the user clearly sets that tone first. For Telegram-facing replies, "
                    "prefer plain text over Markdown or HTML. Answer capability questions, help "
                    "questions, and ordinary conversation directly. Delegate when specialist "
                    "reasoning, tools, workflows, or deterministic execution are needed. "
                    "Preserve safety boundaries for orders, approvals, and broker actions. "
                    "Natural-language messages can request or discuss side effects, but "
                    "pending side effects are approved or rejected only through Telegram "
                    "button callbacks."
                ),
                toolbox_summary=(
                    "Delegation tools: portfolio_analyst, order_agent, market_analyst, "
                    "company_analyst, guideline_memory_agent, calculator_agent. The "
                    "orchestrator may also answer directly or ask clarifying questions."
                ),
                task_complexity=TaskComplexity.EASY,
                guideline_scopes=("global", "orchestrator"),
                guideline_include_categories=("investment_preference",),
            ),
            guideline_service=guideline_service,
        )
        self.specialists = specialists or build_specialist_agents(
            reasoner,
            guideline_service=guideline_service,
        )
        self.orchestrator_toolbox = self._build_orchestrator_toolbox()
        self.profile.toolbox = self.orchestrator_toolbox
        self.profile.toolbox_summary = self._render_orchestrator_toolbox_summary()

    @traceable(
        name="Main Orchestrator Handle",
        run_type="chain",
        process_inputs=_trace_agent_handle_inputs,
        process_outputs=_trace_agent_response_outputs,
    )
    def handle(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent | None = None,
        task_complexity: TaskComplexity | None = None,
    ) -> AgentResponse:
        del intent
        set_trace_name(f"{self.__class__.__name__}.handle")
        set_trace_metadata(
            agent_name=self.name,
            agent_kind="orchestrator",
            task_complexity=(task_complexity or TaskComplexity.EASY).value,
        )
        tool_runs: list[SpecialistToolRun] = []
        final_answer = self._forced_order_route_answer(request, tool_runs)
        if final_answer is None:
            final_answer = self.reasoner.orchestrate_with_tools(
                agent_name=self.profile.name,
                purpose=self.profile.purpose,
                guidelines=self.profile.guidelines,
                toolbox_summary=self.profile.toolbox_summary,
                user_request=request.user_message,
                toolbox=self.orchestrator_toolbox,
                tools_mapping=self._build_tool_mapping(request, tool_runs),
                chat_history=self._history_for_prompt(request.history),
                persistent_guidance=self._persistent_guidance(),
            )
        approval_payload = self._approval_payload(tool_runs)
        if isinstance(approval_payload, dict) and approval_payload.get("text"):
            final_answer = str(approval_payload["text"])
        elif not final_answer.strip() and tool_runs:
            final_answer = tool_runs[-1].response.final_answer

        metadata, artifacts, plan, critique = self._build_response_package(tool_runs)
        return AgentResponse(
            final_answer=final_answer,
            selected_agent=self.name,
            plan=plan,
            critique=critique,
            metadata=metadata,
            artifacts=artifacts,
        )

    @traceable(
        name="Main Orchestrator Forced Order Route",
        run_type="chain",
        process_inputs=_trace_agent_action_inputs,
        process_outputs=_trace_agent_action_outputs,
    )
    def _forced_order_route_answer(
        self,
        request: AgentRequest,
        tool_runs: list[SpecialistToolRun],
    ) -> str | None:
        set_trace_name(f"{self.__class__.__name__}.forced_order_route")
        set_trace_metadata(
            agent_name=self.name,
            agent_step="forced_order_route",
            step_kind="routing",
        )
        inferred_intent = classify_message(request.user_message)
        if inferred_intent.kind not in {
            IntentKind.PLACE_ORDER,
            IntentKind.CANCEL_ORDER,
        }:
            return None
        tool_mapping = self._build_tool_mapping(request, tool_runs)
        delegate = tool_mapping["delegate_to_order_agent"]
        result = delegate(
            task_brief=self._forced_order_task_brief(inferred_intent),
            expected_output=(
                "Return a deterministic broker action result. If approval is required, "
                "prepare the Telegram button approval request; typed confirmation text "
                "is ordinary conversation."
            ),
            intent_kind=inferred_intent.kind.value,
            entities=_entities_to_items(inferred_intent),
        )
        if result.status == "ok":
            return str(result.output or "")
        if result.error is None:
            return str(result.output or "")
        message = result.error.message
        if result.error.hint:
            message = f"{message} Hint: {result.error.hint}"
        return message

    def _build_orchestrator_toolbox(self) -> ToolBox:
        specialists = self.specialists.by_key()
        tools = [
            self._delegation_tool(
                name=tool_name,
                specialist=specialists[specialist_key],
                allowed_intents=allowed_intents,
            )
            for tool_name, specialist_key, allowed_intents in _SPECIALIST_TOOL_CONFIGS
        ]
        return ToolBox(
            name="orchestrator_routing",
            tools=tools,
            tools_by_name=build_tool_index(tools),
        )

    def _render_orchestrator_toolbox_summary(self) -> str:
        lines: list[str] = []
        for tool in self.orchestrator_toolbox.tools:
            function = tool.get("function", {})
            description = str(function.get("description") or "").strip()
            lines.append(f"- {function.get('name')}: {description}")
        return "\n".join(lines)

    def _delegation_tool(
        self,
        *,
        name: str,
        specialist: BaseAgent,
        allowed_intents: tuple[IntentKind, ...],
    ) -> ToolSpec:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": self._tool_description(
                    specialist=specialist,
                    allowed_intents=allowed_intents,
                ),
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "task_brief": {
                            "type": "string",
                            "description": (
                                "What the specialist should focus on for this turn."
                            ),
                        },
                        "expected_output": {
                            "type": "string",
                            "description": (
                                "What kind of result you want back from the specialist."
                            ),
                        },
                        "intent_kind": {
                            "type": "string",
                            "enum": [intent.value for intent in allowed_intents],
                        },
                        "entities": {
                            "type": "array",
                            "description": (
                                "Structured hints extracted from the request, such as "
                                "ticker, order_ref, domain, or operation."
                            ),
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "key": {"type": "string"},
                                    "value": {"type": "string"},
                                },
                                "required": ["key", "value"],
                            },
                        },
                    },
                    "required": [
                        "task_brief",
                        "expected_output",
                        "intent_kind",
                        "entities",
                    ],
                },
                "strict": True,
            },
        }

    def _tool_description(
        self,
        *,
        specialist: BaseAgent,
        allowed_intents: tuple[IntentKind, ...],
    ) -> str:
        intents = ", ".join(intent.value for intent in allowed_intents)
        return (
            f"Delegate work to {specialist.name}. Purpose: {specialist.profile.purpose} "
            f"Capabilities: {specialist.profile.toolbox_summary} "
            f"Allowed intents: {intents}."
        )

    def _build_tool_mapping(
        self,
        request: AgentRequest,
        tool_runs: list[SpecialistToolRun],
    ) -> dict[str, Any]:
        specialists = self.specialists.by_key()
        mapping: dict[str, Any] = {}
        for tool_name, specialist_key, allowed_intents in _SPECIALIST_TOOL_CONFIGS:
            specialist = specialists[specialist_key]
            mapping[tool_name] = self._build_specialist_tool(
                request=request,
                tool_runs=tool_runs,
                tool_name=tool_name,
                specialist_key=specialist_key,
                specialist=specialist,
                allowed_intents=allowed_intents,
            )
        return mapping

    def _build_specialist_tool(
        self,
        *,
        request: AgentRequest,
        tool_runs: list[SpecialistToolRun],
        tool_name: str,
        specialist_key: str,
        specialist: BaseAgent,
        allowed_intents: tuple[IntentKind, ...],
    ):
        @traceable(
            name=tool_name,
            run_type="tool",
            process_inputs=_trace_tool_function_inputs,
            process_outputs=_trace_tool_function_outputs,
        )
        def _delegate(
            *,
            task_brief: str,
            expected_output: str,
            intent_kind: str,
            entities: list[dict[str, str]] | None = None,
        ) -> ToolResult:
            set_trace_name(tool_name)
            set_trace_metadata(
                agent_name=self.name,
                agent_step="delegate_to_specialist",
                step_kind="tool",
                tool_name=tool_name,
                specialist_key=specialist_key,
                specialist_name=specialist.name,
                intent_kind=intent_kind,
            )
            try:
                delegation = OrchestratorDelegationRequest.model_validate(
                    {
                        "task_brief": task_brief,
                        "expected_output": expected_output,
                        "intent_kind": intent_kind,
                        "entities": entities or [],
                    }
                )
            except ValidationError as exc:
                return ToolResult(
                    status="error",
                    error=ToolError(
                        message="Invalid routing payload for specialist delegation.",
                        code="invalid_delegation_payload",
                        hint="Provide task_brief, expected_output, intent_kind, and entities.",
                        retryable=False,
                        details={"errors": exc.errors()},
                    ),
                )
            if delegation.intent_kind not in allowed_intents:
                return ToolResult(
                    status="error",
                    error=ToolError(
                        message=(
                            f"Intent '{delegation.intent_kind.value}' is not valid for "
                            f"{tool_name}."
                        ),
                        code="invalid_specialist_intent",
                        hint=(
                            "Choose one of: "
                            + ", ".join(intent.value for intent in allowed_intents)
                        ),
                        retryable=False,
                    ),
                )
            resolved_intent = delegation.to_agent_intent()
            delegated_request = request.model_copy(
                update={
                    "orchestrator_guidance": self._delegation_guidance(
                        task_brief=delegation.task_brief,
                        expected_output=delegation.expected_output,
                        existing=request.orchestrator_guidance,
                    )
                }
            )
            response = specialist.handle(delegated_request, intent=resolved_intent)
            tool_runs.append(
                SpecialistToolRun(
                    tool_name=tool_name,
                    specialist_key=specialist_key,
                    task_brief=delegation.task_brief,
                    expected_output=delegation.expected_output,
                    intent=resolved_intent,
                    response=response,
                )
            )
            return ToolResult(
                status="ok",
                output=response.final_answer,
                data={
                    "specialist": specialist.name,
                    "task_brief": delegation.task_brief,
                    "expected_output": delegation.expected_output,
                    "intent": resolved_intent.model_dump(mode="json"),
                    "final_answer": response.final_answer,
                    "plan": (
                        response.plan.model_dump(mode="json")
                        if response.plan is not None
                        else None
                    ),
                    "metadata": response.metadata,
                    "artifacts": response.artifacts,
                },
            )

        return _delegate

    def _delegation_guidance(
        self,
        *,
        task_brief: str,
        expected_output: str,
        existing: str | None,
    ) -> str:
        guidance = (
            f"Task brief: {task_brief}\n"
            f"Expected output: {expected_output}"
        )
        if existing and existing.strip():
            return f"{existing}\n\n{guidance}"
        return guidance

    @traceable(
        name="Main Orchestrator Build Response Package",
        run_type="chain",
        process_inputs=_trace_agent_action_inputs,
        process_outputs=_trace_agent_action_outputs,
    )
    def _build_response_package(
        self,
        tool_runs: list[SpecialistToolRun],
    ) -> tuple[dict[str, str], dict[str, Any], Any, Any]:
        set_trace_name(f"{self.__class__.__name__}.build_response_package")
        set_trace_metadata(
            agent_name=self.name,
            agent_step="build_response_package",
            step_kind="return",
            tool_run_count=len(tool_runs),
        )
        if not tool_runs:
            return (
                {"route": "direct", "orchestrator": self.name},
                {},
                None,
                None,
            )
        last = tool_runs[-1]
        route_sequence = [run.response.selected_agent for run in tool_runs]
        metadata = dict(last.response.metadata)
        metadata.update(
            {
                "orchestrator": self.name,
                "intent": last.intent.kind.value,
                "route": last.response.selected_agent,
            }
        )
        if len(route_sequence) > 1:
            metadata["route_sequence"] = " -> ".join(route_sequence)
        set_trace_metadata(route=last.response.selected_agent, route_sequence=route_sequence)
        artifacts: dict[str, Any] = {
            "route_sequence": route_sequence,
            "orchestrator_tool_runs": [
                {
                    "tool_name": run.tool_name,
                    "specialist": run.response.selected_agent,
                    "task_brief": run.task_brief,
                    "expected_output": run.expected_output,
                    "intent": run.intent.model_dump(mode="json"),
                    "metadata": run.response.metadata,
                    "plan": (
                        run.response.plan.model_dump(mode="json")
                        if run.response.plan is not None
                        else None
                    ),
                }
                for run in tool_runs
            ],
        }
        if len(tool_runs) == 1:
            artifacts.update(dict(last.response.artifacts))
        else:
            specialist_artifacts = {
                run.response.selected_agent: dict(run.response.artifacts)
                for run in tool_runs
                if run.response.artifacts
            }
            if specialist_artifacts:
                artifacts["specialist_artifacts"] = specialist_artifacts
            if last.response.artifacts:
                for key, value in last.response.artifacts.items():
                    artifacts.setdefault(key, value)
        approval_payload = self._approval_payload(tool_runs)
        if isinstance(approval_payload, dict):
            artifacts["telegram_approval_request"] = approval_payload
        return metadata, artifacts, last.response.plan, last.response.critique

    def _approval_payload(
        self,
        tool_runs: list[SpecialistToolRun],
    ) -> dict[str, Any] | None:
        for run in reversed(tool_runs):
            approval = run.response.artifacts.get("telegram_approval_request")
            if isinstance(approval, dict):
                return approval
        return None

    def _forced_order_task_brief(self, intent: AgentIntent) -> str:
        if intent.kind == IntentKind.CANCEL_ORDER:
            return (
                "Treat this as a broker order cancellation request. Resolve the target "
                "deterministically, prepare the cancellation for Telegram approval, and "
                "avoid conversational confirmation."
            )
        return (
            "Treat this as an executable broker order request. Extract the order details, "
            "prepare the order for deterministic Telegram button approval, and avoid "
            "conversational confirmation."
        )


class AgentOrchestrator:
    """Compatibility fallback classifier used before the full agent runtime is wired."""

    def classify_fallback(self, message: str) -> AgentIntent:
        return classify_message(message)


def build_specialist_agents(
    reasoner: AgentReasoner,
    *,
    guideline_service: GuidelineMemoryService | None = None,
    calculator_agent: CalculatorAgent | None = None,
    portfolio_summary_workflow: PortfolioSummaryWorkflow | None = None,
    pending_orders_review_workflow: PendingOrdersReviewWorkflow | None = None,
    broker_read_service: BrokerReadService | None = None,
    broker_execution_service: BrokerExecutionService | None = None,
    market_data_service=None,
    configurable_reasoner_agent: ConfigurableReasonerAgent | None = None,
    configurable_planner_agent: ConfigurablePlannerAgent | None = None,
    grouped_plan_executor: GroupedPlanExecutor | None = None,
    broker_provider: str = "broker",
    pending_action_service: PendingActionService | None = None,
    proposal_service: ProposalService | None = None,
    portfolio_toolbox_summary: str | None = None,
    order_toolbox: "ToolBox | None" = None,
    order_toolbox_summary: str | None = None,
    market_toolbox: "ToolBox | None" = None,
    market_toolbox_summary: str | None = None,
    company_toolbox_summary: str | None = None,
) -> SpecialistAgents:
    if guideline_service is None:
        guideline_service = GuidelineMemoryService.from_path("data/guidelines/guidelines.json")
    return SpecialistAgents(
        portfolio=PortfolioAnalystAgent(
            reasoner,
            guideline_service=guideline_service,
            portfolio_summary_workflow=portfolio_summary_workflow,
            toolbox_summary=portfolio_toolbox_summary,
        ),
        order=OrderAgent(
            reasoner,
            guideline_service=guideline_service,
            pending_orders_review_workflow=pending_orders_review_workflow,
            broker_read_service=broker_read_service,
            broker_execution_service=broker_execution_service,
            market_data_service=market_data_service,
            broker_provider=broker_provider,
            pending_action_service=pending_action_service,
            proposal_service=proposal_service,
            toolbox=order_toolbox,
            toolbox_summary=order_toolbox_summary,
            configurable_reasoner_agent=configurable_reasoner_agent,
            configurable_planner_agent=configurable_planner_agent,
            grouped_plan_executor=grouped_plan_executor,
        ),
        market=MarketAnalystAgent(
            reasoner,
            guideline_service=guideline_service,
            market_data_service=market_data_service,
            toolbox=market_toolbox,
            toolbox_summary=market_toolbox_summary,
            configurable_reasoner_agent=configurable_reasoner_agent,
            configurable_planner_agent=configurable_planner_agent,
            grouped_plan_executor=grouped_plan_executor,
        ),
        company=CompanyAnalystAgent(
            reasoner,
            guideline_service=guideline_service,
            toolbox_summary=company_toolbox_summary,
        ),
        guideline_memory=GuidelineMemoryAgent(reasoner, guideline_service),
        calculator=calculator_agent or CalculatorAgent(
            reasoner,
            guideline_service=guideline_service,
        ),
    )


def classify_message(message: str) -> AgentIntent:
    text = message.strip().lower()
    if text in {"/help", "help"}:
        return AgentIntent(kind=IntentKind.HELP, confidence=1.0)
    guideline_intent = _classify_guideline_message(text)
    if guideline_intent is not None:
        return guideline_intent
    if any(word in text for word in ("cancel", "order status")):
        return AgentIntent(kind=IntentKind.CANCEL_ORDER, confidence=0.85)
    if any(word in text for word in ("pending order", "orders", "open order")):
        return AgentIntent(kind=IntentKind.REVIEW_PENDING_ORDERS, confidence=0.8)
    if _is_explicit_order_execution_request(text):
        return AgentIntent(
            kind=IntentKind.PLACE_ORDER,
            entities={"action": "liquidate" if "liquidate" in text or "close" in text or "exit" in text else "submit_order"},
            confidence=0.9,
        )
    if any(word in text for word in ("buy", "sell", "place order", "trade")):
        return AgentIntent(kind=IntentKind.PROPOSE_TRADE, confidence=0.8)
    has_digit = any(char.isdigit() for char in text)
    has_operator = any(symbol in text for symbol in ("+", "-", "*", "/", "^", "%"))
    if "calculate" in text or (has_digit and has_operator) or ("what is" in text and has_digit):
        return AgentIntent(kind=IntentKind.CALCULATE, confidence=0.7)
    if any(word in text for word in ("portfolio", "position", "holding", "allocation")):
        return AgentIntent(kind=IntentKind.PORTFOLIO_SUMMARY, confidence=0.8)
    if any(word in text for word in ("attention", "risk", "exposure", "rebalance")):
        return AgentIntent(kind=IntentKind.PORTFOLIO_ATTENTION_SCAN, confidence=0.82)
    if any(word in text for word in ("market", "macro", "commodity", "gainers", "losers")):
        return AgentIntent(kind=IntentKind.UNKNOWN, entities={"domain": "market"}, confidence=0.55)
    if any(word in text for word in ("analyze", "company", "ticker", "earnings", "analyst")):
        return AgentIntent(kind=IntentKind.ANALYZE_INSTRUMENT, confidence=0.75)
    return AgentIntent(kind=IntentKind.UNKNOWN, entities={"message": message}, confidence=0.0)


def _entities_to_items(intent: AgentIntent) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for key, value in intent.entities.items():
        normalized_key = str(key).strip()
        normalized_value = str(value).strip()
        if normalized_key and normalized_value:
            items.append({"key": normalized_key, "value": normalized_value})
    return items


def _classify_guideline_message(text: str) -> AgentIntent | None:
    if any(
        phrase in text
        for phrase in (
            "remember that",
            "remember this",
            "save this preference",
            "save this rule",
            "add a rule",
            "add guideline",
            "create guideline",
        )
    ):
        return AgentIntent(
            kind=IntentKind.MANAGE_GUIDELINES,
            entities={"operation": "create"},
            confidence=0.9,
        )
    if any(
        phrase in text
        for phrase in (
            "update my preference",
            "update guideline",
            "update rule",
            "change my preference",
        )
    ):
        return AgentIntent(
            kind=IntentKind.MANAGE_GUIDELINES,
            entities={"operation": "update"},
            confidence=0.88,
        )
    if any(
        phrase in text
        for phrase in (
            "forget that",
            "forget this",
            "archive guideline",
            "archive rule",
            "remove this rule",
        )
    ):
        return AgentIntent(
            kind=IntentKind.MANAGE_GUIDELINES,
            entities={"operation": "archive"},
            confidence=0.88,
        )
    if any(
        phrase in text
        for phrase in (
            "delete guideline",
            "delete rule permanently",
            "permanently delete",
        )
    ):
        return AgentIntent(
            kind=IntentKind.MANAGE_GUIDELINES,
            entities={"operation": "delete"},
            confidence=0.92,
        )
    if any(
        phrase in text
        for phrase in (
            "list saved rules",
            "list guidelines",
            "show saved guidelines",
            "show my saved rules",
        )
    ):
        return AgentIntent(
            kind=IntentKind.MANAGE_GUIDELINES,
            entities={"operation": "list"},
            confidence=0.85,
        )
    if any(
        phrase in text
        for phrase in (
            "render guidelines",
            "show guideline markdown",
            "preview guideline render",
        )
    ):
        return AgentIntent(
            kind=IntentKind.MANAGE_GUIDELINES,
            entities={"operation": "render"},
            confidence=0.85,
        )
    return None


def _is_explicit_order_execution_request(text: str) -> bool:
    patterns = (
        r"^\s*(buy|sell)\b",
        r"^\s*can you\s+(buy|sell|liquidate|close|exit)\b",
        r"\b(i want to|please|go ahead and)\s+(buy|sell|liquidate|close|exit)\b",
        r"\b(liquidate|fully liquidate|close my position|close the position|close position)\b",
        r"\b(exit my position|exit the position|exit position|sell all|fully close)\b",
        r"\b(place order|market order|limit order)\b",
        r"\b(at market|at mkt|market price)\b",
    )
    return any(re.search(pattern, text) for pattern in patterns)
