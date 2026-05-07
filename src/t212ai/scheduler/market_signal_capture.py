"""LLM-assisted market-signal capture scheduler adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from t212ai.agent.intents import AgentIntent, IntentKind
from t212ai.agent.planner import TaskComplexity
from t212ai.agent.schemas import AgentRequest, AgentResponse
from t212ai.agent.structured import StructuredAgentOutputSynthesizer
from t212ai.capabilities import (
    CommunityResearchService,
    DisclosureService,
    MarketDataService,
    SearchService,
)
from t212ai.genai.models import ToolResult
from t212ai.genai.tools.search_registry import SearchResultRegistry
from t212ai.market_signals import (
    MarketSignal,
    MarketSignalDirection,
    MarketSignalHorizon,
    MarketSignalService,
    MarketSignalSource,
    MarketSignalType,
)

from .models import (
    ScheduledExecutionMode,
    ScheduledProcess,
    ScheduledProcessKind,
    ScheduledRunStatus,
    ScheduleType,
)
from .worker import ScheduledAdapterResult


class CapturedMarketSignal(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    title: str
    summary: str
    symbols: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    signal_type: MarketSignalType = Field(default=MarketSignalType.OTHER, alias="signalType")
    direction: MarketSignalDirection = MarketSignalDirection.UNKNOWN
    impact_horizon: MarketSignalHorizon = Field(
        default=MarketSignalHorizon.UNKNOWN,
        alias="impactHorizon",
    )
    source_refs: list[str] = Field(default_factory=list, alias="sourceRefs")
    expires_at: datetime | None = Field(default=None, alias="expiresAt")

    @field_validator("title", "summary")
    @classmethod
    def _required_text(cls, value: str) -> str:
        resolved = str(value or "").strip()
        if not resolved:
            raise ValueError("field is required and cannot be empty")
        return resolved


class MarketSignalCaptureAnalysis(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    scan_summary: str = Field(alias="scanSummary")
    proposed_signals: list[CapturedMarketSignal] = Field(
        default_factory=list,
        alias="proposedSignals",
    )
    rejected_items: list[str] = Field(default_factory=list, alias="rejectedItems")
    caveats: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list, alias="sourceRefs")
    data_freshness: str = Field(default="unknown", alias="dataFreshness")
    telegram_brief: str = Field(alias="telegramBrief")
    no_broker_action_configured: bool = Field(
        default=True,
        alias="noBrokerActionConfigured",
    )

    @field_validator("scan_summary", "telegram_brief")
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
class MarketSignalCaptureAdapter:
    market_agent: Any | None = None
    market_signal_service: MarketSignalService | None = None
    search_service: SearchService | None = None
    community_research_service: CommunityResearchService | None = None
    disclosure_service: DisclosureService | None = None
    market_data_service: MarketDataService | None = None
    structured_synthesizer: StructuredAgentOutputSynthesizer | None = None

    def run(self, process: ScheduledProcess) -> ScheduledAdapterResult:
        try:
            spec = _MarketSignalCaptureProcessSpec.from_process(process)
        except Exception as exc:
            return ScheduledAdapterResult(
                status=ScheduledRunStatus.FAILED,
                code="invalid_market_signal_capture_spec",
                message=f"Invalid market-signal capture spec: {exc}.",
                metadata={"error": str(exc), "errorType": exc.__class__.__name__},
            )
        if self.market_signal_service is None:
            return ScheduledAdapterResult(
                status=ScheduledRunStatus.SKIPPED,
                code="market_signal_memory_unavailable",
                message="Market-signal capture requires configured market signal memory.",
                metadata=spec.base_metadata,
            )
        if self.market_agent is None:
            return ScheduledAdapterResult(
                status=ScheduledRunStatus.SKIPPED,
                code="llm_unavailable",
                message="Market-signal capture requires a configured market analyst/LLM.",
                metadata=spec.base_metadata,
            )

        evidence = self._build_evidence(process, spec)
        if not _has_usable_research_evidence(evidence):
            return ScheduledAdapterResult(
                status=ScheduledRunStatus.SKIPPED,
                code="evidence_unavailable",
                message=(
                    "Market-signal capture requires usable search, community, or "
                    "disclosure evidence before calling the LLM."
                ),
                metadata={
                    **spec.base_metadata,
                    "evidence": evidence,
                    "caveats": evidence.get("caveats", []),
                },
            )

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
                code="market_signal_capture_analysis_failed",
                message=f"Market-signal capture structured analysis failed: {exc}.",
                metadata={
                    **spec.base_metadata,
                    "evidence": evidence,
                    "error": str(exc),
                    "errorType": exc.__class__.__name__,
                },
            )

        created, skipped = self._write_signals(spec, analysis)
        caveats = [
            *[str(item) for item in evidence.get("caveats", []) if str(item).strip()],
            *[str(item) for item in analysis.caveats if str(item).strip()],
        ]
        metadata = {
            **spec.base_metadata,
            "analysis": analysis.model_dump(by_alias=True, mode="json"),
            "evidence": evidence,
            "createdSignals": [
                signal.model_dump(by_alias=True, mode="json") for signal in created
            ],
            "skippedCandidates": skipped,
            "sourceRefs": _dedupe([*analysis.source_refs, *_source_refs_from_signals(created)]),
            "caveats": _dedupe(caveats),
        }
        matched = bool(created)
        code = "market_signals_created" if matched else "no_durable_market_signals"
        message = (
            f"Created {len(created)} market signal(s) from scheduled capture."
            if matched
            else "Market-signal capture completed without new durable signals."
        )
        notification_message = (
            _render_notification(process, spec, analysis, created, metadata["caveats"])
            if matched and _notification_enabled(process)
            else None
        )
        return ScheduledAdapterResult(
            status=ScheduledRunStatus.COMPLETED,
            matched=matched,
            code=code,
            message=message,
            output_summary=analysis.telegram_brief if matched else analysis.scan_summary,
            metadata=metadata,
            notification_message=notification_message,
            notification_metadata={
                "createdSignalCount": len(created),
                "scope": spec.scope_label,
            },
        )

    def _build_evidence(
        self,
        process: ScheduledProcess,
        spec: "_MarketSignalCaptureProcessSpec",
    ) -> dict[str, Any]:
        caveats: list[str] = []
        evidence: dict[str, Any] = {
            "processId": process.process_id,
            "title": process.title,
            "scope": spec.scope_label,
            "query": spec.query,
            "symbols": spec.symbols,
            "sectors": spec.sectors,
            "tags": spec.tags,
            "taskGuidelines": spec.task_guidelines,
            "caveats": caveats,
        }
        evidence["search"] = self._search_evidence(process, spec, caveats)
        evidence["community"] = self._community_evidence(spec, caveats)
        evidence["disclosure"] = self._disclosure_evidence(spec, caveats)
        evidence["marketData"] = self._market_data_evidence(spec, caveats)
        return evidence

    def _search_evidence(
        self,
        process: ScheduledProcess,
        spec: "_MarketSignalCaptureProcessSpec",
        caveats: list[str],
    ) -> dict[str, Any]:
        if self.search_service is None:
            caveats.append("Search service is not configured.")
            return {"available": False}
        query = spec.query or _default_search_query(spec)
        try:
            result = self.search_service.search(
                query=query,
                categories="general,news",
                time_range=spec.search_time_range,
                max_results=8,
                scrape_results=True,
                scrape_top_n=3,
                include_scraped_text=False,
                include_scraped_images=False,
                runtime=SearchResultRegistry(prefix=f"{process.process_id}_capture_url"),
            )
        except Exception as exc:
            caveats.append(f"Search failed: {exc}.")
            return {"available": False, "query": query, "error": str(exc)}
        payload = _tool_result_payload(result)
        payload["query"] = query
        return payload

    def _community_evidence(
        self,
        spec: "_MarketSignalCaptureProcessSpec",
        caveats: list[str],
    ) -> dict[str, Any]:
        if self.community_research_service is None:
            caveats.append("Community research service is not configured.")
            return {"available": False}
        try:
            if spec.symbols and hasattr(self.community_research_service, "scan_company_discussion"):
                result = self.community_research_service.scan_company_discussion(
                    spec.symbols[0],
                    time=spec.community_time_range,
                    max_results=12,
                )
            else:
                result = self.community_research_service.search_posts(
                    spec.query or _default_search_query(spec),
                    time=spec.community_time_range,
                    limit=10,
                )
        except Exception as exc:
            caveats.append(f"Community research failed: {exc}.")
            return {"available": False, "error": str(exc), "errorType": exc.__class__.__name__}
        return _model_payload(result)

    def _disclosure_evidence(
        self,
        spec: "_MarketSignalCaptureProcessSpec",
        caveats: list[str],
    ) -> dict[str, Any]:
        if self.disclosure_service is None:
            caveats.append("Disclosure service is not configured.")
            return {"available": False}
        if not spec.symbols:
            caveats.append("Disclosure evidence requires at least one symbol.")
            return {"available": False}
        snapshots: list[dict[str, Any]] = []
        for symbol in spec.symbols[:3]:
            try:
                result = self.disclosure_service.get_company_disclosure_snapshot(
                    symbol,
                    since_days=spec.disclosure_since_days,
                    limit=8,
                )
            except Exception as exc:
                caveats.append(f"Disclosure lookup failed for {symbol}: {exc}.")
                snapshots.append(
                    {
                        "symbol": symbol,
                        "available": False,
                        "error": str(exc),
                        "errorType": exc.__class__.__name__,
                    }
                )
                continue
            payload = _model_payload(result)
            payload["symbol"] = symbol
            snapshots.append(payload)
        available = any(_payload_available(item) for item in snapshots)
        return {"available": available, "snapshots": snapshots}

    def _market_data_evidence(
        self,
        spec: "_MarketSignalCaptureProcessSpec",
        caveats: list[str],
    ) -> dict[str, Any]:
        if self.market_data_service is None:
            caveats.append("Market data service is not configured.")
            return {"available": False}
        if not spec.symbols:
            caveats.append("Market data evidence requires at least one symbol.")
            return {"available": False}
        try:
            result = self.market_data_service.get_market_snapshot(
                spec.symbols[:5],
                period=spec.market_period,
                interval="1d",
            )
        except Exception as exc:
            caveats.append(f"Market data failed: {exc}.")
            return {"available": False, "error": str(exc), "errorType": exc.__class__.__name__}
        return _tool_result_payload(result)

    def _run_market_agent(
        self,
        process: ScheduledProcess,
        spec: "_MarketSignalCaptureProcessSpec",
        evidence: dict[str, Any],
    ) -> AgentResponse:
        request = AgentRequest(
            user_message=(
                f"Capture durable market signals for scheduled scope: {spec.scope_label}."
            ),
            trigger_type="scheduler",
            orchestrator_guidance=_guidance(process, spec, evidence),
            metadata={"process_id": process.process_id, "scheduler_kind": process.kind.value},
        )
        return self.market_agent.handle(
            request,
            intent=AgentIntent(
                kind=IntentKind.UNKNOWN,
                entities={"domain": "market_signal_capture", "scope": spec.scope_label},
            ),
            task_complexity=TaskComplexity.COMPLEX,
        )

    def _synthesize_analysis(
        self,
        *,
        process: ScheduledProcess,
        spec: "_MarketSignalCaptureProcessSpec",
        evidence: dict[str, Any],
        market_response: AgentResponse,
    ) -> MarketSignalCaptureAnalysis:
        synthesizer = self.structured_synthesizer
        if synthesizer is None:
            synthesizer = StructuredAgentOutputSynthesizer(self.market_agent.reasoner.genai)
        result = synthesizer.synthesize(
            MarketSignalCaptureAnalysis,
            source_agent_name=getattr(self.market_agent, "name", "market_analyst"),
            source_response=market_response,
            user_request=f"{process.title}: capture durable market signals",
            instructions=(
                "Return compact durable market signals for memory. Include at most "
                f"{spec.max_signals} proposed signals. Each signal must be concise, "
                "future-impact-oriented, advisory only, and backed by source refs "
                "when available. Reject noisy raw search dumps. "
                "noBrokerActionConfigured must be true."
            ),
            context={
                "process": process.model_dump(by_alias=True, mode="json"),
                "evidence": evidence,
                "maxSignals": spec.max_signals,
            },
            task_complexity=TaskComplexity.COMPLEX,
        )
        return MarketSignalCaptureAnalysis.model_validate(result)

    def _write_signals(
        self,
        spec: "_MarketSignalCaptureProcessSpec",
        analysis: MarketSignalCaptureAnalysis,
    ) -> tuple[list[MarketSignal], list[dict[str, Any]]]:
        created: list[MarketSignal] = []
        skipped: list[dict[str, Any]] = []
        for candidate in analysis.proposed_signals:
            if len(created) >= spec.max_signals:
                skipped.append(
                    {
                        "title": candidate.title,
                        "reason": "max_signals_reached",
                    }
                )
                continue
            if not (candidate.symbols or candidate.sectors or candidate.tags):
                skipped.append(
                    {
                        "title": candidate.title,
                        "reason": "missing_topical_fields",
                    }
                )
                continue
            duplicate_reason = _duplicate_reason(
                candidate,
                self.market_signal_service.search_signals(
                    symbols=candidate.symbols or None,
                    sectors=candidate.sectors or None,
                    tags=candidate.tags or None,
                    active_only=True,
                    include_expired=False,
                    limit=50,
                ),
            )
            if duplicate_reason:
                skipped.append(
                    {
                        "title": candidate.title,
                        "reason": duplicate_reason,
                    }
                )
                continue
            try:
                signal = self.market_signal_service.create_signal(
                    title=candidate.title,
                    summary=candidate.summary,
                    symbols=candidate.symbols,
                    sectors=candidate.sectors,
                    tags=candidate.tags,
                    signal_type=candidate.signal_type,
                    direction=candidate.direction,
                    impact_horizon=candidate.impact_horizon,
                    source=MarketSignalSource.SCHEDULED_JOB,
                    source_refs=candidate.source_refs or analysis.source_refs,
                    expires_at=_ensure_aware(candidate.expires_at)
                    if candidate.expires_at is not None
                    else None,
                )
            except Exception as exc:
                skipped.append(
                    {
                        "title": candidate.title,
                        "reason": "create_failed",
                        "error": str(exc),
                        "errorType": exc.__class__.__name__,
                    }
                )
                continue
            created.append(signal)
        return created, skipped


@dataclass(frozen=True, slots=True)
class _MarketSignalCaptureProcessSpec:
    query: str | None
    symbols: list[str]
    sectors: list[str]
    tags: list[str]
    max_signals: int
    search_time_range: str
    community_time_range: str
    market_period: str
    disclosure_since_days: int
    task_guidelines: str

    @property
    def scope_label(self) -> str:
        parts: list[str] = []
        if self.query:
            parts.append(f"query={self.query}")
        if self.symbols:
            parts.append("symbols=" + ",".join(self.symbols))
        if self.sectors:
            parts.append("sectors=" + ",".join(self.sectors))
        if self.tags:
            parts.append("tags=" + ",".join(self.tags))
        return "; ".join(parts) or "unspecified"

    @property
    def base_metadata(self) -> dict[str, object]:
        return {
            "query": self.query,
            "symbols": self.symbols,
            "sectors": self.sectors,
            "tags": self.tags,
            "maxSignals": self.max_signals,
        }

    @classmethod
    def from_process(cls, process: ScheduledProcess) -> "_MarketSignalCaptureProcessSpec":
        if process.kind != ScheduledProcessKind.MARKET_SIGNAL_CAPTURE:
            raise ValueError("kind must be market_signal_capture")
        if process.execution_mode != ScheduledExecutionMode.LLM_ASSISTED:
            raise ValueError("execution_mode must be llm_assisted")
        if process.schedule.type not in {ScheduleType.RECURRING, ScheduleType.POLLING}:
            raise ValueError("schedule.type must be recurring or polling")
        if process.safety.broker_actions_allowed:
            raise ValueError("brokerActionsAllowed must be false")
        action_type = str(process.action.get("type") or "").strip().lower()
        if action_type and action_type != "notify_only":
            raise ValueError("market_signal_capture supports notify_only action only")
        query = _optional_text(process.inputs.get("query") or process.trigger.get("query"))
        symbols = _clean_symbols(
            _list_value(process.inputs.get("symbols") or process.trigger.get("symbols"))
        )
        sectors = _clean_terms(
            _list_value(process.inputs.get("sectors") or process.trigger.get("sectors"))
        )
        tags = _clean_terms(
            _list_value(process.inputs.get("tags") or process.trigger.get("tags"))
        )
        if not (query or symbols or sectors or tags):
            raise ValueError("query, symbols, sectors, or tags are required")
        max_signals = _positive_int(process.inputs.get("maxSignals"), default=3)
        if max_signals < 1 or max_signals > 3:
            raise ValueError("maxSignals must be between 1 and 3")
        return cls(
            query=query,
            symbols=symbols,
            sectors=sectors,
            tags=tags,
            max_signals=max_signals,
            search_time_range=str(process.inputs.get("searchTimeRange") or "day").strip()
            or "day",
            community_time_range=str(process.inputs.get("communityTimeRange") or "week").strip()
            or "week",
            market_period=str(process.inputs.get("marketPeriod") or "1mo").strip() or "1mo",
            disclosure_since_days=_positive_int(
                process.inputs.get("disclosureSinceDays"),
                default=30,
            ),
            task_guidelines=str(process.llm_scope.get("taskGuidelines") or "").strip(),
        )


def _guidance(
    process: ScheduledProcess,
    spec: _MarketSignalCaptureProcessSpec,
    evidence: dict[str, Any],
) -> str:
    payload = {
        "purpose": "Scheduled market-signal capture into persistent advisory memory.",
        "processId": process.process_id,
        "title": process.title,
        "scope": spec.scope_label,
        "taskGuidelines": spec.task_guidelines,
        "maxSignals": spec.max_signals,
        "evidence": evidence,
        "constraints": [
            "Write only durable, future-useful market insights.",
            "Avoid raw search dumps and noisy restatements of headlines.",
            "Provide concise summaries, topical filters, caveats, and source refs.",
            "Market signals are advisory context, not fresh market data or broker state.",
            "Do not configure, propose, submit, or imply broker actions.",
        ],
    }
    return _json_preview(payload, max_chars=18_000)


def _default_search_query(spec: _MarketSignalCaptureProcessSpec) -> str:
    parts = [*spec.symbols, *spec.sectors, *spec.tags]
    if spec.query:
        parts.insert(0, spec.query)
    scope = " ".join(parts).strip() or "market"
    return f"{scope} market catalyst risk positioning news"


def _has_usable_research_evidence(evidence: dict[str, Any]) -> bool:
    return any(
        _payload_available(evidence.get(key))
        for key in ("search", "community", "disclosure")
    )


def _payload_available(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return bool(payload)
    if payload.get("available") is not True:
        return False
    if payload.get("status") == "error":
        return False
    data = payload.get("data")
    if data:
        return True
    for key in ("results", "matches", "snapshots", "output"):
        value = payload.get(key)
        if value:
            return True
    return bool(payload.get("output"))


def _duplicate_reason(
    candidate: CapturedMarketSignal,
    existing_matches: list[Any],
) -> str | None:
    candidate_title = _normalize_text(candidate.title)
    candidate_refs = set(_clean_refs(candidate.source_refs))
    candidate_summary_prefix = _summary_prefix(candidate.summary)
    candidate_topics = _topic_set(candidate.symbols, candidate.sectors, candidate.tags)
    for match in existing_matches:
        signal = getattr(match, "signal", match)
        if _normalize_text(signal.title) == candidate_title:
            return "duplicate_title"
        existing_refs = set(_clean_refs(signal.source_refs))
        if candidate_refs and candidate_refs.intersection(existing_refs):
            return "duplicate_source_ref"
        existing_topics = _topic_set(signal.symbols, signal.sectors, signal.tags)
        if (
            candidate_topics.intersection(existing_topics)
            and _summary_prefix(signal.summary) == candidate_summary_prefix
        ):
            return "duplicate_summary_topic"
    return None


def _topic_set(symbols: list[str], sectors: list[str], tags: list[str]) -> set[str]:
    return {
        *(f"symbol:{symbol}" for symbol in _clean_symbols(symbols)),
        *(f"sector:{sector}" for sector in _clean_terms(sectors)),
        *(f"tag:{tag}" for tag in _clean_terms(tags)),
    }


def _summary_prefix(value: str) -> str:
    return _normalize_text(value)[:160]


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


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


def _render_notification(
    process: ScheduledProcess,
    spec: _MarketSignalCaptureProcessSpec,
    analysis: MarketSignalCaptureAnalysis,
    created: list[MarketSignal],
    caveats: list[str],
) -> str:
    lines = [
        process.title,
        f"Market signal capture: {spec.scope_label}",
        "",
        analysis.telegram_brief.strip(),
        "",
        f"Created {len(created)} signal(s):",
    ]
    for signal in created:
        topics = []
        if signal.symbols:
            topics.append("symbols=" + ",".join(signal.symbols))
        if signal.sectors:
            topics.append("sectors=" + ",".join(signal.sectors))
        if signal.tags:
            topics.append("tags=" + ",".join(signal.tags))
        lines.append(
            f"- {signal.signal_id}: {signal.title} "
            f"({signal.direction.value}, {signal.impact_horizon.value}; "
            f"{'; '.join(topics) or 'no topics'})"
        )
    lines.append("No broker action was configured.")
    source_refs = _dedupe([*analysis.source_refs, *_source_refs_from_signals(created)])
    if source_refs:
        lines.append("Sources: " + "; ".join(source_refs[:5]))
    if caveats:
        lines.append("Caveats: " + "; ".join(caveats[:4]))
    return "\n".join(lines)


def _source_refs_from_signals(signals: list[MarketSignal]) -> list[str]:
    refs: list[str] = []
    for signal in signals:
        refs.extend(signal.source_refs)
    return refs


def _notification_enabled(process: ScheduledProcess) -> bool:
    return bool(process.notification.get("enabled", True))


def _positive_int(value: Any, *, default: int) -> int:
    if value is None or not str(value).strip():
        return default
    try:
        parsed = int(str(value).strip())
    except ValueError as exc:
        raise ValueError("integer value is required") from exc
    return parsed


def _list_value(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _optional_text(value: Any) -> str | None:
    raw = str(value or "").strip()
    return raw or None


def _clean_symbols(values: list[Any] | None) -> list[str]:
    return _dedupe(str(value or "").strip().upper() for value in values or [])


def _clean_terms(values: list[Any] | None) -> list[str]:
    return _dedupe(str(value or "").strip().lower().replace(" ", "_") for value in values or [])


def _clean_refs(values: list[Any] | None) -> list[str]:
    return _dedupe(str(value or "").strip() for value in values or [])


def _dedupe(values) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
