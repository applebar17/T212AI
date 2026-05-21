"""Human-readable output rendering for broker tools."""

from __future__ import annotations

from typing import Any

from ..models import BrokerOrder, PreparedBrokerOrder
from .formatting import _display_broker_name, _enum_value, _format_money, _format_value
from .references import _register_order_public_ref, _register_position_public_ref
from .runtime import BrokerToolRuntime


def _format_pending_orders_output(
    orders: list[BrokerOrder],
    *,
    runtime: BrokerToolRuntime,
) -> str:
    provider_name = _display_broker_name(runtime.broker_provider)
    lines = [f"Retrieved {len(orders)} pending {provider_name} orders."]
    for order in orders:
        public_ref = _register_order_public_ref(order, runtime=runtime)
        if public_ref is None:
            continue
        lines.append(
            f"- {public_ref}: "
            f"{_format_value(order.side)} {_format_value(order.ticker)}, "
            f"type={_format_value(order.type)}, "
            f"status={_format_value(order.status)}, "
            f"quantity={_format_value(order.quantity)}"
        )
    return "\n".join(lines)


def _format_instrument_snapshot_output(snapshot: Any, *, provider: str) -> str:
    provider_name = _display_broker_name(provider)
    instrument = getattr(snapshot, "instrument", None)
    resolution = getattr(snapshot, "resolution", None)
    lines = [
        (
            f"{provider_name} instrument snapshot for "
            f"{_format_value(getattr(snapshot, 'query', None))}."
        ),
        f"Resolution status: {_enum_value(getattr(snapshot, 'status', None)) or 'unknown'}.",
    ]
    if instrument is not None:
        lines.append(
            "Instrument: "
            f"ticker={_format_value(getattr(instrument, 'ticker', None))}, "
            f"name={_format_value(getattr(instrument, 'name', None))}, "
            f"currency={_format_value(getattr(instrument, 'currency', None))}, "
            f"isin={_format_value(getattr(instrument, 'isin', None))}."
        )
    else:
        lines.append("Instrument: no unique broker instrument snapshot was returned.")
    lines.append(
        "Tradability: "
        f"tradable={_format_value(getattr(snapshot, 'tradable', None))}, "
        f"orderable={_format_value(getattr(snapshot, 'orderable', None))}, "
        f"fractional={_format_value(getattr(snapshot, 'fractional', None))}, "
        f"shortable={_format_value(getattr(snapshot, 'shortable', None))}, "
        f"extended_hours={_format_value(getattr(snapshot, 'extended_hours', None))}."
    )
    lines.append(
        "Metadata: "
        f"asset_class={_format_value(getattr(snapshot, 'asset_class', None))}, "
        f"exchange={_format_value(getattr(snapshot, 'exchange', None))}, "
        f"broker_status={_format_value(getattr(snapshot, 'broker_status', None))}, "
        f"source={_format_value(getattr(snapshot, 'snapshot_source', None))}."
    )
    if resolution is not None and getattr(resolution, "candidates", None):
        candidates = []
        for candidate in resolution.candidates[:5]:
            candidates.append(
                f"{candidate.ticker}"
                f"({_format_value(candidate.currency)}, "
                f"score={_format_value(candidate.score)})"
            )
        if candidates:
            lines.append("Candidates: " + "; ".join(candidates) + ".")
    if getattr(snapshot, "hint", None):
        lines.append(f"Hint: {snapshot.hint}")
    return "\n".join(lines)


def _format_portfolio_snapshot_output(
    snapshot,
    *,
    provider: str,
    runtime: BrokerToolRuntime,
) -> str:
    account = snapshot.account
    cash = account.cash
    investments = account.investments
    provider_name = _display_broker_name(provider)
    lines = [
        f"{provider_name} portfolio snapshot.",
        "Authority: broker-authoritative for account, positions, cash, and pending orders.",
        f"As of: {_format_value(snapshot.as_of)}.",
        (
            "Account: "
            f"id={_format_value(account.id)}, "
            f"currency={_format_value(account.currency)}, "
            f"total_value={_format_money(account.total_value, account.currency)}."
        ),
    ]
    if cash:
        lines.append(
            "Cash: "
            f"available_to_trade={_format_money(cash.available_to_trade, account.currency)}, "
            f"reserved_for_orders={_format_money(cash.reserved_for_orders, account.currency)}, "
            f"in_pies={_format_money(cash.in_pies, account.currency)}."
        )
    if investments:
        lines.append(
            "Investments: "
            f"current_value={_format_money(investments.current_value, account.currency)}, "
            f"total_cost={_format_money(investments.total_cost, account.currency)}, "
            "unrealized_pnl="
            f"{_format_money(investments.unrealized_profit_loss, account.currency)}, "
            f"realized_pnl={_format_money(investments.realized_profit_loss, account.currency)}."
        )
    if snapshot.positions:
        lines.append(f"Positions: {len(snapshot.positions)} open position(s).")
        for index, position in enumerate(snapshot.positions):
            instrument = position.instrument
            public_ref = _register_position_public_ref(
                position,
                index=index,
                runtime=runtime,
            )
            if public_ref is None:
                continue
            lines.append(
                f"- {public_ref}: "
                f"{_format_value(instrument.ticker if instrument else None)}, "
                f"quantity={_format_value(position.quantity)}, "
                f"available={_format_value(position.quantity_available_for_trading)}, "
                f"current_price={_format_money(position.current_price, instrument.currency if instrument else None)}"
            )
    else:
        lines.append(f"Positions: no open positions returned by {provider_name}.")
    if snapshot.pending_orders:
        lines.append(f"Pending orders: {len(snapshot.pending_orders)} active/pending order(s).")
        for order in snapshot.pending_orders:
            public_ref = _register_order_public_ref(order, runtime=runtime)
            if public_ref is None:
                continue
            lines.append(
                f"- {public_ref}: "
                f"{_format_value(order.side)} {_format_value(order.ticker)}, "
                f"type={_format_value(order.type)}, "
                f"status={_format_value(order.status)}, "
                f"quantity={_format_value(order.quantity)}"
            )
    else:
        lines.append(f"Pending orders: no active/pending orders returned by {provider_name}.")
    return "\n".join(lines)


def _format_prepared_order_action_summary(
    prepared: PreparedBrokerOrder,
    *,
    provider: str,
) -> str:
    payload = prepared.request_payload
    provider_name = _display_broker_name(provider)
    lines = [
        f"Prepared {provider_name} order action.",
        "",
    ]
    if prepared.requested_notional_amount is not None:
        lines.extend(
            [
                "Sizing:",
                "- requested_notional: "
                f"{_format_money(prepared.requested_notional_amount, prepared.requested_notional_currency)}",
                f"- sizing_price: {_format_money(prepared.sizing_price, prepared.requested_notional_currency)}",
                f"- sizing_price_source: {_format_value(prepared.sizing_price_source)}",
                f"- estimated_quantity: {_format_value(prepared.quantity)}",
                "",
            ]
        )
    lines.extend(
        [
            "Action:",
            f"- side: {_format_value(prepared.side)}",
            f"- ticker: {_format_value(prepared.ticker)}",
            f"- order_type: {_format_value(prepared.order_type)}",
            f"- quantity: {_format_value(prepared.quantity)}",
            f"- signed_quantity: {_format_value(prepared.signed_quantity)}",
            f"- limit_price: {_format_value(payload.get('limitPrice'))}",
            f"- stop_price: {_format_value(payload.get('stopPrice'))}",
            f"- time_in_force: {_format_value(prepared.time_in_force)}",
            f"- extended_hours: {_format_value(prepared.extended_hours)}",
            f"- order_fingerprint: {_format_value(prepared.order_fingerprint)}",
        ]
    )
    return "\n".join(lines)


def _format_cancel_action_summary(
    order: BrokerOrder,
    *,
    provider: str,
    reason: str | None,
    runtime: BrokerToolRuntime | None = None,
) -> str:
    provider_name = _display_broker_name(provider)
    public_ref = (
        _register_order_public_ref(order, runtime=runtime)
        if runtime is not None
        else None
    )
    lines = [
        f"Prepared {provider_name} cancellation action.",
        "",
        "Target order:",
        f"- public_ref: {_format_value(public_ref)}",
        f"- broker_order_ref: {_format_value(order.id)}",
        f"- ticker: {_format_value(order.ticker)}",
        f"- type: {_format_value(order.type)}",
        f"- side: {_format_value(order.side)}",
        f"- status: {_format_value(order.status)}",
        f"- quantity: {_format_value(order.quantity)}",
        f"- limit_price: {_format_money(order.limit_price, order.currency)}",
        f"- stop_price: {_format_money(order.stop_price, order.currency)}",
        f"- created_at: {_format_value(order.created_at)}",
    ]
    if reason:
        lines.append(f"- reason: {reason}")
    return "\n".join(lines)
