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
    BrokerInstrumentSnapshot,
    BrokerOrder,
    BrokerOrderActionResult,
    BrokerOrderSide,
    BrokerOrderStatus,
    BrokerOrderType,
    BrokerPortfolioSnapshot,
    BrokerPosition,
    BrokerPositionWalletImpact,
    BrokerTimeInForce,
    PreparedBrokerOrder,
)
from t212ai.brokers.tools import (
    _BROKER_ORDER_ARGUMENTS_SCHEMA,
    BrokerToolRuntime,
    broker_cancel_order,
    broker_get_order,
    broker_get_instrument_snapshot,
    broker_get_portfolio_snapshot,
    broker_list_pending_orders,
    broker_place_order,
    broker_prepare_cancel_action,
    broker_prepare_order,
    broker_resolve_instrument,
)
from t212ai.capabilities.market_data_models import MarketQuoteSnapshotResult


class FakeProviderError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("bad api key")
        self.status_code = 401
        self.body = '{"error":"Bad API key"}'


def test_broker_order_tool_schema_requires_resolved_notional_amount() -> None:
    notional_schema = _BROKER_ORDER_ARGUMENTS_SCHEMA["properties"]["notional_amount"]
    description = notional_schema["description"]

    assert notional_schema["type"] == ["number", "null"]
    assert "Resolved numeric cash amount" in description
    assert "half available cash" in description
    assert "first fetch that state" in description


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

    def get_instrument_snapshot(self, ticker: str):
        resolution = self.resolve_instrument(ticker)
        return BrokerInstrumentSnapshot(
            provider="trading212",
            query=ticker,
            status=BrokerInstrumentResolutionStatus.RESOLVED,
            instrument=BrokerInstrument(
                ticker="AAPL_US_EQ",
                name="Apple Inc.",
                currency="USD",
                isin="US0378331005",
            ),
            resolution=resolution,
            tradable=True,
            orderable=True,
            fractional=None,
            asset_class="STOCK",
            snapshot_source="fake",
            hint="Use AAPL_US_EQ for broker orders.",
        )


class PendingOrderReadService(WorkingBrokerReadService):
    def __init__(self) -> None:
        self.orders = [
            BrokerOrder(
                id="broker-order-abc",
                ticker="AAPL_US_EQ",
                side=BrokerOrderSide.BUY,
                type=BrokerOrderType.LIMIT,
                status=BrokerOrderStatus.NEW,
                quantity=Decimal("2"),
                limit_price=Decimal("150"),
                currency="USD",
            )
        ]
        self.get_order_refs: list[str] = []

    def list_pending_orders(self):
        return self.orders

    def get_order(self, order_ref: str):
        self.get_order_refs.append(order_ref)
        for order in self.orders:
            if order.id == order_ref:
                return order
        raise ValueError(f"Order {order_ref} not found.")


class CapturingPendingActionService:
    def __init__(self) -> None:
        self.target_order: BrokerOrder | None = None

    def create_cancel_action(self, **kwargs):
        self.target_order = kwargs["target_order"]

        class Action:
            action_id = "pa_123"
            summary_text = kwargs["summary_text"]

            def model_dump(self, mode="json"):
                del mode
                return {
                    "action_id": self.action_id,
                    "target_order_ref": kwargs["target_order"].id,
                }

        return Action()


class CapturingExecutionService:
    def __init__(self) -> None:
        self.cancelled_refs: list[str] = []

    def cancel_order(self, order_ref: str):
        self.cancelled_refs.append(order_ref)
        return BrokerOrderActionResult(
            brokerProvider="trading212",
            action="cancel_order",
            status="submitted",
            orderId=order_ref,
            message="Cancellation sent.",
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


class CloseOnlyExecutionService(EchoPreparingExecutionService):
    def submit_prepared_order(self, prepared_order: PreparedBrokerOrder):
        del prepared_order
        error = RuntimeError("Trading 212 API request failed with HTTP 400.")
        error.status_code = 400
        error.body = (
            '{"type":"/api-errors/instrument-close-only-mode",'
            '"title":"Error while placing the order","status":400,'
            '"detail":"Close only mode","traceId":"trace-close-only"}'
        )
        raise error


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


def test_generic_broker_snapshot_exposes_public_position_refs() -> None:
    runtime = BrokerToolRuntime(
        broker_read_service=PortfolioWithAppleReadService(),
        broker_provider="trading212",
    )

    result = broker_get_portfolio_snapshot(runtime=runtime)

    assert result.status == "ok"
    assert result.output is not None
    assert "POSITION_000001" in result.output
    position = result.data["snapshot"]["positions"][0]
    assert position["publicPositionRef"] == "POSITION_000001"


def test_generic_broker_pending_orders_exposes_public_order_refs() -> None:
    runtime = BrokerToolRuntime(
        broker_read_service=PendingOrderReadService(),
        broker_provider="trading212",
    )

    result = broker_list_pending_orders(runtime=runtime)

    assert result.status == "ok"
    assert result.output is not None
    assert "ORDER_000001" in result.output
    order = result.data["orders"][0]
    assert order["publicOrderRef"] == "ORDER_000001"
    assert order["brokerOrderRef"] == "broker-order-abc"


def test_generic_broker_get_order_accepts_public_order_ref() -> None:
    read_service = PendingOrderReadService()
    runtime = BrokerToolRuntime(
        broker_read_service=read_service,
        broker_provider="trading212",
    )
    list_result = broker_list_pending_orders(runtime=runtime)
    public_ref = list_result.data["orders"][0]["publicOrderRef"]

    result = broker_get_order(order_ref=public_ref, runtime=runtime)

    assert result.status == "ok"
    assert read_service.get_order_refs == ["broker-order-abc"]
    assert result.data["order"]["publicOrderRef"] == public_ref


def test_generic_broker_get_order_rejects_unknown_public_order_ref() -> None:
    runtime = BrokerToolRuntime(
        broker_read_service=PendingOrderReadService(),
        broker_provider="trading212",
    )

    result = broker_get_order(order_ref="ORDER_000999", runtime=runtime)

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "unknown_public_reference"


def test_generic_broker_prepare_cancel_accepts_public_ref_but_persists_true_ref() -> None:
    pending_action_service = CapturingPendingActionService()
    runtime = BrokerToolRuntime(
        broker_read_service=PendingOrderReadService(),
        pending_action_service=pending_action_service,
        broker_provider="trading212",
        chat_id="chat-1",
    )
    list_result = broker_list_pending_orders(runtime=runtime)
    public_ref = list_result.data["orders"][0]["publicOrderRef"]

    result = broker_prepare_cancel_action(
        order_ref=public_ref,
        selector=None,
        reason="user requested cancel",
        runtime=runtime,
    )

    assert result.status == "ok"
    assert pending_action_service.target_order is not None
    assert pending_action_service.target_order.id == "broker-order-abc"
    assert result.data["pendingAction"]["target_order_ref"] == "broker-order-abc"
    assert result.data["targetOrder"]["publicOrderRef"] == public_ref


def test_generic_broker_cancel_order_accepts_public_order_ref() -> None:
    execution_service = CapturingExecutionService()
    runtime = BrokerToolRuntime(
        broker_read_service=PendingOrderReadService(),
        broker_execution_service=execution_service,
        broker_provider="trading212",
        allow_state_changes=True,
    )
    list_result = broker_list_pending_orders(runtime=runtime)
    public_ref = list_result.data["orders"][0]["publicOrderRef"]

    result = broker_cancel_order(
        order_ref=public_ref,
        confirmed=True,
        reason=None,
        runtime=runtime,
    )

    assert result.status == "ok"
    assert execution_service.cancelled_refs == ["broker-order-abc"]
    assert result.data["brokerOrderRef"] == "broker-order-abc"


def test_generic_broker_get_order_still_accepts_raw_broker_refs() -> None:
    read_service = PendingOrderReadService()
    runtime = BrokerToolRuntime(
        broker_read_service=read_service,
        broker_provider="trading212",
    )

    result = broker_get_order(order_ref="broker-order-abc", runtime=runtime)

    assert result.status == "ok"
    assert read_service.get_order_refs == ["broker-order-abc"]
    assert result.data["order"]["publicOrderRef"] == "ORDER_000001"


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


def test_generic_broker_get_instrument_snapshot_returns_broker_metadata() -> None:
    runtime = BrokerToolRuntime(
        broker_read_service=WorkingBrokerReadService(),
        broker_provider="trading212",
    )

    result = broker_get_instrument_snapshot(ticker="AAPL", runtime=runtime)

    assert result.status == "ok"
    assert result.output is not None
    assert "Trading 212 instrument snapshot" in result.output
    assert "AAPL_US_EQ" in result.output
    snapshot = result.data["snapshot"]
    assert snapshot["provider"] == "trading212"
    assert snapshot["status"] == "resolved"
    assert snapshot["instrument"]["ticker"] == "AAPL_US_EQ"
    assert snapshot["tradable"] is True
    assert snapshot["orderable"] is True
    assert snapshot["assetClass"] == "STOCK"


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
    assert result.output is not None
    assert "No broker order was prepared or submitted." in result.output
    assert "Candidate broker-native tickers" in result.output
    assert "GOOGLE_ES_EQ" in result.output
    assert result.error is not None
    assert result.error.code == "ambiguous_broker_instrument"
    assert result.error.details is not None
    resolution = result.error.details["resolution"]
    assert resolution["status"] == "ambiguous"
    assert resolution["candidates"][0]["ticker"] == "GOOGLE_ES_EQ"
    assert "Do not guess" in (result.error.hint or "")


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


def test_generic_broker_place_order_returns_semantic_close_only_error() -> None:
    runtime = BrokerToolRuntime(
        broker_execution_service=CloseOnlyExecutionService(),
        broker_provider="trading212",
        allow_state_changes=True,
    )

    result = broker_place_order(
        order_type="LIMIT",
        side="BUY",
        ticker="CHSNUSEQ",
        quantity="3389",
        notional_amount=None,
        notional_currency=None,
        limit_price="0.0295",
        stop_price=None,
        time_in_force="GOOD_TILL_CANCEL",
        extended_hours=True,
        confirmed=True,
        confirmation_reference="echo",
        runtime=runtime,
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "instrument_temporarily_not_tradable"
    assert result.error.retryable is False
    assert "close-only mode" in result.error.message
    assert "temporarily not tradable" in (result.error.hint or "")
    assert result.error.details is not None
    assert result.error.details["provider_error_type"] == "/api-errors/instrument-close-only-mode"


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
