"""Human-readable output rendering for Trading 212 tools."""

from __future__ import annotations

from typing import Any

from ..models import Order, PortfolioSnapshot, Position
from .formatting import _format_money, _format_value


def _format_portfolio_snapshot_output(
    snapshot: PortfolioSnapshot,
    *,
    top_positions_limit: int | None = None,
) -> str:
    account = snapshot.account
    cash = account.cash
    investments = account.investments
    lines = [
        "Trading 212 portfolio snapshot.",
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

    lines.extend(
        _format_positions(
            snapshot.positions,
            top_positions_limit=top_positions_limit,
        )
    )
    lines.extend(_format_pending_orders(snapshot.pending_orders))
    lines.append(
        "Decision note: use this as the source of truth for broker state, but fetch fresh "
        "market/news context before making recommendations that depend on current prices "
        "or external events."
    )
    return "\n".join(lines)


def _format_positions(
    positions: list[Position],
    *,
    top_positions_limit: int | None = None,
) -> list[str]:
    if not positions:
        return ["Positions: no open positions returned by Trading 212."]

    displayed_positions = _select_positions_for_display(
        positions,
        top_positions_limit=top_positions_limit,
    )
    if top_positions_limit is not None and len(displayed_positions) < len(positions):
        lines = [
            f"Positions: {len(positions)} open position(s); "
            f"showing top {len(displayed_positions)} by current value."
        ]
    else:
        lines = [
            f"Positions: {len(positions)} open position(s); "
            f"showing all {len(displayed_positions)} by current value."
        ]
    for position in displayed_positions:
        instrument = position.instrument
        wallet = position.wallet_impact
        ticker = position.ticker if hasattr(position, "ticker") else None
        ticker = ticker or (instrument.ticker if instrument else None)
        name = instrument.name if instrument else None
        currency = (wallet.currency if wallet else None) or (
            instrument.currency if instrument else None
        )
        broker_position_ref = _native_position_ref(position)
        isin = instrument.isin if instrument else None
        lines.append(
            "- "
            f"{_format_value(ticker)}"
            f"{f' ({name})' if name else ''}: "
            f"identifier={_format_value(_position_identifier(position))}, "
            f"broker_position_ref={_format_value(broker_position_ref)}, "
            f"isin={_format_value(isin)}, "
            f"quantity={_format_value(position.quantity)}, "
            f"available={_format_value(position.quantity_available_for_trading)}, "
            f"in_pies={_format_value(position.quantity_in_pies)}, "
            f"avg_price={_format_money(position.average_price_paid, currency)}, "
            f"current_price={_format_money(position.current_price, currency)}, "
            f"current_value={_format_money(wallet.current_value if wallet else None, currency)}, "
            f"total_cost={_format_money(wallet.total_cost if wallet else None, currency)}, "
            "unrealized_pnl="
            f"{_format_money(wallet.unrealized_profit_loss if wallet else None, currency)}, "
            f"fx_impact={_format_money(wallet.fx_impact if wallet else None, currency)}."
        )
    return lines


def _select_positions_for_display(
    positions: list[Position],
    *,
    top_positions_limit: int | None,
) -> list[Position]:
    sorted_positions = sorted(
        positions,
        key=lambda position: _position_current_value(position) or 0,
        reverse=True,
    )
    if top_positions_limit is None or top_positions_limit <= 0:
        return sorted_positions
    return sorted_positions[:top_positions_limit]


def _position_current_value(position: Position) -> Any:
    wallet = getattr(position, "wallet_impact", None)
    return getattr(wallet, "current_value", None) if wallet is not None else None


def _native_position_ref(position: Position) -> str | None:
    for attr in ("id", "position_id", "positionId"):
        value = getattr(position, attr, None)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _position_identifier(position: Position) -> str | None:
    broker_position_ref = _native_position_ref(position)
    if broker_position_ref is not None:
        return broker_position_ref
    instrument = getattr(position, "instrument", None)
    if instrument is not None:
        for attr in ("isin", "ticker"):
            value = getattr(instrument, attr, None)
            if value is not None and str(value).strip():
                return str(value).strip()
    return None


def _format_pending_orders(orders: list[Order]) -> list[str]:
    if not orders:
        return ["Pending orders: no active/pending orders returned by Trading 212."]

    lines = [f"Pending orders: {len(orders)} active/pending order(s)."]
    for order in orders:
        lines.append(
            "- "
            f"id={_format_value(order.id)}, "
            f"ticker={_format_value(order.ticker)}, "
            f"type={_format_value(order.type)}, "
            f"side={_format_value(order.side)}, "
            f"status={_format_value(order.status)}, "
            f"quantity={_format_value(order.quantity)}, "
            f"filled_quantity={_format_value(order.filled_quantity)}, "
            f"limit_price={_format_money(order.limit_price, order.currency)}, "
            f"stop_price={_format_money(order.stop_price, order.currency)}, "
            f"time_in_force={_format_value(order.time_in_force)}, "
            f"created_at={_format_value(order.created_at)}."
        )
    return lines


def _format_prepared_order_action_summary(prepared) -> str:
    payload = prepared.request_payload
    return "\n".join(
        [
            "Prepared Trading 212 order action.",
            "",
            "Action:",
            f"- side: {_format_value(prepared.side)}",
            f"- ticker: {_format_value(prepared.ticker)}",
            f"- order_type: {_format_value(prepared.order_type)}",
            f"- signed_quantity: {_format_value(prepared.signed_quantity)}",
            f"- limit_price: {_format_value(payload.get('limitPrice'))}",
            f"- stop_price: {_format_value(payload.get('stopPrice'))}",
            f"- time_validity: {_format_value(payload.get('timeValidity'))}",
            f"- extended_hours: {_format_value(payload.get('extendedHours'))}",
            f"- order_fingerprint: {_format_value(prepared.order_fingerprint)}",
        ]
    )


def _format_cancel_action_summary(order: Order, *, reason: str | None) -> str:
    lines = [
        "Prepared Trading 212 cancellation action.",
        "",
        "Target order:",
        f"- id: {_format_value(order.id)}",
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
