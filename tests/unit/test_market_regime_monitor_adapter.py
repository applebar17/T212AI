from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from t212ai.agent.schemas import AgentResponse
from t212ai.capabilities.market_data_models import (
    MarketPriceHistoryResult,
    MarketQuoteSnapshotResult,
)
from t212ai.genai.models import ToolResult
from t212ai.persistence.database import build_engine, build_session_factory, ensure_schema
from t212ai.scheduler import (
    MarketRegimeAnalysis,
    MarketRegimeMonitorAdapter,
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
        if schema is MarketRegimeAnalysis:
            return MarketRegimeAnalysis(
                proxySymbol="QQQ",
                proxyLabel="Nasdaq",
                triggerSummary="Nasdaq (QQQ) change -3.5% <= -3%",
                severity="stressed",
                regimeSummary="Growth proxies are under pressure.",
                likelyDrivers=["Rates and risk-off positioning."],
                marketImpact="Near-term breadth and beta may remain fragile.",
                watchItems=["Treasury yields", "mega-cap breadth"],
                sourceRefs=["https://example.test/market-stress"],
                caveats=["Search coverage may be incomplete."],
                dataFreshness="scheduled run evidence packet",
                telegramBrief="Nasdaq stress trigger matched; risk-off context is elevated.",
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
            final_answer=f"{self.name} explained the market-regime stress.",
            selected_agent=self.name,
            metadata={"workflow": self.name},
            artifacts={"summary": "market stress artifact"},
        )


class FakeMarketDataService:
    provider_name = "fake_market"

    def __init__(
        self,
        *,
        price: float = 100.0,
        change_pct: float | None = -3.5,
        highs: list[float] | None = None,
        quote_errors: dict[str, dict[str, object]] | None = None,
        history_errors: dict[str, dict[str, object]] | None = None,
    ) -> None:
        self.price = price
        self.change_pct = change_pct
        self.highs = highs or [101.0, 100.0]
        self.quote_errors = quote_errors or {}
        self.history_errors = history_errors or {}
        self.quote_calls = 0
        self.history_calls = 0

    def get_quote_snapshot(self, symbols):
        self.quote_calls += 1
        symbol = symbols[0]
        quote = {"symbol": symbol, "price": self.price, "currency": "USD"}
        if self.change_pct is not None:
            quote["change_pct"] = self.change_pct
        return MarketQuoteSnapshotResult(
            quotes={} if self.quote_errors else {symbol: quote},
            errors=self.quote_errors,
            meta={"provider": self.provider_name},
        )

    def get_price_history(self, symbols, **kwargs):
        self.history_calls += 1
        symbol = symbols[0]
        return MarketPriceHistoryResult(
            series={
                symbol: [
                    {
                        "timestamp": f"2026-05-0{index + 1}T00:00:00Z",
                        "high": high,
                        "low": high - 2,
                        "close": high - 1,
                    }
                    for index, high in enumerate(self.highs)
                ]
            }
            if not self.history_errors
            else {},
            errors=self.history_errors,
            meta={"provider": self.provider_name, **kwargs},
        )


class FakeSearchService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def search(self, **kwargs):
        self.calls.append(dict(kwargs))
        return ToolResult(
            status="ok",
            output="Search returned market stress context.",
            data={
                "results": [
                    {
                        "title": "Market stress",
                        "url": "https://example.test/market-stress",
                        "snippet": "Growth stocks sold off.",
                    }
                ],
                "query": kwargs.get("query"),
            },
        )


def _service(tmp_path: Path) -> ScheduledProcessService:
    engine = build_engine(f"sqlite:///{tmp_path / 'market-regime.db'}")
    ensure_schema(engine)
    return ScheduledProcessService(build_session_factory(engine))


def _market_regime_process(
    tmp_path: Path,
    *,
    conditions: list[dict[str, object]] | None = None,
    notification_enabled: bool = True,
    execution_mode: str = "llm_assisted",
) -> ScheduledProcess:
    service = _service(tmp_path)
    return service.create_process(
        title="Nasdaq stress monitor",
        description="Monitor broad market stress.",
        kind="market_regime_monitor",
        execution_mode=execution_mode,
        schedule={"type": "polling", "pollEverySeconds": 300},
        trigger={
            "type": "market_regime_stress",
            "proxySymbol": "QQQ",
            "proxyLabel": "Nasdaq",
            "conditions": conditions
            or [{"type": "percent_change_below", "value": -3.0}],
            "lookbackPeriod": "1mo",
            "lookbackInterval": "1d",
            "autoAdjust": False,
        },
        inputs={"proxySymbol": "QQQ", "proxyLabel": "Nasdaq", "searchTimeRange": "day"},
        llm_scope={"taskGuidelines": "Explain likely drivers and what to watch."},
        action={"type": "notify_only"},
        notification={"enabled": notification_enabled},
        lifecycle={
            "completionPolicy": "complete_on_first_match",
            "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
        },
        safety={"brokerActionsAllowed": False},
    )


def test_market_regime_percent_match_calls_market_agent_and_notifies(
    tmp_path: Path,
) -> None:
    genai = FakeGenAI()
    market_agent = FakeAgent("market_analyst", genai)
    search = FakeSearchService()
    process = _market_regime_process(tmp_path)
    adapter = MarketRegimeMonitorAdapter(
        market_agent=market_agent,
        market_data_service=FakeMarketDataService(change_pct=-3.5),
        search_service=search,
    )

    result = adapter.run(process)

    assert result.status == ScheduledRunStatus.COMPLETED
    assert result.matched is True
    assert result.code == "market_regime_analysis_completed"
    assert result.notification_message is not None
    assert "No broker action was configured" in result.notification_message
    assert result.metadata["analysis"]["proxySymbol"] == "QQQ"
    assert result.metadata["analysis"]["severity"] == "stressed"
    assert result.metadata["evidence"]["search"]["available"] is True
    assert market_agent.calls
    assert search.calls
    assert genai.calls[0]["schema"] == "MarketRegimeAnalysis"


def test_market_regime_percent_no_match_avoids_search_and_llm(tmp_path: Path) -> None:
    genai = FakeGenAI()
    market_agent = FakeAgent("market_analyst", genai)
    search = FakeSearchService()
    market_data = FakeMarketDataService(change_pct=-2.0)
    process = _market_regime_process(tmp_path)
    adapter = MarketRegimeMonitorAdapter(
        market_agent=market_agent,
        market_data_service=market_data,
        search_service=search,
    )

    result = adapter.run(process)

    assert result.status == ScheduledRunStatus.COMPLETED
    assert result.matched is False
    assert result.code == "no_match"
    assert result.notification_message is None
    assert market_agent.calls == []
    assert search.calls == []
    assert genai.calls == []
    assert market_data.history_calls == 0


def test_market_regime_drawdown_match_and_no_match(tmp_path: Path) -> None:
    process = _market_regime_process(
        tmp_path,
        conditions=[{"type": "drawdown_from_high_pct", "value": 5.0}],
    )
    matched = MarketRegimeMonitorAdapter(
        market_agent=FakeAgent("market_analyst", FakeGenAI()),
        market_data_service=FakeMarketDataService(price=90.0, change_pct=0.0, highs=[100.0]),
    ).run(process)
    no_match = MarketRegimeMonitorAdapter(
        market_agent=FakeAgent("market_analyst", FakeGenAI()),
        market_data_service=FakeMarketDataService(price=98.0, change_pct=0.0, highs=[100.0]),
    ).run(process)

    assert matched.status == ScheduledRunStatus.COMPLETED
    assert matched.matched is True
    assert matched.metadata["evidence"]["trigger"]["matchedConditions"][0]["type"] == (
        "drawdown_from_high_pct"
    )
    assert no_match.status == ScheduledRunStatus.COMPLETED
    assert no_match.matched is False
    assert no_match.code == "no_match"


def test_market_regime_search_is_optional_after_match(tmp_path: Path) -> None:
    process = _market_regime_process(tmp_path)
    adapter = MarketRegimeMonitorAdapter(
        market_agent=FakeAgent("market_analyst", FakeGenAI()),
        market_data_service=FakeMarketDataService(change_pct=-4.0),
        search_service=None,
    )

    result = adapter.run(process)

    assert result.status == ScheduledRunStatus.COMPLETED
    assert result.matched is True
    assert result.metadata["evidence"]["search"]["available"] is False
    assert "Search service is not configured." in result.metadata["caveats"]


def test_market_regime_skips_when_market_data_is_missing(tmp_path: Path) -> None:
    process = _market_regime_process(tmp_path)
    adapter = MarketRegimeMonitorAdapter(market_agent=FakeAgent("market_analyst", FakeGenAI()))

    result = adapter.run(process)

    assert result.status == ScheduledRunStatus.SKIPPED
    assert result.code == "market_data_unavailable"


def test_market_regime_skips_llm_only_after_trigger_match(tmp_path: Path) -> None:
    process = _market_regime_process(tmp_path)
    search = FakeSearchService()
    adapter = MarketRegimeMonitorAdapter(
        market_agent=None,
        market_data_service=FakeMarketDataService(change_pct=-4.0),
        search_service=search,
    )

    result = adapter.run(process)

    assert result.status == ScheduledRunStatus.SKIPPED
    assert result.code == "llm_unavailable"
    assert search.calls == []


def test_market_regime_fails_invalid_process_spec(tmp_path: Path) -> None:
    process = _market_regime_process(tmp_path, execution_mode="deterministic")
    adapter = MarketRegimeMonitorAdapter(
        market_agent=FakeAgent("market_analyst", FakeGenAI()),
        market_data_service=FakeMarketDataService(),
    )

    result = adapter.run(process)

    assert result.status == ScheduledRunStatus.FAILED
    assert result.code == "invalid_market_regime_monitor_spec"


def test_market_regime_suppresses_notification_when_disabled(tmp_path: Path) -> None:
    process = _market_regime_process(tmp_path, notification_enabled=False)
    adapter = MarketRegimeMonitorAdapter(
        market_agent=FakeAgent("market_analyst", FakeGenAI()),
        market_data_service=FakeMarketDataService(change_pct=-4.0),
    )

    result = adapter.run(process)

    assert result.status == ScheduledRunStatus.COMPLETED
    assert result.matched is True
    assert result.notification_message is None
