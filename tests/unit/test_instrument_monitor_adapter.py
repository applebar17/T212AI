from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from t212ai.capabilities.market_data_models import (
    MarketPriceHistoryResult,
    MarketQuoteSnapshotResult,
)
from t212ai.scheduler import InstrumentMonitorAdapter
from t212ai.scheduler.models import ScheduledProcess, ScheduledRunStatus


BASE_NOW = datetime(2026, 5, 7, 9, 0, tzinfo=UTC)


class FakeMarketDataService:
    provider_name = "fake_market_data"

    def __init__(
        self,
        *,
        quote: dict[str, Any] | None = None,
        quote_errors: dict[str, dict[str, Any]] | None = None,
        history: list[dict[str, Any]] | None = None,
        history_errors: dict[str, dict[str, Any]] | None = None,
        raise_quote: Exception | None = None,
        raise_history: Exception | None = None,
    ) -> None:
        self.quote = quote
        self.quote_errors = dict(quote_errors or {})
        self.history = history
        self.history_errors = dict(history_errors or {})
        self.raise_quote = raise_quote
        self.raise_history = raise_history
        self.history_calls: list[dict[str, Any]] = []

    def get_quote_snapshot(self, symbols: list[str]) -> MarketQuoteSnapshotResult:
        if self.raise_quote is not None:
            raise self.raise_quote
        quotes = {symbols[0]: self.quote} if self.quote is not None else {}
        return MarketQuoteSnapshotResult(
            quotes=quotes,
            errors=self.quote_errors,
            meta={"provider": "fake"},
        )

    def get_price_history(
        self,
        symbols: list[str],
        *,
        period: str = "1mo",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
        auto_adjust: bool = False,
    ) -> MarketPriceHistoryResult:
        del start, end
        if self.raise_history is not None:
            raise self.raise_history
        self.history_calls.append(
            {
                "symbols": symbols,
                "period": period,
                "interval": interval,
                "auto_adjust": auto_adjust,
            }
        )
        series = {symbols[0]: list(self.history or [])} if self.history is not None else {}
        return MarketPriceHistoryResult(
            series=series,
            errors=self.history_errors,
            meta={"provider": "fake"},
        )


def _process(trigger: dict[str, Any], *, notification: dict[str, Any] | None = None):
    return ScheduledProcess(
        process_id="sched_test",
        title="TSLA monitor",
        description="",
        kind="instrument_monitor",
        execution_mode="deterministic",
        status="active",
        schedule={"type": "polling", "pollEverySeconds": 60},
        trigger=trigger,
        inputs={},
        llm_scope={},
        action={},
        notification=notification or {},
        lifecycle={"completionPolicy": "keep_running"},
        safety={},
        created_at=BASE_NOW,
        updated_at=BASE_NOW,
        next_run_at=BASE_NOW,
        last_run_at=None,
        last_status=None,
        failure_count=0,
    )


def _quote(*, price: float = 100.0, change_pct: float = 1.5):
    return {
        "symbol": "TSLA",
        "price": price,
        "change_pct": change_pct,
        "currency": "USD",
        "market_state": "REGULAR",
    }


@pytest.mark.parametrize(
    ("trigger_type", "value", "price", "matched"),
    [
        ("below_price", 100.0, 99.0, True),
        ("below_price", 100.0, 101.0, False),
        ("above_price", 100.0, 101.0, True),
        ("above_price", 100.0, 99.0, False),
    ],
)
def test_instrument_monitor_evaluates_price_triggers(
    trigger_type: str,
    value: float,
    price: float,
    matched: bool,
) -> None:
    adapter = InstrumentMonitorAdapter(FakeMarketDataService(quote=_quote(price=price)))

    result = adapter.run(_process({"type": trigger_type, "symbol": "TSLA", "value": value}))

    assert result.status == ScheduledRunStatus.COMPLETED
    assert result.matched is matched
    assert result.code == ("trigger_matched" if matched else "no_match")
    assert result.metadata["observedPrice"] == price
    assert result.metadata["thresholdValue"] == value
    assert result.notification_message is not None if matched else result.notification_message is None


@pytest.mark.parametrize(
    ("trigger_type", "value", "change_pct", "matched"),
    [
        ("percent_change_below", -5.0, -5.5, True),
        ("percent_change_below", -5.0, -4.5, False),
        ("percent_change_above", 3.0, 3.5, True),
        ("percent_change_above", 3.0, 2.5, False),
    ],
)
def test_instrument_monitor_evaluates_percent_triggers(
    trigger_type: str,
    value: float,
    change_pct: float,
    matched: bool,
) -> None:
    adapter = InstrumentMonitorAdapter(
        FakeMarketDataService(quote=_quote(price=100.0, change_pct=change_pct))
    )

    result = adapter.run(_process({"type": trigger_type, "symbol": "TSLA", "value": value}))

    assert result.status == ScheduledRunStatus.COMPLETED
    assert result.matched is matched
    assert result.metadata["observedChangePct"] == change_pct
    assert result.metadata["thresholdValue"] == value


@pytest.mark.parametrize(
    ("trigger_type", "price", "matched", "reference_key"),
    [
        ("period_low_breakdown", 88.0, True, "referenceLow"),
        ("period_low_breakdown", 95.0, False, "referenceLow"),
        ("period_high_breakout", 112.0, True, "referenceHigh"),
        ("period_high_breakout", 105.0, False, "referenceHigh"),
    ],
)
def test_instrument_monitor_evaluates_period_high_low_triggers(
    trigger_type: str,
    price: float,
    matched: bool,
    reference_key: str,
) -> None:
    service = FakeMarketDataService(
        quote=_quote(price=price),
        history=[
            {"timestamp": "2026-05-01T00:00:00Z", "low": 89.0, "high": 110.0},
            {"timestamp": "2026-05-02T00:00:00Z", "low": 91.0, "high": 108.0},
        ],
    )
    adapter = InstrumentMonitorAdapter(service)

    result = adapter.run(
        _process(
            {
                "type": trigger_type,
                "symbol": "TSLA",
                "lookbackPeriod": "3mo",
                "lookbackInterval": "1d",
                "autoAdjust": True,
            }
        )
    )

    assert result.status == ScheduledRunStatus.COMPLETED
    assert result.matched is matched
    assert result.metadata[reference_key] in {89.0, 110.0}
    assert result.metadata["lookbackPeriod"] == "3mo"
    assert result.metadata["lookbackInterval"] == "1d"
    assert service.history_calls == [
        {
            "symbols": ["TSLA"],
            "period": "3mo",
            "interval": "1d",
            "auto_adjust": True,
        }
    ]


def test_instrument_monitor_skips_when_market_data_is_missing() -> None:
    result = InstrumentMonitorAdapter(None).run(
        _process({"type": "below_price", "symbol": "TSLA", "value": 100.0})
    )

    assert result.status == ScheduledRunStatus.SKIPPED
    assert result.code == "market_data_unavailable"
    assert result.notification_message is None


def test_instrument_monitor_skips_provider_quote_errors_and_missing_quote() -> None:
    quote_error_result = InstrumentMonitorAdapter(
        FakeMarketDataService(
            quote_errors={
                "TSLA": {"code": "missing_quote", "message": "No quote.", "retryable": False}
            }
        )
    ).run(_process({"type": "below_price", "symbol": "TSLA", "value": 100.0}))

    missing_quote_result = InstrumentMonitorAdapter(FakeMarketDataService()).run(
        _process({"type": "below_price", "symbol": "TSLA", "value": 100.0})
    )

    assert quote_error_result.status == ScheduledRunStatus.SKIPPED
    assert quote_error_result.code == "quote_unavailable"
    assert missing_quote_result.status == ScheduledRunStatus.SKIPPED
    assert missing_quote_result.code == "missing_quote"


def test_instrument_monitor_skips_missing_history_and_provider_exceptions() -> None:
    missing_history_result = InstrumentMonitorAdapter(
        FakeMarketDataService(quote=_quote(price=100.0), history=[])
    ).run(_process({"type": "period_low_breakdown", "symbol": "TSLA"}))
    exception_result = InstrumentMonitorAdapter(
        FakeMarketDataService(quote=_quote(price=100.0), raise_history=RuntimeError("boom"))
    ).run(_process({"type": "period_high_breakout", "symbol": "TSLA"}))

    assert missing_history_result.status == ScheduledRunStatus.SKIPPED
    assert missing_history_result.code == "history_unavailable"
    assert exception_result.status == ScheduledRunStatus.SKIPPED
    assert exception_result.code == "market_data_history_error"


def test_instrument_monitor_invalid_spec_returns_failed() -> None:
    result = InstrumentMonitorAdapter(FakeMarketDataService(quote=_quote())).run(
        _process({"type": "below_price", "symbol": "TSLA"})
    )

    assert result.status == ScheduledRunStatus.FAILED
    assert result.code == "invalid_instrument_monitor_spec"


def test_instrument_monitor_match_notification_is_deterministic_and_suppressible() -> None:
    adapter = InstrumentMonitorAdapter(FakeMarketDataService(quote=_quote(price=99.0)))

    notifying = adapter.run(
        _process({"type": "below_price", "symbol": "TSLA", "value": 100.0})
    )
    suppressed = adapter.run(
        _process(
            {"type": "below_price", "symbol": "TSLA", "value": 100.0},
            notification={"enabled": False},
        )
    )

    assert notifying.notification_message is not None
    assert "Scheduler alert: TSLA monitor" in notifying.notification_message
    assert "TSLA price 99 <= 100" in notifying.notification_message
    assert notifying.notification_metadata["provider"] == "fake"
    assert suppressed.matched is True
    assert suppressed.notification_message is None
