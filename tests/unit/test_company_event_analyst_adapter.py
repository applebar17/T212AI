from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from t212ai.agent.schemas import AgentResponse
from t212ai.data_sources.sec_edgar.models import (
    EdgarFilingActivityResult,
    EdgarFilingRecord,
)
from t212ai.genai.models import ToolResult
from t212ai.persistence.database import build_engine, build_session_factory, ensure_schema
from t212ai.scheduler import (
    CompanyEventAnalysis,
    CompanyEventAnalystAdapter,
    ScheduledProcess,
    ScheduledProcessService,
    ScheduledRunStatus,
)


class FakeGenAI:
    def __init__(self) -> None:
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
        if schema is CompanyEventAnalysis:
            return CompanyEventAnalysis(
                symbol="MSFT",
                companyName="Microsoft Corporation",
                eventType="earnings_report",
                eventSummary="Microsoft reported resilient cloud demand.",
                thesisImpact="The event supports the medium-term cloud growth thesis.",
                direction="bullish",
                impactHorizon="medium_term",
                keyPoints=["Azure growth remains relevant.", "Guidance needs monitoring."],
                risks=["Valuation remains sensitive to rates."],
                uncertainties=["Search coverage may be incomplete."],
                sourceRefs=["https://example.test/msft-earnings"],
                dataFreshness="scheduled run evidence packet",
                marketContextSummary="Market backdrop was constructive.",
                telegramBrief="MSFT earnings look supportive, with cloud demand as the key driver.",
                noBrokerActionConfigured=True,
            )
        raise AssertionError(f"Unexpected schema {schema}")


class FakeAgent:
    def __init__(self, name: str, genai: FakeGenAI) -> None:
        self.name = name
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
            final_answer=f"{self.name} analyzed the scheduled event.",
            selected_agent=self.name,
            metadata={"workflow": self.name},
            artifacts={"summary": f"{self.name} artifact"},
        )


class FakeMarketDataService:
    def get_market_snapshot(self, symbols, **kwargs):
        return ToolResult(
            status="ok",
            output="Market snapshot returned.",
            data={
                "quotes": {symbols[0]: {"price": 420.0, "currency": "USD"}},
                "meta": kwargs,
            },
        )


class FakeDisclosureService:
    def get_company_disclosure_snapshot(self, symbol, *, since_days=30, limit=12):
        return EdgarFilingActivityResult(
            symbol=symbol,
            cik="0000789019",
            company_name="Microsoft Corporation",
            activity_label="company disclosure snapshot",
            since_days=since_days,
            tracked_forms=["10-Q", "8-K"],
            filing_counts={"10-Q": 1},
            recent_filings=[
                EdgarFilingRecord(
                    form="10-Q",
                    normalized_form="10-Q",
                    filed_at=date(2026, 5, 1),
                    filing_url="https://example.test/10q",
                    category="periodic_report",
                )
            ],
        )


class FakeSearchService:
    def search(self, **kwargs):
        return ToolResult(
            status="ok",
            output="Search returned company event context.",
            data={
                "results": [
                    {
                        "title": "Microsoft earnings",
                        "url": "https://example.test/msft-earnings",
                        "snippet": "Cloud growth remained strong.",
                    }
                ],
                "query": kwargs.get("query"),
            },
        )


def _service(tmp_path: Path) -> ScheduledProcessService:
    engine = build_engine(f"sqlite:///{tmp_path / 'company-event.db'}")
    ensure_schema(engine)
    return ScheduledProcessService(build_session_factory(engine))


def _company_event_process(
    tmp_path: Path,
    *,
    include_market: bool = False,
    notification_enabled: bool = True,
    execution_mode: str = "llm_assisted",
) -> ScheduledProcess:
    service = _service(tmp_path)
    return service.create_process(
        title="MSFT earnings review",
        description="Scheduled company-event research.",
        kind="company_event_analyst",
        execution_mode=execution_mode,
        schedule={
            "type": "one_shot",
            "runAt": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        },
        trigger={"type": "company_event", "symbol": "MSFT", "eventType": "earnings_report"},
        inputs={
            "symbols": ["MSFT"],
            "eventType": "earnings_report",
            "disclosureSinceDays": 30,
            "searchTimeRange": "week",
            "marketPeriod": "1mo",
        },
        llm_scope={
            "taskGuidelines": "Focus on cloud growth, guidance, risks, and thesis impact.",
            "includeMarketAnalyst": include_market,
        },
        action={"type": "notify_only"},
        notification={"enabled": notification_enabled},
        lifecycle={"completionPolicy": "complete_on_first_run"},
        safety={"brokerActionsAllowed": False},
    )


def test_company_event_adapter_completes_with_structured_analysis_and_notification(
    tmp_path: Path,
) -> None:
    genai = FakeGenAI()
    company_agent = FakeAgent("company_analyst", genai)
    market_agent = FakeAgent("market_analyst", genai)
    process = _company_event_process(tmp_path, include_market=True)
    adapter = CompanyEventAnalystAdapter(
        company_agent=company_agent,
        market_agent=market_agent,
        market_data_service=FakeMarketDataService(),
        disclosure_service=FakeDisclosureService(),
        search_service=FakeSearchService(),
    )

    result = adapter.run(process)

    assert result.status == ScheduledRunStatus.COMPLETED
    assert result.matched is True
    assert result.code == "company_event_analysis_completed"
    assert result.notification_message is not None
    assert "No broker action was configured" in result.notification_message
    assert result.metadata["analysis"]["symbol"] == "MSFT"
    assert result.metadata["analysis"]["eventType"] == "earnings_report"
    assert result.metadata["analysis"]["noBrokerActionConfigured"] is True
    assert result.metadata["evidence"]["marketData"]["available"] is True
    assert result.metadata["evidence"]["disclosure"]["available"] is True
    assert result.metadata["evidence"]["search"]["available"] is True
    assert company_agent.calls
    assert market_agent.calls
    assert genai.calls[0]["schema"] == "CompanyEventAnalysis"


def test_company_event_adapter_degrades_when_optional_services_are_missing(
    tmp_path: Path,
) -> None:
    genai = FakeGenAI()
    process = _company_event_process(tmp_path)
    adapter = CompanyEventAnalystAdapter(company_agent=FakeAgent("company_analyst", genai))

    result = adapter.run(process)

    assert result.status == ScheduledRunStatus.COMPLETED
    assert result.metadata["evidence"]["marketData"]["available"] is False
    assert result.metadata["evidence"]["disclosure"]["available"] is False
    assert result.metadata["evidence"]["search"]["available"] is False
    assert result.metadata["caveats"]


def test_company_event_adapter_skips_when_company_agent_is_missing(tmp_path: Path) -> None:
    process = _company_event_process(tmp_path)
    adapter = CompanyEventAnalystAdapter(company_agent=None)

    result = adapter.run(process)

    assert result.status == ScheduledRunStatus.SKIPPED
    assert result.code == "llm_unavailable"


def test_company_event_adapter_fails_invalid_process_spec(tmp_path: Path) -> None:
    process = _company_event_process(tmp_path, execution_mode="deterministic")
    adapter = CompanyEventAnalystAdapter(company_agent=FakeAgent("company_analyst", FakeGenAI()))

    result = adapter.run(process)

    assert result.status == ScheduledRunStatus.FAILED
    assert result.code == "invalid_company_event_analyst_spec"


def test_company_event_adapter_suppresses_notification_when_disabled(
    tmp_path: Path,
) -> None:
    process = _company_event_process(tmp_path, notification_enabled=False)
    adapter = CompanyEventAnalystAdapter(
        company_agent=FakeAgent("company_analyst", FakeGenAI())
    )

    result = adapter.run(process)

    assert result.status == ScheduledRunStatus.COMPLETED
    assert result.notification_message is None


def test_company_event_adapter_calls_market_agent_only_when_requested(
    tmp_path: Path,
) -> None:
    genai = FakeGenAI()
    market_agent = FakeAgent("market_analyst", genai)
    process = _company_event_process(tmp_path, include_market=False)
    adapter = CompanyEventAnalystAdapter(
        company_agent=FakeAgent("company_analyst", genai),
        market_agent=market_agent,
    )

    result = adapter.run(process)

    assert result.status == ScheduledRunStatus.COMPLETED
    assert market_agent.calls == []
