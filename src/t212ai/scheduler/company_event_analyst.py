"""LLM-assisted company-event scheduler adapter."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from t212ai.agent.intents import AgentIntent, IntentKind
from t212ai.agent.planner import TaskComplexity
from t212ai.agent.schemas import AgentRequest, AgentResponse
from t212ai.agent.structured import StructuredAgentOutputSynthesizer
from t212ai.capabilities import (
    BrokerReadService,
    DisclosureService,
    MarketDataService,
    SearchService,
)
from t212ai.genai.models import ToolResult
from t212ai.genai.tools.search_registry import SearchResultRegistry
from t212ai.market_signals import MarketSignalService

from .models import (
    ScheduledExecutionMode,
    ScheduledProcess,
    ScheduledProcessKind,
    ScheduledRunStatus,
    ScheduleType,
)
from .worker import ScheduledAdapterResult


class CompanyEventType(StrEnum):
    EARNINGS_REPORT = "earnings_report"
    GUIDANCE_UPDATE = "guidance_update"
    FILING = "filing"
    MAJOR_NEWS = "major_news"
    COMPANY_EVENT = "company_event"


class CompanyEventDirection(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class CompanyEventImpactHorizon(StrEnum):
    INTRADAY = "intraday"
    SHORT_TERM = "short_term"
    MEDIUM_TERM = "medium_term"
    LONG_TERM = "long_term"
    UNKNOWN = "unknown"


class CompanyEventAnalysis(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    symbol: str
    company_name: str | None = Field(default=None, alias="companyName")
    event_type: CompanyEventType = Field(alias="eventType")
    event_summary: str = Field(alias="eventSummary")
    thesis_impact: str = Field(alias="thesisImpact")
    direction: CompanyEventDirection = CompanyEventDirection.UNKNOWN
    impact_horizon: CompanyEventImpactHorizon = Field(
        default=CompanyEventImpactHorizon.UNKNOWN,
        alias="impactHorizon",
    )
    key_points: list[str] = Field(default_factory=list, alias="keyPoints")
    risks: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list, alias="sourceRefs")
    data_freshness: str = Field(default="unknown", alias="dataFreshness")
    market_context_summary: str = Field(default="", alias="marketContextSummary")
    telegram_brief: str = Field(alias="telegramBrief")
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

    @field_validator("event_summary", "thesis_impact", "telegram_brief")
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
class CompanyEventAnalystAdapter:
    company_agent: Any | None = None
    market_agent: Any | None = None
    market_data_service: MarketDataService | None = None
    disclosure_service: DisclosureService | None = None
    search_service: SearchService | None = None
    market_signal_service: MarketSignalService | None = None
    broker_read_service: BrokerReadService | None = None
    structured_synthesizer: StructuredAgentOutputSynthesizer | None = None

    def run(self, process: ScheduledProcess) -> ScheduledAdapterResult:
        try:
            spec = _CompanyEventProcessSpec.from_process(process)
        except Exception as exc:
            return ScheduledAdapterResult(
                status=ScheduledRunStatus.FAILED,
                code="invalid_company_event_analyst_spec",
                message=f"Invalid company-event analyst spec: {exc}.",
                metadata={"error": str(exc), "errorType": exc.__class__.__name__},
            )
        if self.company_agent is None:
            return ScheduledAdapterResult(
                status=ScheduledRunStatus.SKIPPED,
                code="llm_unavailable",
                message="Company-event analysis requires a configured company analyst/LLM.",
                metadata={"symbol": spec.symbol, "eventType": spec.event_type.value},
            )

        evidence = self._build_evidence(process, spec)
        market_response = self._optional_market_context(process, spec, evidence)
        company_response = self._run_company_agent(process, spec, evidence, market_response)
        try:
            analysis = self._synthesize_analysis(
                process=process,
                spec=spec,
                evidence=evidence,
                market_response=market_response,
                company_response=company_response,
            )
        except Exception as exc:
            return ScheduledAdapterResult(
                status=ScheduledRunStatus.FAILED,
                code="company_event_analysis_failed",
                message=f"Company-event structured analysis failed: {exc}.",
                metadata={
                    "symbol": spec.symbol,
                    "eventType": spec.event_type.value,
                    "evidence": evidence,
                    "error": str(exc),
                    "errorType": exc.__class__.__name__,
                },
            )

        analysis = analysis.model_copy(
            update={
                "symbol": spec.symbol,
                "event_type": spec.event_type,
                "no_broker_action_configured": True,
            }
        )
        notification_message = (
            _render_notification(process, analysis, evidence)
            if _notification_enabled(process)
            else None
        )
        metadata = {
            "symbol": spec.symbol,
            "eventType": spec.event_type.value,
            "analysis": analysis.model_dump(by_alias=True, mode="json"),
            "evidence": evidence,
            "sourceRefs": analysis.source_refs,
            "caveats": evidence.get("caveats", []),
        }
        return ScheduledAdapterResult(
            status=ScheduledRunStatus.COMPLETED,
            matched=True,
            code="company_event_analysis_completed",
            message=f"Completed company-event analysis for {spec.symbol}.",
            output_summary=analysis.telegram_brief,
            metadata=metadata,
            notification_message=notification_message,
            notification_metadata={
                "symbol": spec.symbol,
                "eventType": spec.event_type.value,
                "direction": analysis.direction.value,
                "impactHorizon": analysis.impact_horizon.value,
            },
        )

    def _build_evidence(
        self,
        process: ScheduledProcess,
        spec: "_CompanyEventProcessSpec",
    ) -> dict[str, Any]:
        caveats: list[str] = []
        evidence: dict[str, Any] = {
            "processId": process.process_id,
            "title": process.title,
            "symbol": spec.symbol,
            "eventType": spec.event_type.value,
            "taskGuidelines": spec.task_guidelines,
            "caveats": caveats,
        }
        evidence["marketData"] = self._market_data_evidence(spec, caveats)
        evidence["disclosure"] = self._disclosure_evidence(spec, caveats)
        evidence["marketSignals"] = self._market_signal_evidence(spec, caveats)
        evidence["search"] = self._search_evidence(process, spec, caveats)
        if self.broker_read_service is not None:
            evidence["brokerContext"] = {
                "available": True,
                "note": "Broker read service is configured but not used for notify-only company-event analysis.",
            }
        return evidence

    def _market_data_evidence(
        self,
        spec: "_CompanyEventProcessSpec",
        caveats: list[str],
    ) -> dict[str, Any]:
        if self.market_data_service is None:
            caveats.append("Market data service is not configured.")
            return {"available": False}
        try:
            result = self.market_data_service.get_market_snapshot(
                [spec.symbol],
                period=spec.market_period,
                interval="1d",
            )
        except Exception as exc:
            caveats.append(f"Market data failed: {exc}.")
            return {"available": False, "error": str(exc), "errorType": exc.__class__.__name__}
        return _tool_result_payload(result)

    def _disclosure_evidence(
        self,
        spec: "_CompanyEventProcessSpec",
        caveats: list[str],
    ) -> dict[str, Any]:
        if self.disclosure_service is None:
            caveats.append("Disclosure service is not configured.")
            return {"available": False}
        try:
            result = self.disclosure_service.get_company_disclosure_snapshot(
                spec.symbol,
                since_days=spec.disclosure_since_days,
                limit=12,
            )
        except Exception as exc:
            caveats.append(f"Disclosure lookup failed: {exc}.")
            return {"available": False, "error": str(exc), "errorType": exc.__class__.__name__}
        return _model_payload(result)

    def _market_signal_evidence(
        self,
        spec: "_CompanyEventProcessSpec",
        caveats: list[str],
    ) -> dict[str, Any]:
        if self.market_signal_service is None:
            caveats.append("Market signal memory is not configured.")
            return {"available": False, "matches": []}
        try:
            matches = self.market_signal_service.search_signals(
                symbols=[spec.symbol],
                limit=5,
            )
        except Exception as exc:
            caveats.append(f"Market signal search failed: {exc}.")
            return {"available": False, "error": str(exc), "errorType": exc.__class__.__name__}
        return {
            "available": True,
            "matches": [_model_payload(match) for match in matches],
        }

    def _search_evidence(
        self,
        process: ScheduledProcess,
        spec: "_CompanyEventProcessSpec",
        caveats: list[str],
    ) -> dict[str, Any]:
        if self.search_service is None:
            caveats.append("Search service is not configured.")
            return {"available": False}
        query = spec.search_query or _default_search_query(spec)
        try:
            result = self.search_service.search(
                query=query,
                categories="general,news",
                time_range=spec.search_time_range,
                max_results=6,
                scrape_results=True,
                scrape_top_n=2,
                include_scraped_text=False,
                include_scraped_images=False,
                runtime=SearchResultRegistry(prefix=f"{process.process_id}_url"),
            )
        except Exception as exc:
            caveats.append(f"Search failed: {exc}.")
            return {"available": False, "query": query, "error": str(exc)}
        payload = _tool_result_payload(result)
        payload["query"] = query
        return payload

    def _optional_market_context(
        self,
        process: ScheduledProcess,
        spec: "_CompanyEventProcessSpec",
        evidence: dict[str, Any],
    ) -> AgentResponse | None:
        if not spec.include_market_analyst:
            return None
        if self.market_agent is None:
            evidence.setdefault("caveats", []).append("Market analyst is not configured.")
            return None
        request = AgentRequest(
            user_message=(
                f"Provide supporting market context for {spec.symbol} around "
                f"{spec.event_type.value}. Do not recommend or prepare broker actions."
            ),
            trigger_type="scheduler",
            orchestrator_guidance=_guidance(process, spec, evidence, market_context=True),
            metadata={"process_id": process.process_id, "scheduler_kind": process.kind.value},
        )
        return self.market_agent.handle(
            request,
            intent=AgentIntent(kind=IntentKind.UNKNOWN, entities={"domain": "market"}),
            task_complexity=TaskComplexity.COMPLEX,
        )

    def _run_company_agent(
        self,
        process: ScheduledProcess,
        spec: "_CompanyEventProcessSpec",
        evidence: dict[str, Any],
        market_response: AgentResponse | None,
    ) -> AgentResponse:
        request = AgentRequest(
            user_message=(
                f"Analyze {spec.symbol} for scheduled company-event research: "
                f"{spec.event_type.value}."
            ),
            trigger_type="scheduler",
            orchestrator_guidance=_guidance(
                process,
                spec,
                evidence,
                market_response=market_response,
            ),
            metadata={"process_id": process.process_id, "scheduler_kind": process.kind.value},
        )
        return self.company_agent.handle(
            request,
            intent=AgentIntent(
                kind=IntentKind.ANALYZE_INSTRUMENT,
                entities={"ticker": spec.symbol, "event_type": spec.event_type.value},
            ),
            task_complexity=TaskComplexity.COMPLEX,
        )

    def _synthesize_analysis(
        self,
        *,
        process: ScheduledProcess,
        spec: "_CompanyEventProcessSpec",
        evidence: dict[str, Any],
        market_response: AgentResponse | None,
        company_response: AgentResponse,
    ) -> CompanyEventAnalysis:
        synthesizer = self.structured_synthesizer
        if synthesizer is None:
            synthesizer = StructuredAgentOutputSynthesizer(self.company_agent.reasoner.genai)
        result = synthesizer.synthesize(
            CompanyEventAnalysis,
            source_agent_name=getattr(self.company_agent, "name", "company_analyst"),
            source_response=company_response,
            user_request=f"{process.title}: analyze {spec.symbol} {spec.event_type.value}",
            instructions=(
                "Return a compact company-event analysis for a scheduled Telegram "
                "brief. Use the configured event type. Include caveats for missing "
                "optional evidence. noBrokerActionConfigured must be true."
            ),
            context={
                "process": process.model_dump(by_alias=True, mode="json"),
                "evidence": evidence,
                "marketAgentResponse": (
                    market_response.model_dump(mode="json") if market_response else None
                ),
            },
            task_complexity=TaskComplexity.COMPLEX,
        )
        return CompanyEventAnalysis.model_validate(result)


@dataclass(frozen=True, slots=True)
class _CompanyEventProcessSpec:
    symbol: str
    event_type: CompanyEventType
    task_guidelines: str
    include_market_analyst: bool
    disclosure_since_days: int
    search_time_range: str
    market_period: str
    search_query: str | None

    @classmethod
    def from_process(cls, process: ScheduledProcess) -> "_CompanyEventProcessSpec":
        if process.kind != ScheduledProcessKind.COMPANY_EVENT_ANALYST:
            raise ValueError("kind must be company_event_analyst")
        if process.execution_mode != ScheduledExecutionMode.LLM_ASSISTED:
            raise ValueError("execution_mode must be llm_assisted")
        if process.schedule.type not in {ScheduleType.ONE_SHOT, ScheduleType.RECURRING}:
            raise ValueError("schedule.type must be one_shot or recurring")
        if process.safety.broker_actions_allowed:
            raise ValueError("brokerActionsAllowed must be false")
        action_type = str(process.action.get("type") or "").strip().lower()
        if action_type and action_type != "notify_only":
            raise ValueError("company_event_analyst supports notify_only action only")
        symbol = _symbol_from_process(process)
        event_type = _event_type_from_process(process)
        return cls(
            symbol=symbol,
            event_type=event_type,
            task_guidelines=str(process.llm_scope.get("taskGuidelines") or "").strip(),
            include_market_analyst=bool(process.llm_scope.get("includeMarketAnalyst", False)),
            disclosure_since_days=_positive_int(
                process.inputs.get("disclosureSinceDays"),
                default=30,
            ),
            search_time_range=str(process.inputs.get("searchTimeRange") or "week").strip()
            or "week",
            market_period=str(process.inputs.get("marketPeriod") or "1mo").strip() or "1mo",
            search_query=_optional_text(process.inputs.get("searchQuery")),
        )


def _symbol_from_process(process: ScheduledProcess) -> str:
    raw = process.inputs.get("symbol") or process.trigger.get("symbol")
    if raw is None:
        symbols = process.inputs.get("symbols")
        if isinstance(symbols, list) and symbols:
            raw = symbols[0]
    symbol = str(raw or "").strip().upper()
    if not symbol:
        raise ValueError("symbol is required")
    return symbol


def _event_type_from_process(process: ScheduledProcess) -> CompanyEventType:
    raw = (
        process.inputs.get("eventType")
        or process.trigger.get("eventType")
        or CompanyEventType.COMPANY_EVENT.value
    )
    try:
        return CompanyEventType(str(raw).strip())
    except ValueError as exc:
        raise ValueError(f"unsupported eventType '{raw}'") from exc


def _positive_int(value: Any, *, default: int) -> int:
    if value is None or not str(value).strip():
        return default
    try:
        parsed = int(str(value).strip())
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _optional_text(value: Any) -> str | None:
    raw = str(value or "").strip()
    return raw or None


def _default_search_query(spec: _CompanyEventProcessSpec) -> str:
    label = spec.event_type.value.replace("_", " ")
    return f"{spec.symbol} {label} earnings guidance filing news"


def _guidance(
    process: ScheduledProcess,
    spec: _CompanyEventProcessSpec,
    evidence: dict[str, Any],
    *,
    market_context: bool = False,
    market_response: AgentResponse | None = None,
) -> str:
    purpose = (
        "Supporting market context only."
        if market_context
        else "Primary scheduled company-event analysis."
    )
    payload = {
        "purpose": purpose,
        "processId": process.process_id,
        "title": process.title,
        "symbol": spec.symbol,
        "eventType": spec.event_type.value,
        "taskGuidelines": spec.task_guidelines,
        "evidence": evidence,
        "marketResponseSummary": market_response.final_answer if market_response else None,
        "constraints": [
            "Use only the provided/configured evidence and explicit uncertainty.",
            "Treat market signals as advisory context.",
            "Do not configure, propose, submit, or imply broker actions.",
            "Return concise trading-relevant impact, risks, and source limitations.",
        ],
    }
    return _json_preview(payload, max_chars=18_000)


def _tool_result_payload(result: Any) -> dict[str, Any]:
    if isinstance(result, ToolResult):
        return {
            "available": result.status == "ok",
            "status": result.status,
            "output": result.output,
            "data": _compact_payload(result.data),
            "error": result.error.model_dump(mode="json") if result.error else None,
            "meta": result.meta,
        }
    return _model_payload(result)


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


def _notification_enabled(process: ScheduledProcess) -> bool:
    return bool(process.notification.get("enabled", True))


def _render_notification(
    process: ScheduledProcess,
    analysis: CompanyEventAnalysis,
    evidence: dict[str, Any],
) -> str:
    caveats = [str(item) for item in evidence.get("caveats", []) if str(item).strip()]
    lines = [
        f"{process.title}",
        f"{analysis.symbol} {analysis.event_type.value.replace('_', ' ')} analysis",
        "",
        analysis.telegram_brief.strip(),
        "",
        f"Direction: {analysis.direction.value}",
        f"Impact horizon: {analysis.impact_horizon.value}",
        f"No broker action was configured.",
    ]
    if analysis.source_refs:
        lines.append("Sources: " + "; ".join(analysis.source_refs[:5]))
    if caveats:
        lines.append("Caveats: " + "; ".join(caveats[:4]))
    return "\n".join(lines)
