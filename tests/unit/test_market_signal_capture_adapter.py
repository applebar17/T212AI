from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from t212ai.agent.schemas import AgentResponse
from t212ai.genai.models import ToolResult
from t212ai.market_signals import MarketSignalService
from t212ai.persistence.database import build_engine, build_session_factory, ensure_schema
from t212ai.scheduler import (
    MarketSignalCaptureAdapter,
    MarketSignalCaptureAnalysis,
    ScheduledProcess,
    ScheduledProcessService,
    ScheduledRunStatus,
)


class FakeGenAI:
    def __init__(self, analysis: MarketSignalCaptureAnalysis | None = None) -> None:
        self.analysis = analysis
        self.calls: list[dict[str, object]] = []

    def chat_model_for(self, purpose: str | None = None) -> str:
        return f"{purpose or 'default'}-model"

    def generate_structured(
        self,
        schema,
        system_prompt,
        chat_message,
        *,
        model=None,
        temperature=0.0,
        max_tokens=None,
    ):
        self.calls.append(
            {
                "schema": schema.__name__,
                "system_prompt": system_prompt,
                "chat_message": chat_message,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        if schema is MarketSignalCaptureAnalysis:
            return self.analysis or _analysis()
        raise AssertionError(f"Unexpected schema {schema}")


class FakeAgent:
    def __init__(self, genai: FakeGenAI) -> None:
        self.name = "market_analyst"
        self.reasoner = SimpleNamespace(genai=genai)
        self.calls: list[dict[str, object]] = []

    def handle(self, request, *, intent=None, task_complexity=None):
        self.calls.append(
            {
                "request": request,
                "intent": intent,
                "task_complexity": task_complexity,
            }
        )
        return AgentResponse(
            final_answer="Market analyst found durable advisory signals.",
            selected_agent=self.name,
            metadata={"workflow": "market_signal_capture"},
            artifacts={"summary": "capture artifact"},
        )


class FakeSearchService:
    def __init__(self, *, raise_error: bool = False) -> None:
        self.raise_error = raise_error
        self.calls: list[dict[str, object]] = []

    def search(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self.raise_error:
            raise RuntimeError("search failed")
        return ToolResult(
            status="ok",
            output="Search returned market signal evidence.",
            data={
                "results": [
                    {
                        "title": "Semiconductor capex update",
                        "url": "https://example.test/semis",
                        "snippet": "AI capex remains a forward demand driver.",
                    }
                ],
                "query": kwargs.get("query"),
            },
        )


class RaisingCommunityService:
    def scan_company_discussion(self, *args, **kwargs):
        raise RuntimeError("community failed")

    def search_posts(self, *args, **kwargs):
        raise RuntimeError("community failed")


class RaisingDisclosureService:
    def get_company_disclosure_snapshot(self, *args, **kwargs):
        raise RuntimeError("disclosure failed")


class RaisingMarketDataService:
    def get_market_snapshot(self, *args, **kwargs):
        raise RuntimeError("market data failed")


def _services(tmp_path: Path) -> tuple[ScheduledProcessService, MarketSignalService]:
    engine = build_engine(f"sqlite:///{tmp_path / 'market-signal-capture.db'}")
    ensure_schema(engine)
    factory = build_session_factory(engine)
    return ScheduledProcessService(factory), MarketSignalService(factory)


def _process(
    service: ScheduledProcessService,
    *,
    notification_enabled: bool = True,
    execution_mode: str = "llm_assisted",
    max_signals: int = 3,
) -> ScheduledProcess:
    return service.create_process(
        title="Semiconductor signal capture",
        description="Capture durable semis market signals.",
        kind="market_signal_capture",
        execution_mode=execution_mode,
        schedule={"type": "polling", "pollEverySeconds": 3600},
        trigger={
            "type": "market_signal_capture",
            "query": "semiconductor AI capex risks",
            "symbols": ["NVDA"],
            "sectors": ["semiconductors"],
            "tags": ["ai_capex"],
        },
        inputs={
            "query": "semiconductor AI capex risks",
            "symbols": ["NVDA"],
            "sectors": ["semiconductors"],
            "tags": ["ai_capex"],
            "maxSignals": max_signals,
            "searchTimeRange": "day",
            "communityTimeRange": "week",
            "marketPeriod": "1mo",
            "disclosureSinceDays": 30,
        },
        llm_scope={"taskGuidelines": "Save only durable forward-looking signals."},
        action={"type": "notify_only"},
        notification={"enabled": notification_enabled},
        lifecycle={
            "completionPolicy": "keep_running",
            "expiresAt": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        },
        safety={"brokerActionsAllowed": False},
    )


def _analysis(
    *,
    proposed: list[dict[str, object]] | None = None,
) -> MarketSignalCaptureAnalysis:
    return MarketSignalCaptureAnalysis(
        scanSummary="Semiconductor research produced durable AI-capex signals.",
        proposedSignals=[
            {
                "title": "AI capex remains a semiconductor demand driver",
                "summary": "AI infrastructure spending may keep semiconductors supported over the medium term, while valuation remains a caveat.",
                "symbols": ["NVDA"],
                "sectors": ["semiconductors"],
                "tags": ["ai_capex"],
                "signalType": "catalyst",
                "direction": "bullish",
                "impactHorizon": "medium_term",
                "sourceRefs": ["https://example.test/semis"],
            },
            {
                "title": "Memory supply risk remains relevant",
                "summary": "Memory supply discipline could affect semiconductor margins and inventory sensitivity over the short term.",
                "symbols": ["MU"],
                "sectors": ["semiconductors"],
                "tags": ["memory"],
                "signalType": "risk",
                "direction": "mixed",
                "impactHorizon": "short_term",
                "sourceRefs": ["https://example.test/memory"],
            },
            {
                "title": "Export-control headlines can pressure chip sentiment",
                "summary": "Regulatory headlines around chip exports can quickly shift sentiment for exposed semiconductor names.",
                "symbols": ["NVDA", "AMD"],
                "sectors": ["semiconductors"],
                "tags": ["regulatory"],
                "signalType": "regulatory",
                "direction": "bearish",
                "impactHorizon": "short_term",
                "sourceRefs": ["https://example.test/export-controls"],
            },
            {
                "title": "Skipped fourth signal",
                "summary": "This candidate should be skipped because maxSignals is three.",
                "symbols": ["AVGO"],
                "sectors": ["semiconductors"],
                "tags": ["ai_capex"],
                "signalType": "other",
                "direction": "unknown",
                "impactHorizon": "unknown",
                "sourceRefs": ["https://example.test/fourth"],
            },
        ]
        if proposed is None
        else proposed,
        rejectedItems=["Raw price-only headline was not durable."],
        caveats=["Search coverage may be incomplete."],
        sourceRefs=["https://example.test/semis"],
        dataFreshness="scheduled evidence packet",
        telegramBrief="Saved semiconductor signals for future advisory context.",
        noBrokerActionConfigured=True,
    )


def test_market_signal_capture_creates_up_to_three_signals_and_notifies(
    tmp_path: Path,
) -> None:
    scheduled_service, signal_service = _services(tmp_path)
    genai = FakeGenAI()
    market_agent = FakeAgent(genai)
    search = FakeSearchService()
    process = _process(scheduled_service)
    adapter = MarketSignalCaptureAdapter(
        market_agent=market_agent,
        market_signal_service=signal_service,
        search_service=search,
    )

    result = adapter.run(process)
    matches = signal_service.search_signals(active_only=True, include_expired=False, limit=10)

    assert result.status == ScheduledRunStatus.COMPLETED
    assert result.matched is True
    assert result.code == "market_signals_created"
    assert len(result.metadata["createdSignals"]) == 3
    assert len(matches) == 3
    assert all(match.signal.source.value == "scheduled_job" for match in matches)
    assert result.notification_message is not None
    assert "No broker action was configured" in result.notification_message
    assert result.metadata["skippedCandidates"][0]["reason"] == "max_signals_reached"
    assert market_agent.calls
    assert search.calls
    assert genai.calls[0]["schema"] == "MarketSignalCaptureAnalysis"


def test_market_signal_capture_no_durable_signals_writes_nothing(
    tmp_path: Path,
) -> None:
    scheduled_service, signal_service = _services(tmp_path)
    process = _process(scheduled_service)
    analysis = _analysis(proposed=[])
    adapter = MarketSignalCaptureAdapter(
        market_agent=FakeAgent(FakeGenAI(analysis)),
        market_signal_service=signal_service,
        search_service=FakeSearchService(),
    )

    result = adapter.run(process)

    assert result.status == ScheduledRunStatus.COMPLETED
    assert result.matched is False
    assert result.code == "no_durable_market_signals"
    assert result.notification_message is None
    assert signal_service.search_signals(limit=10) == []


def test_market_signal_capture_skips_duplicates_and_does_not_notify(
    tmp_path: Path,
) -> None:
    scheduled_service, signal_service = _services(tmp_path)
    signal_service.create_signal(
        title="AI capex remains a semiconductor demand driver",
        summary="AI infrastructure spending may keep semiconductors supported over the medium term, while valuation remains a caveat.",
        symbols=["NVDA"],
        sectors=["semiconductors"],
        tags=["ai_capex"],
        source_refs=["https://example.test/semis"],
        source="scheduled_job",
    )
    process = _process(scheduled_service)
    analysis = _analysis(
        proposed=[
            {
                "title": "AI capex remains a semiconductor demand driver",
                "summary": "AI infrastructure spending may keep semiconductors supported over the medium term, while valuation remains a caveat.",
                "symbols": ["NVDA"],
                "sectors": ["semiconductors"],
                "tags": ["ai_capex"],
                "sourceRefs": ["https://example.test/semis"],
            }
        ]
    )
    adapter = MarketSignalCaptureAdapter(
        market_agent=FakeAgent(FakeGenAI(analysis)),
        market_signal_service=signal_service,
        search_service=FakeSearchService(),
    )

    result = adapter.run(process)

    assert result.status == ScheduledRunStatus.COMPLETED
    assert result.matched is False
    assert result.notification_message is None
    assert result.metadata["skippedCandidates"][0]["reason"] == "duplicate_title"
    assert len(signal_service.search_signals(limit=10)) == 1


def test_market_signal_capture_skips_when_required_runtime_is_missing(
    tmp_path: Path,
) -> None:
    scheduled_service, signal_service = _services(tmp_path)
    process = _process(scheduled_service)

    missing_memory = MarketSignalCaptureAdapter(
        market_agent=FakeAgent(FakeGenAI()),
        market_signal_service=None,
        search_service=FakeSearchService(),
    ).run(process)
    missing_llm = MarketSignalCaptureAdapter(
        market_agent=None,
        market_signal_service=signal_service,
        search_service=FakeSearchService(),
    ).run(process)
    missing_evidence = MarketSignalCaptureAdapter(
        market_agent=FakeAgent(FakeGenAI()),
        market_signal_service=signal_service,
        market_data_service=RaisingMarketDataService(),
    ).run(process)

    assert missing_memory.status == ScheduledRunStatus.SKIPPED
    assert missing_memory.code == "market_signal_memory_unavailable"
    assert missing_llm.status == ScheduledRunStatus.SKIPPED
    assert missing_llm.code == "llm_unavailable"
    assert missing_evidence.status == ScheduledRunStatus.SKIPPED
    assert missing_evidence.code == "evidence_unavailable"


def test_market_signal_capture_optional_failures_add_caveats(
    tmp_path: Path,
) -> None:
    scheduled_service, signal_service = _services(tmp_path)
    process = _process(scheduled_service)
    adapter = MarketSignalCaptureAdapter(
        market_agent=FakeAgent(FakeGenAI()),
        market_signal_service=signal_service,
        search_service=FakeSearchService(),
        community_research_service=RaisingCommunityService(),
        disclosure_service=RaisingDisclosureService(),
        market_data_service=RaisingMarketDataService(),
    )

    result = adapter.run(process)

    assert result.status == ScheduledRunStatus.COMPLETED
    assert result.matched is True
    assert any("Community research failed" in item for item in result.metadata["caveats"])
    assert any("Disclosure lookup failed" in item for item in result.metadata["caveats"])
    assert any("Market data failed" in item for item in result.metadata["caveats"])


def test_market_signal_capture_invalid_process_spec_fails(tmp_path: Path) -> None:
    scheduled_service, signal_service = _services(tmp_path)
    process = _process(scheduled_service, execution_mode="deterministic")
    adapter = MarketSignalCaptureAdapter(
        market_agent=FakeAgent(FakeGenAI()),
        market_signal_service=signal_service,
        search_service=FakeSearchService(),
    )

    result = adapter.run(process)

    assert result.status == ScheduledRunStatus.FAILED
    assert result.code == "invalid_market_signal_capture_spec"


def test_market_signal_capture_suppresses_notification_when_disabled(
    tmp_path: Path,
) -> None:
    scheduled_service, signal_service = _services(tmp_path)
    process = _process(scheduled_service, notification_enabled=False)
    adapter = MarketSignalCaptureAdapter(
        market_agent=FakeAgent(FakeGenAI()),
        market_signal_service=signal_service,
        search_service=FakeSearchService(),
    )

    result = adapter.run(process)

    assert result.status == ScheduledRunStatus.COMPLETED
    assert result.matched is True
    assert result.notification_message is None
