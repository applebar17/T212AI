"""Hybrid market-regime scheduler adapter."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from t212ai.agent.intents import AgentIntent, IntentKind
from t212ai.agent.planner import TaskComplexity
from t212ai.agent.schemas import AgentRequest, AgentResponse
from t212ai.agent.structured import StructuredAgentOutputSynthesizer
from t212ai.capabilities import MarketDataService, SearchService
from t212ai.genai.models import ToolResult
from t212ai.genai.tools.search_registry import SearchResultRegistry

from .models import (
    ScheduledExecutionMode,
    ScheduledProcess,
    ScheduledProcessKind,
    ScheduledRunStatus,
    ScheduleType,
)
from .worker import ScheduledAdapterResult


class MarketRegimeSeverity(StrEnum):
    ELEVATED = "elevated"
    STRESSED = "stressed"
    CRISIS = "crisis"
    UNKNOWN = "unknown"


class MarketRegimeAnalysis(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    proxy_symbol: str = Field(alias="proxySymbol")
    proxy_label: str = Field(alias="proxyLabel")
    trigger_summary: str = Field(alias="triggerSummary")
    severity: MarketRegimeSeverity = MarketRegimeSeverity.UNKNOWN
    regime_summary: str = Field(alias="regimeSummary")
    likely_drivers: list[str] = Field(default_factory=list, alias="likelyDrivers")
    market_impact: str = Field(default="", alias="marketImpact")
    watch_items: list[str] = Field(default_factory=list, alias="watchItems")
    source_refs: list[str] = Field(default_factory=list, alias="sourceRefs")
    caveats: list[str] = Field(default_factory=list)
    data_freshness: str = Field(default="unknown", alias="dataFreshness")
    telegram_brief: str = Field(alias="telegramBrief")
    no_broker_action_configured: bool = Field(
        default=True,
        alias="noBrokerActionConfigured",
    )

    @field_validator("proxy_symbol")
    @classmethod
    def _normalize_proxy_symbol(cls, value: str) -> str:
        resolved = str(value or "").strip().upper()
        if not resolved:
            raise ValueError("proxySymbol is required")
        return resolved

    @field_validator("proxy_label", "trigger_summary", "regime_summary", "telegram_brief")
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
class MarketRegimeMonitorAdapter:
    market_agent: Any | None = None
    market_data_service: MarketDataService | None = None
    search_service: SearchService | None = None
    structured_synthesizer: StructuredAgentOutputSynthesizer | None = None

    def run(self, process: ScheduledProcess) -> ScheduledAdapterResult:
        try:
            spec = _MarketRegimeProcessSpec.from_process(process)
        except Exception as exc:
            return ScheduledAdapterResult(
                status=ScheduledRunStatus.FAILED,
                code="invalid_market_regime_monitor_spec",
                message=f"Invalid market-regime monitor spec: {exc}.",
                metadata={"error": str(exc), "errorType": exc.__class__.__name__},
            )
        if self.market_data_service is None:
            return ScheduledAdapterResult(
                status=ScheduledRunStatus.SKIPPED,
                code="market_data_unavailable",
                message="Market-regime monitor requires a configured market-data service.",
                metadata=spec.base_metadata,
            )

        trigger_result = self._evaluate_trigger(spec)
        if trigger_result.status != ScheduledRunStatus.COMPLETED:
            return trigger_result
        if not trigger_result.matched:
            return trigger_result
        if self.market_agent is None:
            return ScheduledAdapterResult(
                status=ScheduledRunStatus.SKIPPED,
                code="llm_unavailable",
                message="Matched market-regime stress requires a configured market analyst/LLM.",
                metadata=dict(trigger_result.metadata),
            )

        evidence = self._build_matched_evidence(process, spec, trigger_result.metadata)
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
                code="market_regime_analysis_failed",
                message=f"Market-regime structured analysis failed: {exc}.",
                metadata={
                    "proxySymbol": spec.proxy_symbol,
                    "proxyLabel": spec.proxy_label,
                    "evidence": evidence,
                    "error": str(exc),
                    "errorType": exc.__class__.__name__,
                },
            )

        analysis = analysis.model_copy(
            update={
                "proxy_symbol": spec.proxy_symbol,
                "proxy_label": spec.proxy_label,
                "no_broker_action_configured": True,
            }
        )
        notification_message = (
            _render_notification(process, analysis, evidence)
            if _notification_enabled(process)
            else None
        )
        metadata = {
            "proxySymbol": spec.proxy_symbol,
            "proxyLabel": spec.proxy_label,
            "analysis": analysis.model_dump(by_alias=True, mode="json"),
            "evidence": evidence,
            "sourceRefs": analysis.source_refs,
            "caveats": evidence.get("caveats", []),
        }
        return ScheduledAdapterResult(
            status=ScheduledRunStatus.COMPLETED,
            matched=True,
            code="market_regime_analysis_completed",
            message=f"Completed market-regime analysis for {spec.proxy_symbol}.",
            output_summary=analysis.telegram_brief,
            metadata=metadata,
            notification_message=notification_message,
            notification_metadata={
                "proxySymbol": spec.proxy_symbol,
                "proxyLabel": spec.proxy_label,
                "severity": analysis.severity.value,
            },
        )

    def _evaluate_trigger(self, spec: "_MarketRegimeProcessSpec") -> ScheduledAdapterResult:
        try:
            quote_result = self.market_data_service.get_quote_snapshot([spec.proxy_symbol])
        except Exception as exc:
            return _skipped(
                code="market_data_error",
                message=f"Market-data quote lookup failed: {exc}.",
                metadata={**spec.base_metadata, "errorType": exc.__class__.__name__},
            )
        provider = _provider_name(quote_result.meta, self.market_data_service)
        quote_error = quote_result.errors.get(spec.proxy_symbol)
        if quote_error:
            return _skipped(
                code="quote_unavailable",
                message=(
                    f"Market-data provider did not return a usable quote for "
                    f"{spec.proxy_symbol}."
                ),
                metadata={**spec.base_metadata, "provider": provider, "quoteError": quote_error},
            )
        quote = quote_result.quotes.get(spec.proxy_symbol)
        if quote is None:
            return _skipped(
                code="missing_quote",
                message=f"Market-data provider did not return a quote for {spec.proxy_symbol}.",
                metadata={**spec.base_metadata, "provider": provider},
            )
        price = _number(quote.get("price"))
        if price is None:
            return _skipped(
                code="missing_price",
                message=f"Quote for {spec.proxy_symbol} does not include a numeric price.",
                metadata={**spec.base_metadata, "provider": provider, "quote": quote},
            )

        evidence: dict[str, Any] = {
            **spec.base_metadata,
            "provider": provider,
            "quote": quote,
            "observedPrice": price,
            "matched": False,
            "conditionResults": [],
        }
        skipped_conditions: list[dict[str, Any]] = []
        matched_conditions: list[dict[str, Any]] = []

        if spec.percent_change_below is not None:
            change_pct = _number(quote.get("change_pct"))
            if change_pct is None:
                skipped_conditions.append(
                    {
                        "type": "percent_change_below",
                        "code": "missing_change_pct",
                        "message": "Quote does not include numeric change_pct.",
                    }
                )
            else:
                matched = change_pct <= spec.percent_change_below
                condition = {
                    "type": "percent_change_below",
                    "observedChangePct": change_pct,
                    "thresholdValue": spec.percent_change_below,
                    "matched": matched,
                }
                evidence["conditionResults"].append(condition)
                evidence["observedChangePct"] = change_pct
                if matched:
                    matched_conditions.append(condition)

        if spec.drawdown_from_high_pct is not None:
            drawdown = self._drawdown_result(spec, price, provider)
            if "code" in drawdown:
                skipped_conditions.append(drawdown)
            else:
                evidence["conditionResults"].append(drawdown)
                evidence.update(
                    {
                        "lookbackPeriod": spec.lookback_period,
                        "lookbackInterval": spec.lookback_interval,
                        "autoAdjust": spec.auto_adjust,
                    }
                )
                if drawdown.get("matched") is True:
                    matched_conditions.append(drawdown)

        evidence["matchedConditions"] = matched_conditions
        evidence["skippedConditions"] = skipped_conditions
        if matched_conditions:
            evidence["matched"] = True
            summary = _trigger_summary(spec, matched_conditions)
            evidence["triggerSummary"] = summary
            return ScheduledAdapterResult(
                status=ScheduledRunStatus.COMPLETED,
                matched=True,
                code="trigger_matched",
                message=f"Market-regime monitor matched: {summary}.",
                output_summary=f"Market-regime monitor matched: {summary}.",
                metadata=evidence,
            )
        if skipped_conditions:
            return _skipped(
                code="market_regime_trigger_unavailable",
                message=(
                    f"Market-regime monitor could not evaluate all configured "
                    f"conditions for {spec.proxy_symbol}."
                ),
                metadata=evidence,
            )
        summary = _trigger_summary(spec, evidence["conditionResults"])
        evidence["triggerSummary"] = summary
        return ScheduledAdapterResult(
            status=ScheduledRunStatus.COMPLETED,
            matched=False,
            code="no_match",
            message=f"Market-regime monitor checked: no stress match for {summary}.",
            output_summary=f"Market-regime monitor checked: no stress match for {summary}.",
            metadata=evidence,
        )

    def _drawdown_result(
        self,
        spec: "_MarketRegimeProcessSpec",
        price: float,
        provider: str,
    ) -> dict[str, Any]:
        try:
            history = self.market_data_service.get_price_history(
                [spec.proxy_symbol],
                period=spec.lookback_period,
                interval=spec.lookback_interval,
                auto_adjust=spec.auto_adjust,
            )
        except Exception as exc:
            return {
                "type": "drawdown_from_high_pct",
                "code": "market_data_history_error",
                "message": f"Market-data history lookup failed: {exc}.",
                "errorType": exc.__class__.__name__,
            }
        history_error = history.errors.get(spec.proxy_symbol)
        if history_error:
            return {
                "type": "drawdown_from_high_pct",
                "code": "history_unavailable",
                "message": "Market-data provider did not return usable history.",
                "historyError": history_error,
            }
        points = history.series.get(spec.proxy_symbol) or []
        highs = [_number(point.get("high")) for point in points]
        numeric_highs = [value for value in highs if value is not None and value > 0]
        if not numeric_highs:
            return {
                "type": "drawdown_from_high_pct",
                "code": "history_reference_unavailable",
                "message": "History does not include numeric positive high values.",
            }
        reference_high = max(numeric_highs)
        drawdown_pct = ((reference_high - price) / reference_high) * 100
        matched = drawdown_pct >= (spec.drawdown_from_high_pct or 0)
        return {
            "type": "drawdown_from_high_pct",
            "provider": provider,
            "referenceHigh": reference_high,
            "observedDrawdownPct": drawdown_pct,
            "thresholdValue": spec.drawdown_from_high_pct,
            "historyPoints": len(points),
            "matched": matched,
        }

    def _build_matched_evidence(
        self,
        process: ScheduledProcess,
        spec: "_MarketRegimeProcessSpec",
        trigger_evidence: dict[str, Any],
    ) -> dict[str, Any]:
        caveats: list[str] = []
        evidence = {
            "processId": process.process_id,
            "title": process.title,
            "proxySymbol": spec.proxy_symbol,
            "proxyLabel": spec.proxy_label,
            "trigger": trigger_evidence,
            "taskGuidelines": spec.task_guidelines,
            "caveats": caveats,
        }
        evidence["search"] = self._search_evidence(process, spec, caveats)
        return evidence

    def _search_evidence(
        self,
        process: ScheduledProcess,
        spec: "_MarketRegimeProcessSpec",
        caveats: list[str],
    ) -> dict[str, Any]:
        if self.search_service is None:
            caveats.append("Search service is not configured.")
            return {"available": False}
        query = spec.search_query or (
            f"{spec.proxy_label} {spec.proxy_symbol} market stress selloff news today"
        )
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
                runtime=SearchResultRegistry(prefix=f"{process.process_id}_regime_url"),
            )
        except Exception as exc:
            caveats.append(f"Search failed: {exc}.")
            return {"available": False, "query": query, "error": str(exc)}
        payload = _tool_result_payload(result)
        payload["query"] = query
        return payload

    def _run_market_agent(
        self,
        process: ScheduledProcess,
        spec: "_MarketRegimeProcessSpec",
        evidence: dict[str, Any],
    ) -> AgentResponse:
        request = AgentRequest(
            user_message=(
                f"Explain the matched market-regime stress signal for "
                f"{spec.proxy_label} ({spec.proxy_symbol})."
            ),
            trigger_type="scheduler",
            orchestrator_guidance=_guidance(process, spec, evidence),
            metadata={"process_id": process.process_id, "scheduler_kind": process.kind.value},
        )
        return self.market_agent.handle(
            request,
            intent=AgentIntent(kind=IntentKind.UNKNOWN, entities={"domain": "market"}),
            task_complexity=TaskComplexity.COMPLEX,
        )

    def _synthesize_analysis(
        self,
        *,
        process: ScheduledProcess,
        spec: "_MarketRegimeProcessSpec",
        evidence: dict[str, Any],
        market_response: AgentResponse,
    ) -> MarketRegimeAnalysis:
        synthesizer = self.structured_synthesizer
        if synthesizer is None:
            synthesizer = StructuredAgentOutputSynthesizer(self.market_agent.reasoner.genai)
        result = synthesizer.synthesize(
            MarketRegimeAnalysis,
            source_agent_name=getattr(self.market_agent, "name", "market_analyst"),
            source_response=market_response,
            user_request=(
                f"{process.title}: explain {spec.proxy_label} "
                f"({spec.proxy_symbol}) market-regime stress"
            ),
            instructions=(
                "Return a compact market-regime stress analysis for a scheduled "
                "Telegram brief. Focus on likely drivers, near-term market impact, "
                "watch items, caveats, and data freshness. noBrokerActionConfigured "
                "must be true."
            ),
            context={
                "process": process.model_dump(by_alias=True, mode="json"),
                "evidence": evidence,
            },
            task_complexity=TaskComplexity.COMPLEX,
        )
        return MarketRegimeAnalysis.model_validate(result)


@dataclass(frozen=True, slots=True)
class _MarketRegimeProcessSpec:
    proxy_symbol: str
    proxy_label: str
    percent_change_below: float | None
    drawdown_from_high_pct: float | None
    lookback_period: str
    lookback_interval: str
    auto_adjust: bool
    search_time_range: str
    task_guidelines: str
    search_query: str | None

    @property
    def base_metadata(self) -> dict[str, object]:
        return {
            "proxySymbol": self.proxy_symbol,
            "proxyLabel": self.proxy_label,
            "triggerType": "market_regime_stress",
            "percentChangeBelow": self.percent_change_below,
            "drawdownFromHighPct": self.drawdown_from_high_pct,
            "lookbackPeriod": self.lookback_period,
            "lookbackInterval": self.lookback_interval,
            "autoAdjust": self.auto_adjust,
        }

    @classmethod
    def from_process(cls, process: ScheduledProcess) -> "_MarketRegimeProcessSpec":
        if process.kind != ScheduledProcessKind.MARKET_REGIME_MONITOR:
            raise ValueError("kind must be market_regime_monitor")
        if process.execution_mode != ScheduledExecutionMode.LLM_ASSISTED:
            raise ValueError("execution_mode must be llm_assisted")
        if process.schedule.type != ScheduleType.POLLING:
            raise ValueError("schedule.type must be polling")
        if process.safety.broker_actions_allowed:
            raise ValueError("brokerActionsAllowed must be false")
        action_type = str(process.action.get("type") or "").strip().lower()
        if action_type and action_type != "notify_only":
            raise ValueError("market_regime_monitor supports notify_only action only")
        trigger_type = str(process.trigger.get("type") or "").strip().lower()
        if trigger_type != "market_regime_stress":
            raise ValueError("trigger.type must be market_regime_stress")
        proxy_symbol = str(
            process.trigger.get("proxySymbol")
            or process.inputs.get("proxySymbol")
            or ""
        ).strip().upper()
        if not proxy_symbol:
            raise ValueError("proxySymbol is required")
        proxy_label = str(
            process.trigger.get("proxyLabel")
            or process.inputs.get("proxyLabel")
            or proxy_symbol
        ).strip()
        conditions = process.trigger.get("conditions")
        if not isinstance(conditions, list) or not conditions:
            raise ValueError("trigger.conditions must be a non-empty array")
        percent_change_below: float | None = None
        drawdown_from_high_pct: float | None = None
        lookback_period = str(process.trigger.get("lookbackPeriod") or "1mo").strip() or "1mo"
        lookback_interval = str(process.trigger.get("lookbackInterval") or "1d").strip() or "1d"
        auto_adjust = _bool(process.trigger.get("autoAdjust", False))
        for condition in conditions:
            if not isinstance(condition, dict):
                raise ValueError("trigger.conditions items must be objects")
            condition_type = str(condition.get("type") or "").strip().lower()
            value = _number(condition.get("value"))
            if condition_type == "percent_change_below":
                if value is None or value >= 0:
                    raise ValueError("percent_change_below requires a negative numeric value")
                percent_change_below = value
            elif condition_type == "drawdown_from_high_pct":
                if value is None or value <= 0:
                    raise ValueError("drawdown_from_high_pct requires a positive numeric value")
                drawdown_from_high_pct = value
                lookback_period = (
                    str(condition.get("lookbackPeriod") or lookback_period).strip()
                    or lookback_period
                )
                lookback_interval = (
                    str(condition.get("lookbackInterval") or lookback_interval).strip()
                    or lookback_interval
                )
                auto_adjust = _bool(condition.get("autoAdjust", auto_adjust))
            else:
                raise ValueError(f"unsupported market-regime condition type '{condition_type}'")
        if percent_change_below is None and drawdown_from_high_pct is None:
            raise ValueError("at least one market-regime condition is required")
        return cls(
            proxy_symbol=proxy_symbol,
            proxy_label=proxy_label,
            percent_change_below=percent_change_below,
            drawdown_from_high_pct=drawdown_from_high_pct,
            lookback_period=lookback_period,
            lookback_interval=lookback_interval,
            auto_adjust=auto_adjust,
            search_time_range=str(process.inputs.get("searchTimeRange") or "day").strip()
            or "day",
            task_guidelines=str(process.llm_scope.get("taskGuidelines") or "").strip(),
            search_query=_optional_text(process.inputs.get("searchQuery")),
        )


def _skipped(
    *,
    code: str,
    message: str,
    metadata: dict[str, object] | None = None,
) -> ScheduledAdapterResult:
    return ScheduledAdapterResult(
        status=ScheduledRunStatus.SKIPPED,
        matched=False,
        output_summary=message,
        code=code,
        message=message,
        metadata=dict(metadata or {}),
    )


def _trigger_summary(
    spec: _MarketRegimeProcessSpec,
    conditions: list[dict[str, Any]],
) -> str:
    parts: list[str] = []
    for condition in conditions:
        condition_type = condition.get("type")
        if condition_type == "percent_change_below":
            parts.append(
                f"change {condition.get('observedChangePct'):g}% <= "
                f"{condition.get('thresholdValue'):g}%"
            )
        elif condition_type == "drawdown_from_high_pct":
            parts.append(
                f"drawdown {condition.get('observedDrawdownPct'):g}% >= "
                f"{condition.get('thresholdValue'):g}% from "
                f"{condition.get('referenceHigh'):g}"
            )
    return f"{spec.proxy_label} ({spec.proxy_symbol}) " + " or ".join(parts)


def _guidance(
    process: ScheduledProcess,
    spec: _MarketRegimeProcessSpec,
    evidence: dict[str, Any],
) -> str:
    payload = {
        "purpose": "Scheduled market-regime stress explanation after deterministic trigger match.",
        "processId": process.process_id,
        "title": process.title,
        "proxySymbol": spec.proxy_symbol,
        "proxyLabel": spec.proxy_label,
        "taskGuidelines": spec.task_guidelines,
        "evidence": evidence,
        "constraints": [
            "Explain likely drivers and market impact using only configured evidence.",
            "State uncertainty and missing evidence explicitly.",
            "Do not configure, propose, submit, or imply broker actions.",
            "Return a concise trading-relevant stress brief for notification.",
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
    analysis: MarketRegimeAnalysis,
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
        f"{process.title}",
        f"{analysis.proxy_label} ({analysis.proxy_symbol}) market-regime stress",
        "",
        analysis.telegram_brief.strip(),
        "",
        f"Severity: {analysis.severity.value}",
        f"Trigger: {analysis.trigger_summary}",
        "No broker action was configured.",
    ]
    if analysis.source_refs:
        lines.append("Sources: " + "; ".join(analysis.source_refs[:5]))
    if caveats:
        lines.append("Caveats: " + "; ".join(caveats[:4]))
    return "\n".join(lines)


def _provider_name(meta: dict[str, Any], service: MarketDataService) -> str:
    provider = meta.get("provider") if isinstance(meta, dict) else None
    if provider:
        return str(provider)
    return str(getattr(service, "provider_name", None) or "market_data")


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    raw = str(value or "").strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off", ""}:
        return False
    return bool(value)


def _optional_text(value: Any) -> str | None:
    raw = str(value or "").strip()
    return raw or None
