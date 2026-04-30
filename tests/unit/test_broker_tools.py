from __future__ import annotations

from decimal import Decimal

from t212ai.brokers.exceptions import BrokerInstrumentResolutionError
from t212ai.brokers.models import (
    BrokerAccountSummary,
    BrokerCash,
    BrokerInstrument,
    BrokerInstrumentCandidate,
    BrokerInstrumentResolution,
    BrokerInstrumentResolutionStatus,
    BrokerOrderSide,
    BrokerOrderType,
    BrokerPortfolioSnapshot,
    BrokerPosition,
    BrokerPositionWalletImpact,
    BrokerTimeInForce,
    PreparedBrokerOrder,
)
from t212ai.brokers.tools import (
    BrokerToolRuntime,
    broker_get_portfolio_snapshot,
    broker_list_pending_orders,
    broker_prepare_order,
    broker_resolve_instrument,
)
from t212ai.capabilities.market_data_models import MarketQuoteSnapshotResult


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


class EchoPreparingExecutionService:
    provider_name = "trading212"

    def prepare_order(self, **kwargs):
        quantity = Decimal(str(kwargs["quantity"]))
        side = BrokerOrderSide(str(kwargs["side"]).upper())
        order_type = BrokerOrderType(str(kwargs["order_type"]).upper())
        signed_quantity = quantity if side == BrokerOrderSide.BUY else -quantity
        payload = {
            "ticker": kwargs["ticker"],
            "quantity": float(signed_quantity),
            "extendedHours": bool(kwargs["extended_hours"]),
        }
        return PreparedBrokerOrder(
            broker_provider="trading212",
            order_type=order_type,
            side=side,
            ticker=kwargs["ticker"],
            quantity=quantity,
            signed_quantity=signed_quantity,
            limit_price=kwargs["limit_price"],
            stop_price=kwargs["stop_price"],
            time_in_force=BrokerTimeInForce(str(kwargs["time_in_force"]).upper()),
            extended_hours=bool(kwargs["extended_hours"]),
            request_payload=payload,
            order_fingerprint="echo",
        )


class PortfolioWithAppleReadService(WorkingBrokerReadService):
    def get_portfolio_snapshot(self):
        return BrokerPortfolioSnapshot(
            account=BrokerAccountSummary(id="acct-1", currency="EUR"),
            positions=[
                BrokerPosition(
                    instrument=BrokerInstrument(
                        name="Apple Inc.",
                        ticker="AAPL_US_EQ",
                        currency="USD",
                    ),
                    quantity=Decimal("2"),
                    quantity_available_for_trading=Decimal("2"),
                    current_price=Decimal("200"),
                    wallet_impact=BrokerPositionWalletImpact(currency="USD"),
                )
            ],
        )


class AppleMarketDataService:
    def get_quote_snapshot(self, symbols: list[str]) -> MarketQuoteSnapshotResult:
        del symbols
        return MarketQuoteSnapshotResult(
            quotes={"AAPL": {"price": 50.0, "currency": "USD"}},
            errors={},
            meta={"provider": "fake"},
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


def test_generic_broker_prepare_order_sizes_limit_order_from_notional() -> None:
    runtime = BrokerToolRuntime(
        broker_execution_service=EchoPreparingExecutionService(),
        broker_provider="trading212",
    )

    result = broker_prepare_order(
        order_type="LIMIT",
        side="BUY",
        ticker="AAPL_US_EQ",
        quantity=None,
        notional_amount="200",
        notional_currency="USD",
        limit_price="20",
        stop_price=None,
        time_in_force="DAY",
        extended_hours=False,
        runtime=runtime,
    )

    assert result.status == "ok"
    prepared = result.data["preparedOrder"]
    assert prepared["quantity"] == 10.0
    assert prepared["requestedNotionalAmount"] == 200.0
    assert prepared["requestedNotionalCurrency"] == "USD"
    assert prepared["sizingPrice"] == 20.0
    assert prepared["sizingPriceSource"] == "explicit_limit_price"


def test_generic_broker_prepare_sell_market_order_sizes_from_portfolio_price() -> None:
    runtime = BrokerToolRuntime(
        broker_read_service=PortfolioWithAppleReadService(),
        broker_execution_service=EchoPreparingExecutionService(),
        broker_provider="trading212",
    )

    result = broker_prepare_order(
        order_type="MARKET",
        side="SELL",
        ticker="AAPL_US_EQ",
        quantity=None,
        notional_amount="100",
        notional_currency="USD",
        limit_price=None,
        stop_price=None,
        time_in_force="DAY",
        extended_hours=False,
        runtime=runtime,
    )

    assert result.status == "ok"
    prepared = result.data["preparedOrder"]
    assert prepared["quantity"] == 0.5
    assert prepared["signedQuantity"] == -0.5
    assert prepared["sizingPrice"] == 200.0
    assert prepared["sizingPriceSource"] == "portfolio_current_price"


def test_generic_broker_prepare_buy_market_order_sizes_from_market_data() -> None:
    runtime = BrokerToolRuntime(
        broker_read_service=WorkingBrokerReadService(),
        broker_execution_service=EchoPreparingExecutionService(),
        market_data_service=AppleMarketDataService(),
        broker_provider="trading212",
    )

    result = broker_prepare_order(
        order_type="MARKET",
        side="BUY",
        ticker="AAPL_US_EQ",
        quantity=None,
        notional_amount="200",
        notional_currency="USD",
        limit_price=None,
        stop_price=None,
        time_in_force="DAY",
        extended_hours=False,
        runtime=runtime,
    )

    assert result.status == "ok"
    prepared = result.data["preparedOrder"]
    assert prepared["quantity"] == 4.0
    assert prepared["sizingPrice"] == 50.0
    assert prepared["sizingPriceSource"] == "market_data_quote:AAPL"
