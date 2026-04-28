from __future__ import annotations

from decimal import Decimal

import pytest

from t212ai.alpaca.broker import AlpacaBrokerClient, AlpacaBrokerService
from t212ai.brokers.models import (
    BrokerOrderSide,
    BrokerOrderStatus,
    BrokerOrderType,
    BrokerTimeInForce,
)


class RecordingAlpacaBrokerClient(AlpacaBrokerClient):
    def __init__(self) -> None:
        super().__init__(api_key="key", api_secret="secret")
        self.calls: list[dict[str, object]] = []

    def _request_json(self, **kwargs):  # type: ignore[override]
        self.calls.append(dict(kwargs))
        path = kwargs["path"]
        method = kwargs.get("method", "GET")
        if path == "/v2/account":
            return {"account_number": "PA123", "currency": "USD", "buying_power": "1000", "portfolio_value": "1500"}
        if path == "/v2/positions":
            return []
        if path == "/v2/orders" and method == "GET":
            return []
        if path == "/v2/orders" and method == "POST":
            return {
                "id": "alpaca-order-1",
                "symbol": "AAPL",
                "qty": "1",
                "filled_qty": "0",
                "side": "buy",
                "status": "accepted",
                "type": "limit",
                "time_in_force": "day",
                "limit_price": "180",
                "extended_hours": False,
                "client_order_id": "t212ai-test",
            }
        if path == "/v2/orders/alpaca-order-1":
            return {"id": "alpaca-order-1", "symbol": "AAPL", "qty": "1", "side": "buy", "status": "new", "type": "limit", "time_in_force": "day"}
        return None


class FakeAlpacaBrokerApi:
    def __init__(self) -> None:
        self.submitted_payloads: list[dict[str, object]] = []
        self.cancelled_refs: list[str] = []

    def get_account(self):
        return {
            "account_number": "PA1234567",
            "currency": "USD",
            "buying_power": "5000",
            "portfolio_value": "7500",
        }

    def list_positions(self):
        return [
            {
                "symbol": "AAPL",
                "qty": "2",
                "qty_available": "2",
                "avg_entry_price": "150",
                "current_price": "175",
                "market_value": "350",
                "cost_basis": "300",
                "unrealized_pl": "50",
            }
        ]

    def list_orders(self, *, status: str, limit: int | None = None, ticker: str | None = None, cursor=None):
        del limit, ticker, cursor
        if status == "open":
            return [
                {
                    "id": "alpaca-open-1",
                    "symbol": "MSFT",
                    "qty": "1",
                    "filled_qty": "0",
                    "side": "buy",
                    "status": "new",
                    "type": "limit",
                    "limit_price": "320",
                    "time_in_force": "day",
                    "extended_hours": False,
                    "created_at": "2026-04-27T12:00:00Z",
                }
            ]
        return [
            {
                "id": "alpaca-filled-1",
                "symbol": "AAPL",
                "qty": "1",
                "filled_qty": "1",
                "filled_avg_price": "180",
                "side": "buy",
                "status": "filled",
                "type": "market",
                "time_in_force": "day",
                "created_at": "2026-04-27T11:00:00Z",
            }
        ]

    def get_order(self, order_ref: str):
        return {
            "id": order_ref,
            "symbol": "AAPL",
            "qty": "1",
            "filled_qty": "0",
            "side": "buy",
            "status": "new",
            "type": "market",
            "time_in_force": "day",
        }

    def place_order(self, payload):
        self.submitted_payloads.append(dict(payload))
        return {
            "id": "alpaca-submitted-1",
            "symbol": payload["symbol"],
            "qty": payload["qty"],
            "filled_qty": "0",
            "side": payload["side"],
            "status": "accepted",
            "type": payload["type"],
            "time_in_force": payload["time_in_force"],
            "limit_price": payload.get("limit_price"),
            "stop_price": payload.get("stop_price"),
            "extended_hours": payload.get("extended_hours"),
            "client_order_id": payload.get("client_order_id"),
            "created_at": "2026-04-28T10:00:00Z",
        }

    def cancel_order(self, order_ref: str):
        self.cancelled_refs.append(order_ref)


def test_alpaca_broker_client_uses_trading_endpoints() -> None:
    client = RecordingAlpacaBrokerClient()

    client.get_account()
    client.list_positions()
    client.list_orders(status="open", limit=10)
    client.get_order("alpaca-order-1")
    client.place_order({"symbol": "AAPL", "qty": "1", "side": "buy", "type": "limit", "time_in_force": "day"})
    client.cancel_order("alpaca-order-1")

    assert client.calls[0]["base_url"] == client.trading_base_url
    assert client.calls[0]["path"] == "/v2/account"
    assert client.calls[4]["method"] == "POST"
    assert client.calls[5]["method"] == "DELETE"


def test_alpaca_broker_service_maps_snapshot_and_history() -> None:
    service = AlpacaBrokerService(FakeAlpacaBrokerApi())  # type: ignore[arg-type]

    snapshot = service.get_portfolio_snapshot()
    pending = service.list_pending_orders()
    history = service.list_historical_orders(limit=5)

    assert snapshot.account.id == "PA1234567"
    assert snapshot.account.currency == "USD"
    assert snapshot.positions[0].instrument.ticker == "AAPL"
    assert snapshot.positions[0].wallet_impact.current_value == Decimal("350")
    assert pending[0].id == "alpaca-open-1"
    assert pending[0].status == BrokerOrderStatus.NEW
    assert history.items[0].order is not None
    assert history.items[0].order.status == BrokerOrderStatus.FILLED


def test_alpaca_broker_service_prepare_submit_and_cancel() -> None:
    api = FakeAlpacaBrokerApi()
    service = AlpacaBrokerService(api)  # type: ignore[arg-type]

    prepared = service.prepare_order(
        order_type="LIMIT",
        side="BUY",
        ticker="AAPL",
        quantity="1",
        limit_price="180",
        time_in_force="DAY",
        extended_hours=False,
    )
    result = service.submit_prepared_order(prepared)
    cancelled = service.cancel_order("alpaca-open-1")

    assert prepared.broker_provider == "alpaca"
    assert prepared.request_payload["client_order_id"].startswith("t212ai-")
    assert result.order_id == "alpaca-submitted-1"
    assert result.order is not None
    assert result.order.side == BrokerOrderSide.BUY
    assert api.submitted_payloads[0]["symbol"] == "AAPL"
    assert cancelled.status == "accepted"
    assert api.cancelled_refs == ["alpaca-open-1"]


@pytest.mark.parametrize(
    ("kwargs", "expected_message"),
    [
        (
            {
                "order_type": "MARKET",
                "side": "BUY",
                "ticker": "AAPL",
                "quantity": "1",
                "extended_hours": True,
            },
            "extended-hours orders currently require order_type=LIMIT",
        ),
        (
            {
                "order_type": "LIMIT",
                "side": "BUY",
                "ticker": "AAPL",
                "quantity": "1",
                "limit_price": "180",
                "time_in_force": BrokerTimeInForce.GOOD_TILL_CANCEL,
                "extended_hours": True,
            },
            "extended-hours orders currently require time_in_force=DAY",
        ),
    ],
)
def test_alpaca_broker_service_validates_unsupported_order_combinations(
    kwargs,
    expected_message: str,
) -> None:
    service = AlpacaBrokerService(FakeAlpacaBrokerApi())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match=expected_message):
        service.prepare_order(**kwargs)
