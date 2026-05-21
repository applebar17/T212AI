"""Broker state context helpers for order reasoning."""

from __future__ import annotations

import re
from typing import Any


def _metadata_user_id(metadata: dict[str, str]) -> int | None:
    raw = str(metadata.get("telegram_user_id", "")).strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None

def _broker_snapshot_order_context(snapshot: Any) -> str:
    account = getattr(snapshot, "account", None)
    cash = getattr(account, "cash", None) if account is not None else None
    currency = getattr(account, "currency", None)
    lines = [
        "Broker state context for order reasoning. Use these values only as current "
        "broker-provided context; calculate any relative order sizing before filling "
        "numeric order fields."
    ]
    if account is not None:
        lines.append(
            "Account: "
            f"currency={_context_value(currency)}, "
            f"total_value={_context_value(getattr(account, 'total_value', None))}."
        )
    if cash is not None:
        lines.append(
            "Cash: "
            f"available_to_trade={_context_value(getattr(cash, 'available_to_trade', None))}, "
            f"reserved_for_orders={_context_value(getattr(cash, 'reserved_for_orders', None))}, "
            f"in_pies={_context_value(getattr(cash, 'in_pies', None))}."
        )
    positions = list(getattr(snapshot, "positions", []) or [])
    if positions:
        summarized_positions = []
        for position in positions[:8]:
            instrument = getattr(position, "instrument", None)
            ticker = getattr(instrument, "ticker", None) if instrument is not None else None
            summarized_positions.append(
                "{ticker}: quantity={quantity}, available={available}".format(
                    ticker=_context_value(ticker or getattr(position, "ticker", None)),
                    quantity=_context_value(getattr(position, "quantity", None)),
                    available=_context_value(
                        getattr(position, "quantity_available_for_trading", None)
                    ),
                )
            )
        lines.append("Positions: " + "; ".join(summarized_positions) + ".")
    pending_orders = list(getattr(snapshot, "pending_orders", []) or [])
    lines.append(f"Pending orders count: {len(pending_orders)}.")
    return "\n".join(lines)


def _context_value(value: Any) -> str:
    if value is None:
        return "unknown"
    raw = str(value).strip()
    return raw if raw else "unknown"


def _match_position_for_liquidation(
    positions: list[Any],
    *,
    ticker_hint: str | None,
    user_message: str,
):
    hint = _normalize_position_text(ticker_hint)
    message = _normalize_position_text(user_message)
    candidates: list[tuple[int, Any]] = []
    for position in positions:
        best_score = 0
        for name in _position_match_texts(position):
            normalized = _normalize_position_text(name)
            if not normalized:
                continue
            if hint and (hint == normalized or hint in normalized or normalized in hint):
                best_score = max(best_score, 4)
            if normalized and re.search(rf"\b{re.escape(normalized)}\b", message):
                best_score = max(best_score, 3)
            if _has_meaningful_token_overlap(normalized, message):
                best_score = max(best_score, 2)
            if hint and any(token == normalized for token in hint.split()):
                best_score = max(best_score, 2)
        if best_score > 0:
            candidates.append((best_score, position))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _position_match_texts(position: Any) -> list[str]:
    instrument = getattr(position, "instrument", None)
    values = [
        getattr(position, "ticker", None),
        getattr(instrument, "ticker", None) if instrument is not None else None,
        getattr(instrument, "name", None) if instrument is not None else None,
    ]
    return [str(value).strip() for value in values if str(value or "").strip()]


def _normalize_position_text(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", raw).strip()


def _has_meaningful_token_overlap(candidate: str, message: str) -> bool:
    candidate_tokens = {token for token in candidate.split() if len(token) >= 3}
    message_tokens = {token for token in message.split() if len(token) >= 3}
    return bool(candidate_tokens & message_tokens)
