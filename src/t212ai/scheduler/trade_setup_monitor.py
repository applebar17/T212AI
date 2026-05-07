"""LLM-assisted trade setup monitor with guarded pending proposals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from t212ai.agent.intents import AgentIntent, IntentKind
from t212ai.agent.planner import TaskComplexity
from t212ai.agent.schemas import AgentRequest, AgentResponse
from t212ai.agent.structured import StructuredAgentOutputSynthesizer
from t212ai.brokers.models import BrokerOrderSide, BrokerOrderType, BrokerTimeInForce
from t212ai.capabilities import BrokerExecutionService, BrokerReadService, MarketDataService
from t212ai.market_signals import MarketSignalService
from t212ai.pending_actions import PendingActionKind, PendingActionService, approval_expiry
from t212ai.proposals import ProposalService

from .instrument_monitor import InstrumentMonitorAdapter
from .models import (
    ScheduledExecutionMode,
    ScheduledProcess,
    ScheduledProcessKind,
    ScheduledRunStatus,
    ScheduleType,
)
from .worker import ScheduledAdapterResult


class TradeSetupQuality(StrEnum):
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    REJECT = "reject"
    UNKNOWN = "unknown"


class TradeSetupProposedOrder(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    ticker: str
    side: BrokerOrderSide
    order_type: BrokerOrderType = Field(alias="orderType")
    quantity: Decimal | None = None
    notional_amount: Decimal | None = Field(default=None, alias="notionalAmount")
    notional_currency: str | None = Field(default=None, alias="notionalCurrency")
    limit_price: Decimal | None = Field(default=None, alias="limitPrice")
    stop_price: Decimal | None = Field(default=None, alias="stopPrice")
    time_in_force: BrokerTimeInForce = Field(default=BrokerTimeInForce.DAY, alias="timeInForce")
    extended_hours: bool = Field(default=False, alias="extendedHours")
    rationale: str = ""

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, value: str) -> str:
        resolved = str(value or "").strip().upper()
        if not resolved:
            raise ValueError("ticker is required")
        return resolved


class TradeSetupAnalysis(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    symbol: str
    setup_summary: str = Field(alias="setupSummary")
    thesis: str
    risks: list[str] = Field(default_factory=list)
    setup_quality: TradeSetupQuality = Field(default=TradeSetupQuality.UNKNOWN, alias="setupQuality")
    should_propose_order: bool = Field(default=False, alias="shouldProposeOrder")
    proposed_order: TradeSetupProposedOrder | None = Field(default=None, alias="proposedOrder")
    caveats: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list, alias="sourceRefs")
    data_freshness: str = Field(default="unknown", alias="dataFreshness")
    telegram_brief: str = Field(alias="telegramBrief")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    no_broker_action_configured: bool = Field(
        default=True,
        alias="noBrokerActionConfigured",
    )

    @field_validator("symbol")
    @classmethod
    def _normalize_symbol(cls, value: str) -> str:
        resolved = str(value or "").strip().upper()
        if not resolved:
            raise ValueError("symbol is required")
        return resolved

    @field_validator("setup_summary", "thesis", "telegram_brief")
    @classmethod
    def _required_text(cls, value: str) -> str:
        resolved = str(value or "").strip()
        if not resolved:
            raise ValueError("field is required and cannot be empty")
        return resolved

    @field_validator("no_broker_action_configured")
    @classmethod
    def _must_not_configure_broker_action(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("noBrokerActionConfigured must be true")
        return True


@dataclass(slots=True)
class TradeSetupMonitorAdapter:
    market_agent: Any | None = None
    market_data_service: MarketDataService | None = None
    broker_read_service: BrokerReadService | None = None
    broker_execution_service: BrokerExecutionService | None = None
    pending_action_service: PendingActionService | None = None
    proposal_service: ProposalService | None = None
    market_signal_service: MarketSignalService | None = None
    broker_provider: str = "broker"
    structured_synthesizer: StructuredAgentOutputSynthesizer | None = None

    def run(self, process: ScheduledProcess) -> ScheduledAdapterResult:
        try:
            spec = _TradeSetupProcessSpec.from_process(process)
        except Exception as exc:
            return _failed_invalid_spec(exc)
        trigger_result = InstrumentMonitorAdapter(self.market_data_service).run(process)
        if trigger_result.status == ScheduledRunStatus.FAILED:
            return ScheduledAdapterResult(
                status=ScheduledRunStatus.FAILED,
                code="invalid_trade_setup_monitor_spec",
                message=f"Invalid trade setup monitor spec: {trigger_result.message}.",
                metadata={"trigger": trigger_result.metadata},
            )
        if trigger_result.status != ScheduledRunStatus.COMPLETED:
            return trigger_result
        if not trigger_result.matched:
            return ScheduledAdapterResult(
                status=ScheduledRunStatus.COMPLETED,
                matched=False,
                code="no_match",
                message=trigger_result.message,
                output_summary=trigger_result.output_summary,
                metadata={"trigger": trigger_result.metadata, **spec.base_metadata},
            )
        if self.market_agent is None:
            return _skipped(
                code="llm_unavailable",
                message="Trade setup monitor requires a configured market analyst/LLM after trigger match.",
                metadata={"trigger": trigger_result.metadata, **spec.base_metadata},
            )
        if spec.proposal_creation_allowed:
            missing = self._missing_proposal_services()
            if missing:
                return _skipped(
                    code=missing,
                    message=f"Trade setup proposal creation is unavailable: {missing}.",
                    metadata={"trigger": trigger_result.metadata, **spec.base_metadata},
                )

        evidence = self._build_evidence(process, spec, trigger_result.metadata)
        market_response = self._run_market_agent(process, spec, evidence)
        try:
            analysis = self._synthesize_analysis(
                process=process,
                spec=spec,
                evidence=evidence,
                market_response=market_response,
            )
        except Exception as exc:
            return ScheduledAdapterResult(
                status=ScheduledRunStatus.FAILED,
                code="trade_setup_analysis_failed",
                message=f"Trade setup structured analysis failed: {exc}.",
                metadata={
                    "error": str(exc),
                    "errorType": exc.__class__.__name__,
                    "evidence": evidence,
                    **spec.base_metadata,
                },
            )

        if not analysis.should_propose_order or analysis.proposed_order is None:
            notification = (
                _render_non_proposal_notification(process, analysis, evidence)
                if _notification_enabled(process)
                else None
            )
            matched = analysis.setup_quality != TradeSetupQuality.REJECT
            return ScheduledAdapterResult(
                status=ScheduledRunStatus.COMPLETED,
                matched=matched and not spec.proposal_creation_allowed,
                code="setup_matched_no_proposal" if matched else "setup_rejected",
                message="Trade setup analysis completed without creating a proposal.",
                output_summary=analysis.telegram_brief,
                metadata=_metadata(spec, analysis, evidence),
                notification_message=notification,
                notification_metadata={"symbol": spec.symbol, "setupQuality": analysis.setup_quality.value},
            )

        if not spec.proposal_creation_allowed:
            notification = (
                _render_non_proposal_notification(process, analysis, evidence)
                if _notification_enabled(process)
                else None
            )
            return ScheduledAdapterResult(
                status=ScheduledRunStatus.COMPLETED,
                matched=True,
                code="setup_matched_no_proposal",
                message="Trade setup matched, but proposal creation is disabled.",
                output_summary=analysis.telegram_brief,
                metadata=_metadata(spec, analysis, evidence),
                notification_message=notification,
                notification_metadata={"symbol": spec.symbol, "setupQuality": analysis.setup_quality.value},
            )

        rejection = _policy_rejection(analysis.proposed_order, spec.order_policy)
        if rejection is not None:
            metadata = _metadata(spec, analysis, evidence)
            metadata["proposalRejectedReason"] = rejection
            return ScheduledAdapterResult(
                status=ScheduledRunStatus.COMPLETED,
                matched=False,
                code="proposed_order_rejected",
                message=f"Trade setup proposed order rejected by safety policy: {rejection}.",
                output_summary=analysis.telegram_brief,
                metadata=metadata,
            )

        try:
            prepared = self.broker_execution_service.prepare_order(
                order_type=analysis.proposed_order.order_type.value,
                side=analysis.proposed_order.side.value,
                ticker=analysis.proposed_order.ticker,
                quantity=analysis.proposed_order.quantity,
                notional_amount=analysis.proposed_order.notional_amount,
                notional_currency=analysis.proposed_order.notional_currency,
                limit_price=analysis.proposed_order.limit_price,
                stop_price=analysis.proposed_order.stop_price,
                time_in_force=analysis.proposed_order.time_in_force.value,
                extended_hours=analysis.proposed_order.extended_hours,
            )
        except Exception as exc:
            return _skipped(
                code="broker_order_preparation_failed",
                message=f"Broker order preparation failed: {exc}.",
                metadata={
                    **_metadata(spec, analysis, evidence),
                    "error": str(exc),
                    "errorType": exc.__class__.__name__,
                },
            )

        try:
            proposal = self.proposal_service.create_submit_order_proposal(
                chat_id=str(spec.approval_chat_id),
                user_id=spec.approval_user_id,
                intent_kind=IntentKind.PROPOSE_TRADE.value,
                original_user_message=f"Scheduled trade setup {process.process_id}: {process.title}",
                action_summary=_order_summary(analysis.proposed_order),
                order_intent=_order_intent_payload(analysis.proposed_order),
                thesis=analysis.thesis,
                risks=analysis.risks,
                confidence=analysis.confidence,
            )
            action = self.pending_action_service.create_submit_action(
                chat_id=str(spec.approval_chat_id),
                user_id=spec.approval_user_id,
                prepared_order=prepared,
                original_user_message=f"Scheduled trade setup {process.process_id}: {process.title}",
                summary_text=_pending_action_summary(
                    process=process,
                    analysis=analysis,
                    order=analysis.proposed_order,
                    policy=spec.order_policy,
                    proposal_id=proposal.proposal_id,
                ),
                expires_at=approval_expiry(
                    kind=PendingActionKind.SUBMIT_ORDER,
                    order_type=prepared.order_type.value,
                ),
                broker_provider=self.broker_provider,
            )
            self.proposal_service.attach_pending_action(
                proposal.proposal_id,
                pending_action_id=action.action_id,
            )
        except Exception as exc:
            return ScheduledAdapterResult(
                status=ScheduledRunStatus.FAILED,
                code="proposal_creation_failed",
                message=f"Trade setup proposal creation failed: {exc}.",
                metadata={
                    **_metadata(spec, analysis, evidence),
                    "error": str(exc),
                    "errorType": exc.__class__.__name__,
                },
            )

        approval_payload = _approval_payload(
            action_id=action.action_id,
            proposal_id=proposal.proposal_id,
            text=_approval_text(
                process=process,
                analysis=analysis,
                order=analysis.proposed_order,
                policy=spec.order_policy,
                proposal_id=proposal.proposal_id,
                pending_action_id=action.action_id,
            ),
        )
        metadata = _metadata(spec, analysis, evidence)
        metadata.update(
            {
                "proposalId": proposal.proposal_id,
                "pendingActionId": action.action_id,
                "preparedOrder": prepared.model_dump(by_alias=True, exclude_none=True, mode="json"),
                "approvalPayload": approval_payload,
            }
        )
        return ScheduledAdapterResult(
            status=ScheduledRunStatus.COMPLETED,
            matched=True,
            code="pending_proposal_created",
            message=(
                f"Created pending trade setup proposal {proposal.proposal_id} "
                f"with action {action.action_id}."
            ),
            output_summary=analysis.telegram_brief,
            metadata=metadata,
            notification_message=str(approval_payload["text"]) if _notification_enabled(process) else None,
            notification_metadata={
                "symbol": spec.symbol,
                "proposalId": proposal.proposal_id,
                "pendingActionId": action.action_id,
            },
            notification_target_chat_ids=(spec.approval_chat_id,),
            notification_approval_payload=approval_payload if _notification_enabled(process) else None,
        )

    def _missing_proposal_services(self) -> str | None:
        if self.broker_read_service is None:
            return "broker_read_unavailable"
        if self.broker_execution_service is None:
            return "broker_order_preparation_unavailable"
        if self.pending_action_service is None:
            return "pending_action_service_unavailable"
        if self.proposal_service is None:
            return "proposal_service_unavailable"
        return None

    def _build_evidence(
        self,
        process: ScheduledProcess,
        spec: "_TradeSetupProcessSpec",
        trigger_evidence: dict[str, Any],
    ) -> dict[str, Any]:
        caveats: list[str] = []
        evidence: dict[str, Any] = {
            "processId": process.process_id,
            "title": process.title,
            "symbol": spec.symbol,
            "trigger": trigger_evidence,
            "taskGuidelines": spec.task_guidelines,
            "caveats": caveats,
        }
        evidence["brokerContext"] = self._broker_context(spec, caveats)
        evidence["marketSignals"] = self._market_signal_context(spec, caveats)
        return evidence

    def _broker_context(self, spec: "_TradeSetupProcessSpec", caveats: list[str]) -> dict[str, Any]:
        if self.broker_read_service is None:
            caveats.append("Broker read service is not configured.")
            return {"available": False}
        try:
            snapshot = self.broker_read_service.get_portfolio_snapshot()
        except Exception as exc:
            caveats.append(f"Broker portfolio context failed: {exc}.")
            return {"available": False, "error": str(exc), "errorType": exc.__class__.__name__}
        payload = _model_payload(snapshot)
        data = payload.get("data")
        if isinstance(data, dict):
            positions = data.get("positions")
            if isinstance(positions, list):
                data["positions"] = [
                    position
                    for position in positions
                    if str(position.get("ticker") or "").strip().upper() == spec.symbol
                ][:3]
            pending = data.get("pendingOrders")
            if isinstance(pending, list):
                data["pendingOrders"] = [
                    order
                    for order in pending
                    if str(order.get("ticker") or "").strip().upper() == spec.symbol
                ][:5]
        return payload

    def _market_signal_context(
        self,
        spec: "_TradeSetupProcessSpec",
        caveats: list[str],
    ) -> dict[str, Any]:
        if self.market_signal_service is None:
            caveats.append("Market signal memory is not configured.")
            return {"available": False, "matches": []}
        try:
            matches = self.market_signal_service.search_signals(symbols=[spec.symbol], limit=5)
        except Exception as exc:
            caveats.append(f"Market signal search failed: {exc}.")
            return {"available": False, "error": str(exc), "errorType": exc.__class__.__name__}
        return {
            "available": True,
            "matches": [_model_payload(match) for match in matches],
        }

    def _run_market_agent(
        self,
        process: ScheduledProcess,
        spec: "_TradeSetupProcessSpec",
        evidence: dict[str, Any],
    ) -> AgentResponse:
        request = AgentRequest(
            user_message=f"Evaluate matched scheduled trade setup for {spec.symbol}.",
            trigger_type="scheduler",
            orchestrator_guidance=_guidance(process, spec, evidence),
            metadata={"process_id": process.process_id, "scheduler_kind": process.kind.value},
        )
        return self.market_agent.handle(
            request,
            intent=AgentIntent(kind=IntentKind.PROPOSE_TRADE, entities={"ticker": spec.symbol}),
            task_complexity=TaskComplexity.CRITICAL,
        )

    def _synthesize_analysis(
        self,
        *,
        process: ScheduledProcess,
        spec: "_TradeSetupProcessSpec",
        evidence: dict[str, Any],
        market_response: AgentResponse,
    ) -> TradeSetupAnalysis:
        synthesizer = self.structured_synthesizer
        if synthesizer is None:
            synthesizer = StructuredAgentOutputSynthesizer(self.market_agent.reasoner.genai)
        result = synthesizer.synthesize(
            TradeSetupAnalysis,
            source_agent_name=getattr(self.market_agent, "name", "market_analyst"),
            source_response=market_response,
            user_request=f"{process.title}: evaluate trade setup for {spec.symbol}",
            instructions=(
                "Return a compact trade setup analysis after a deterministic trigger "
                "matched. You may propose order terms only within the configured "
                "policy context. noBrokerActionConfigured must be true because the "
                "scheduler cannot submit orders."
            ),
            context={
                "process": process.model_dump(by_alias=True, mode="json"),
                "evidence": evidence,
                "orderPolicy": spec.order_policy.model_dump(mode="json") if spec.order_policy else None,
            },
            task_complexity=TaskComplexity.CRITICAL,
        )
        return TradeSetupAnalysis.model_validate(result)


@dataclass(frozen=True, slots=True)
class _OrderPolicy:
    allowed_symbols: tuple[str, ...]
    allowed_sides: tuple[str, ...]
    allowed_order_types: tuple[str, ...]
    max_quantity: Decimal | None
    max_notional_amount: Decimal | None
    notional_currency: str | None
    allow_extended_hours: bool = False

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        del mode
        return {
            "allowedSymbols": list(self.allowed_symbols),
            "allowedSides": list(self.allowed_sides),
            "allowedOrderTypes": list(self.allowed_order_types),
            "maxQuantity": str(self.max_quantity) if self.max_quantity is not None else None,
            "maxNotionalAmount": (
                str(self.max_notional_amount)
                if self.max_notional_amount is not None
                else None
            ),
            "notionalCurrency": self.notional_currency,
            "allowExtendedHours": self.allow_extended_hours,
        }


@dataclass(frozen=True, slots=True)
class _TradeSetupProcessSpec:
    symbol: str
    proposal_creation_allowed: bool
    order_policy: _OrderPolicy | None
    approval_chat_id: int | None
    approval_user_id: int | None
    task_guidelines: str

    @property
    def base_metadata(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "proposalCreationAllowed": self.proposal_creation_allowed,
            "approvalChatId": self.approval_chat_id,
        }

    @classmethod
    def from_process(cls, process: ScheduledProcess) -> "_TradeSetupProcessSpec":
        if process.kind != ScheduledProcessKind.TRADE_SETUP_MONITOR:
            raise ValueError("kind must be trade_setup_monitor")
        if process.execution_mode != ScheduledExecutionMode.LLM_ASSISTED:
            raise ValueError("execution_mode must be llm_assisted")
        if process.schedule.type != ScheduleType.POLLING:
            raise ValueError("schedule.type must be polling")
        if process.safety.broker_actions_allowed:
            raise ValueError("brokerActionsAllowed must be false")
        symbol = str(process.trigger.get("symbol") or process.inputs.get("symbol") or "").strip().upper()
        if not symbol:
            raise ValueError("symbol is required")
        action_type = str(process.action.get("type") or "").strip().lower()
        if action_type and action_type != "notify_or_propose":
            raise ValueError("trade_setup_monitor supports notify_or_propose action only")
        proposal_allowed = _bool(process.action.get("proposalCreationAllowed", False))
        policy = _policy_from_action(process.action.get("orderPolicy")) if proposal_allowed else None
        approval = process.action.get("approval") if isinstance(process.action.get("approval"), dict) else {}
        chat_id = _optional_int(approval.get("chatId"))
        user_id = _optional_int(approval.get("userId"))
        if proposal_allowed:
            if policy is None:
                raise ValueError("proposal-capable specs require orderPolicy")
            if chat_id is None:
                raise ValueError("proposal-capable specs require approval.chatId")
            if symbol not in policy.allowed_symbols:
                raise ValueError("trigger symbol must be included in orderPolicy.allowedSymbols")
        return cls(
            symbol=symbol,
            proposal_creation_allowed=proposal_allowed,
            order_policy=policy,
            approval_chat_id=chat_id,
            approval_user_id=user_id,
            task_guidelines=str(process.llm_scope.get("taskGuidelines") or "").strip(),
        )


def _policy_from_action(value: Any) -> _OrderPolicy:
    if not isinstance(value, dict):
        raise ValueError("orderPolicy must be an object")
    allowed_symbols = tuple(_clean_symbols(value.get("allowedSymbols")))
    allowed_sides = tuple(_clean_terms_upper(value.get("allowedSides")))
    allowed_order_types = tuple(_clean_terms_upper(value.get("allowedOrderTypes")))
    if not allowed_symbols:
        raise ValueError("orderPolicy.allowedSymbols is required")
    if not allowed_sides:
        raise ValueError("orderPolicy.allowedSides is required")
    if not allowed_order_types:
        raise ValueError("orderPolicy.allowedOrderTypes is required")
    max_quantity = _optional_decimal(value.get("maxQuantity"))
    max_notional = _optional_decimal(value.get("maxNotionalAmount"))
    currency = _optional_text(value.get("notionalCurrency"))
    if max_quantity is None and max_notional is None:
        raise ValueError("orderPolicy requires maxQuantity or maxNotionalAmount")
    if max_quantity is not None and max_quantity <= 0:
        raise ValueError("orderPolicy.maxQuantity must be positive")
    if max_notional is not None and max_notional <= 0:
        raise ValueError("orderPolicy.maxNotionalAmount must be positive")
    if max_notional is not None and not currency:
        raise ValueError("orderPolicy.notionalCurrency is required with maxNotionalAmount")
    return _OrderPolicy(
        allowed_symbols=allowed_symbols,
        allowed_sides=allowed_sides,
        allowed_order_types=allowed_order_types,
        max_quantity=max_quantity,
        max_notional_amount=max_notional,
        notional_currency=currency.upper() if currency else None,
        allow_extended_hours=_bool(value.get("allowExtendedHours", False)),
    )


def _policy_rejection(order: TradeSetupProposedOrder, policy: _OrderPolicy | None) -> str | None:
    if policy is None:
        return "missing_order_policy"
    if order.ticker not in policy.allowed_symbols:
        return f"ticker {order.ticker} is outside allowed symbols"
    if order.side.value not in policy.allowed_sides:
        return f"side {order.side.value} is outside allowed sides"
    if order.order_type.value not in policy.allowed_order_types:
        return f"order type {order.order_type.value} is outside allowed order types"
    if order.extended_hours and not policy.allow_extended_hours:
        return "extended hours are not allowed"
    has_quantity = order.quantity is not None
    has_notional = order.notional_amount is not None
    if has_quantity == has_notional:
        return "provide exactly one of quantity or notionalAmount"
    if has_quantity:
        assert order.quantity is not None
        if order.quantity <= 0:
            return "quantity must be positive"
        if policy.max_quantity is None:
            return "quantity order requires maxQuantity policy"
        if order.quantity > policy.max_quantity:
            return f"quantity {order.quantity} exceeds maxQuantity {policy.max_quantity}"
    if has_notional:
        assert order.notional_amount is not None
        if order.notional_amount <= 0:
            return "notionalAmount must be positive"
        if policy.max_notional_amount is None:
            return "notional order requires maxNotionalAmount policy"
        if order.notional_amount > policy.max_notional_amount:
            return (
                f"notionalAmount {order.notional_amount} exceeds "
                f"maxNotionalAmount {policy.max_notional_amount}"
            )
        if policy.notional_currency and (
            str(order.notional_currency or "").strip().upper() != policy.notional_currency
        ):
            return f"notionalCurrency must be {policy.notional_currency}"
    return None


def _metadata(
    spec: _TradeSetupProcessSpec,
    analysis: TradeSetupAnalysis,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        **spec.base_metadata,
        "analysis": analysis.model_dump(by_alias=True, mode="json"),
        "evidence": evidence,
        "caveats": [
            *[str(item) for item in evidence.get("caveats", []) if str(item).strip()],
            *[str(item) for item in analysis.caveats if str(item).strip()],
        ],
    }


def _guidance(
    process: ScheduledProcess,
    spec: _TradeSetupProcessSpec,
    evidence: dict[str, Any],
) -> str:
    payload = {
        "purpose": "Scheduled trade setup analysis after deterministic trigger match.",
        "processId": process.process_id,
        "title": process.title,
        "symbol": spec.symbol,
        "proposalCreationAllowed": spec.proposal_creation_allowed,
        "orderPolicy": spec.order_policy.model_dump() if spec.order_policy else None,
        "taskGuidelines": spec.task_guidelines,
        "evidence": evidence,
        "constraints": [
            "The scheduler cannot submit broker orders.",
            "Only propose order terms inside the configured order policy.",
            "If setup quality is weak or ambiguous, set shouldProposeOrder=false.",
            "State risks and caveats compactly.",
            "noBrokerActionConfigured must be true.",
        ],
    }
    return _json_preview(payload, max_chars=18_000)


def _order_intent_payload(order: TradeSetupProposedOrder) -> dict[str, Any]:
    return order.model_dump(by_alias=True, exclude_none=True, mode="json")


def _order_summary(order: TradeSetupProposedOrder) -> str:
    size = (
        f"notional {order.notional_amount} {order.notional_currency}"
        if order.notional_amount is not None
        else f"quantity {order.quantity}"
    )
    parts = [order.side.value, order.order_type.value, order.ticker, size]
    if order.limit_price is not None:
        parts.append(f"limit {order.limit_price}")
    if order.stop_price is not None:
        parts.append(f"stop {order.stop_price}")
    parts.append(order.time_in_force.value)
    return " ".join(str(part) for part in parts)


def _pending_action_summary(
    *,
    process: ScheduledProcess,
    analysis: TradeSetupAnalysis,
    order: TradeSetupProposedOrder,
    policy: _OrderPolicy,
    proposal_id: str,
) -> str:
    return "\n".join(
        [
            f"Scheduled trade setup proposal: {process.title}",
            f"Proposal: {proposal_id}",
            f"Order: {_order_summary(order)}",
            f"Thesis: {analysis.thesis}",
            "Risks: " + "; ".join(analysis.risks[:4]) if analysis.risks else "Risks: none listed",
            "Risk caps: " + _policy_summary(policy),
        ]
    )


def _approval_text(
    *,
    process: ScheduledProcess,
    analysis: TradeSetupAnalysis,
    order: TradeSetupProposedOrder,
    policy: _OrderPolicy,
    proposal_id: str,
    pending_action_id: str,
) -> str:
    lines = [
        f"Scheduled trade setup: {process.title}",
        "",
        analysis.telegram_brief.strip(),
        "",
        f"Proposed order: {_order_summary(order)}",
        f"Proposal: {proposal_id}",
        f"Pending action: {pending_action_id}",
        f"Setup quality: {analysis.setup_quality.value}",
        f"Thesis: {analysis.thesis}",
        "Risks: " + ("; ".join(analysis.risks[:4]) if analysis.risks else "none listed"),
        "Risk caps applied: " + _policy_summary(policy),
        "",
        "Nothing has been executed yet.",
        "Approve or reject with the Telegram buttons below.",
    ]
    return "\n".join(lines)


def _approval_payload(*, action_id: str, proposal_id: str, text: str) -> dict[str, object]:
    return {
        "actionId": action_id,
        "proposalId": proposal_id,
        "text": text,
        "approveCallbackData": f"pa:approve:{action_id}",
        "rejectCallbackData": f"pa:reject:{action_id}",
    }


def _render_non_proposal_notification(
    process: ScheduledProcess,
    analysis: TradeSetupAnalysis,
    evidence: dict[str, Any],
) -> str:
    caveats = [
        str(item)
        for item in [
            *analysis.caveats,
            *evidence.get("caveats", []),
        ]
        if str(item).strip()
    ]
    lines = [
        f"Trade setup monitor: {process.title}",
        "",
        analysis.telegram_brief.strip(),
        "",
        f"Setup quality: {analysis.setup_quality.value}",
        "No pending proposal was created.",
        "No broker action was configured.",
    ]
    if caveats:
        lines.append("Caveats: " + "; ".join(caveats[:4]))
    return "\n".join(lines)


def _policy_summary(policy: _OrderPolicy) -> str:
    parts = [
        "symbols=" + ",".join(policy.allowed_symbols),
        "sides=" + ",".join(policy.allowed_sides),
        "types=" + ",".join(policy.allowed_order_types),
    ]
    if policy.max_quantity is not None:
        parts.append(f"maxQuantity={policy.max_quantity}")
    if policy.max_notional_amount is not None:
        parts.append(f"maxNotional={policy.max_notional_amount} {policy.notional_currency}")
    parts.append(f"extendedHoursAllowed={policy.allow_extended_hours}")
    return "; ".join(parts)


def _skipped(*, code: str, message: str, metadata: dict[str, object]) -> ScheduledAdapterResult:
    return ScheduledAdapterResult(
        status=ScheduledRunStatus.SKIPPED,
        matched=False,
        output_summary=message,
        code=code,
        message=message,
        metadata=dict(metadata),
    )


def _failed_invalid_spec(exc: Exception) -> ScheduledAdapterResult:
    return ScheduledAdapterResult(
        status=ScheduledRunStatus.FAILED,
        code="invalid_trade_setup_monitor_spec",
        message=f"Invalid trade setup monitor spec: {exc}.",
        metadata={"error": str(exc), "errorType": exc.__class__.__name__},
    )


def _model_payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return {"available": True, "data": value.model_dump(mode="json")}
    if hasattr(value, "__dict__"):
        return {"available": True, "data": _compact_payload(value.__dict__)}
    return {"available": True, "data": _compact_payload(value)}


def _compact_payload(value: Any, *, max_chars: int = 8_000) -> Any:
    rendered = _json_preview(value, max_chars=max_chars)
    try:
        import json

        return json.loads(rendered)
    except Exception:
        return rendered


def _json_preview(value: Any, *, max_chars: int) -> str:
    import json

    rendered = json.dumps(value, default=str, ensure_ascii=False)
    if len(rendered) <= max_chars:
        return rendered
    return rendered[:max_chars] + "...[truncated]"


def _clean_symbols(value: Any) -> list[str]:
    return _dedupe(str(item or "").strip().upper() for item in _list_value(value))


def _clean_terms_upper(value: Any) -> list[str]:
    return _dedupe(str(item or "").strip().upper() for item in _list_value(value))


def _dedupe(values) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _list_value(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None or not str(value).strip():
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("decimal-compatible value is required") from exc


def _optional_int(value: Any) -> int | None:
    if value is None or not str(value).strip():
        return None
    try:
        return int(str(value).strip())
    except ValueError as exc:
        raise ValueError("integer-compatible value is required") from exc


def _optional_text(value: Any) -> str | None:
    raw = str(value or "").strip()
    return raw or None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    raw = str(value or "").strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off", ""}:
        return False
    return bool(value)


def _notification_enabled(process: ScheduledProcess) -> bool:
    return bool(process.notification.get("enabled", True))
