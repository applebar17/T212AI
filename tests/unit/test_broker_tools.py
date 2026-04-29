from __future__ import annotations

from decimal import Decimal

from t212ai.brokers.models import (
    BrokerAccountSummary,
    BrokerCash,
    BrokerPortfolioSnapshot,
)
from t212ai.brokers.tools import (
    BrokerToolRuntime,
    broker_get_portfolio_snapshot,
    broker_list_pending_orders,
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
