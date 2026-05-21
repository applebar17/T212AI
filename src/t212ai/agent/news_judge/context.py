"""Context rendering helpers for news judge prompts."""

from __future__ import annotations

import json

from t212ai.capabilities.protocols import BrokerReadService


def _portfolio_context(broker_read_service: BrokerReadService | None) -> str:
    if broker_read_service is None:
        return "Portfolio snapshot: unavailable."
    try:
        snapshot = broker_read_service.get_portfolio_snapshot()
    except Exception as exc:
        return f"Portfolio snapshot: unavailable ({exc.__class__.__name__})."
    positions = []
    for position in snapshot.positions[:20]:
        instrument = position.instrument
        ticker = getattr(instrument, "ticker", None) if instrument is not None else None
        name = getattr(instrument, "name", None) if instrument is not None else None
        quantity = position.quantity_available_for_trading or position.quantity
        if ticker or name:
            positions.append(
                {
                    "ticker": str(ticker or ""),
                    "name": str(name or ""),
                    "quantity": str(quantity) if quantity is not None else None,
                    "currentPrice": (
                        str(position.current_price)
                        if position.current_price is not None
                        else None
                    ),
                }
            )
    account = snapshot.account
    context = {
        "asOf": snapshot.as_of.isoformat(),
        "currency": account.currency,
        "totalValue": str(account.total_value) if account.total_value is not None else None,
        "positionCount": len(snapshot.positions),
        "positions": positions,
    }
    return "Portfolio snapshot: " + json.dumps(context, ensure_ascii=True)
