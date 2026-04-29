from __future__ import annotations

from decimal import Decimal

from t212ai.brokers.exceptions import BrokerInstrumentResolutionError
from t212ai.brokers.models import (
    BrokerAccountSummary,
    BrokerCash,
    BrokerInstrumentCandidate,
    BrokerInstrumentResolution,
    BrokerInstrumentResolutionStatus,
    BrokerPortfolioSnapshot,
)
from t212ai.brokers.tools import (
    BrokerToolRuntime,
    broker_get_portfolio_snapshot,
    broker_list_pending_orders,
    broker_prepare_order,
    broker_resolve_instrument,
)


class FakeProviderError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("bad api key")
        self.status_code = 401
        self.body = '{"error":"Bad API key"}'


class FailingBrokerReadService:
    def get_portfolio_snapshot(self):
        raise FakeProviderError()

    def list_pending_orders(self):
        raise FakeProviderError()


class WorkingBrokerReadService:
    def get_portfolio_snapshot(self):
        return BrokerPortfolioSnapshot(
            account=BrokerAccountSummary(
                id="acct-1",
                currency="EUR",
                cash=BrokerCash(available_to_trade=Decimal("100")),
                total_value=Decimal("100"),
            ),
            positions=[],
            pending_orders=[],
        )

    def resolve_instrument(self, query: str, *, limit: int = 8):
        del limit
        return BrokerInstrumentResolution(
            query=query,
            status=BrokerInstrumentResolutionStatus.RESOLVED,
            resolved_ticker="AAPL_US_EQ",
            candidates=[
                BrokerInstrumentCandidate(
                    ticker="AAPL_US_EQ",
                    name="Apple Inc.",
                    currency="USD",
                    score=100,
                    match_reason="ticker_root_exact",
                )
            ],
            hint="Use broker-native ticker AAPL_US_EQ.",
        )


class InstrumentResolutionFailingExecutionService:
    def prepare_order(self, **kwargs):
        del kwargs
        resolution = BrokerInstrumentResolution(
            query="GOOGL",
            status=BrokerInstrumentResolutionStatus.AMBIGUOUS,
            candidates=[
                BrokerInstrumentCandidate(
                    ticker="GOOGLE_ES_EQ",
                    name="Alphabet Inc Class A",
                    currency="EUR",
                    score=95.0,
                    match_reason="ticker_root_fuzzy",
                ),
                BrokerInstrumentCandidate(
                    ticker="GOOGLE_US_EQ",
                    name="Alphabet Inc Class A",
                    currency="USD",
                    score=95.0,
                    match_reason="ticker_root_fuzzy",
                ),
            ],
            hint="Use the exact broker-native ticker from one candidate.",
        )
        raise BrokerInstrumentResolutionError(
            "Trading 212 instrument 'GOOGL' is ambiguous.",
            provider="trading212",
            resolution=resolution,
        )


def test_generic_broker_snapshot_returns_structured_provider_error() -> None:
    runtime = BrokerToolRuntime(
        broker_read_service=FailingBrokerReadService(),
        broker_provider="trading212",
    )

    result = broker_get_portfolio_snapshot(runtime=runtime)

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "broker_provider_request_failed"
    assert result.error.type == "FakeProviderError"
    assert result.error.hint is not None
    assert "T212_ENVIRONMENT" in result.error.hint
    assert result.error.details is not None
    assert result.error.details["operation"] == "get_portfolio_snapshot"
    assert result.error.details["status_code"] == "401"
    assert result.error.details["body"] == '{"error":"Bad API key"}'


def test_generic_broker_pending_orders_returns_structured_provider_error() -> None:
    runtime = BrokerToolRuntime(
        broker_read_service=FailingBrokerReadService(),
        broker_provider="alpaca",
    )

    result = broker_list_pending_orders(runtime=runtime)

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "broker_provider_request_failed"
    assert result.error.details is not None
    assert result.error.details["operation"] == "list_pending_orders"
    assert "ALPACA_ENVIRONMENT" in (result.error.hint or "")


def test_generic_broker_snapshot_still_returns_readable_ok_result() -> None:
    runtime = BrokerToolRuntime(
        broker_read_service=WorkingBrokerReadService(),
        broker_provider="trading212",
    )

    result = broker_get_portfolio_snapshot(runtime=runtime)

    assert result.status == "ok"
    assert result.output is not None
    assert "broker-authoritative" in result.output
    assert result.data["provider"] == "trading212"
    assert result.data["snapshot"]["account"]["currency"] == "EUR"


def test_generic_broker_resolve_instrument_returns_llm_ready_candidates() -> None:
    runtime = BrokerToolRuntime(
        broker_read_service=WorkingBrokerReadService(),
        broker_provider="trading212",
    )

    result = broker_resolve_instrument(query="AAPL", limit=5, runtime=runtime)

    assert result.status == "ok"
    assert result.output is not None
    assert "AAPL_US_EQ" in result.output
    resolution = result.data["resolution"]
    assert resolution["status"] == "resolved"
    assert resolution["resolvedTicker"] == "AAPL_US_EQ"
    assert resolution["candidates"][0]["ticker"] == "AAPL_US_EQ"


def test_generic_broker_prepare_order_returns_structured_resolution_error() -> None:
    runtime = BrokerToolRuntime(
        broker_execution_service=InstrumentResolutionFailingExecutionService(),
        broker_provider="trading212",
    )

    result = broker_prepare_order(
        order_type="MARKET",
        side="BUY",
        ticker="GOOGL",
        quantity="1",
        limit_price=None,
        stop_price=None,
        time_in_force="DAY",
        extended_hours=False,
        runtime=runtime,
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_order_request"
    assert result.error.details is not None
    resolution = result.error.details["resolution"]
    assert resolution["status"] == "ambiguous"
    assert resolution["candidates"][0]["ticker"] == "GOOGLE_ES_EQ"
    assert "error.details.resolution.candidates" in (result.error.hint or "")
