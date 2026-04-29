"""Trading 212 instrument resolution helpers."""

from __future__ import annotations

from difflib import SequenceMatcher
import re
from typing import Any

from t212ai.brokers.models import (
    BrokerInstrument,
    BrokerInstrumentCandidate,
    BrokerInstrumentResolution,
    BrokerInstrumentResolutionStatus,
)

from .models import TradableInstrument


MIN_MATCH_SCORE = 70.0
MIN_AUTO_RESOLVE_MARGIN = 5.0


def resolve_trading212_instrument(
    query: str,
    instruments: list[TradableInstrument],
    *,
    limit: int = 8,
) -> BrokerInstrumentResolution:
    resolved_query = str(query or "").strip()
    if not resolved_query:
        return BrokerInstrumentResolution(
            query=resolved_query,
            status=BrokerInstrumentResolutionStatus.NOT_FOUND,
            hint="Provide a broker ticker, public symbol, ISIN, or instrument name.",
        )

    candidates = _rank_candidates(resolved_query, instruments)[: max(1, int(limit))]
    if not candidates:
        return BrokerInstrumentResolution(
            query=resolved_query,
            status=BrokerInstrumentResolutionStatus.NOT_FOUND,
            hint=(
                "Trading 212 requires its broker-native instrument ticker. "
                "Call broker_resolve_instrument with a broader company or fund name."
            ),
        )

    top = candidates[0]
    runner_up_score = candidates[1].score if len(candidates) > 1 else 0.0
    if top.score >= MIN_MATCH_SCORE and top.score - runner_up_score >= MIN_AUTO_RESOLVE_MARGIN:
        return BrokerInstrumentResolution(
            query=resolved_query,
            status=BrokerInstrumentResolutionStatus.RESOLVED,
            resolved_ticker=top.ticker,
            candidates=candidates,
            hint=f"Use broker-native ticker {top.ticker} for Trading 212 orders.",
        )

    return BrokerInstrumentResolution(
        query=resolved_query,
        status=BrokerInstrumentResolutionStatus.AMBIGUOUS,
        candidates=candidates,
        hint=(
            "Multiple Trading 212 instruments matched. Use the exact broker-native "
            "ticker from candidates before preparing an order."
        ),
    )


def broker_instrument_from_candidate(candidate: BrokerInstrumentCandidate) -> BrokerInstrument:
    return BrokerInstrument(
        currency=candidate.currency,
        isin=candidate.isin,
        name=candidate.name or candidate.short_name,
        ticker=candidate.ticker,
    )


def _rank_candidates(
    query: str,
    instruments: list[TradableInstrument],
) -> list[BrokerInstrumentCandidate]:
    scored: list[BrokerInstrumentCandidate] = []
    for instrument in instruments:
        candidate = _score_instrument(query, instrument)
        if candidate.score >= MIN_MATCH_SCORE:
            scored.append(candidate)
    scored.sort(
        key=lambda item: (
            -item.score,
            item.ticker,
            item.currency or "",
            item.name or "",
        )
    )
    return scored


def _score_instrument(
    query: str,
    instrument: TradableInstrument,
) -> BrokerInstrumentCandidate:
    ticker = str(instrument.ticker or "").strip().upper()
    name = str(instrument.name or "").strip() or None
    short_name = str(instrument.short_name or "").strip() or None
    isin = str(instrument.isin or "").strip().upper() or None
    currency = str(instrument.currency_code or "").strip().upper() or None
    instrument_type = str(instrument.type.value if instrument.type else "").strip() or None

    query_key = _normalize_key(query)
    ticker_key = _normalize_key(ticker)
    root_key = _normalize_key(_ticker_root(ticker))
    isin_key = _normalize_key(isin)
    text_keys = [_normalize_key(value) for value in (name, short_name) if value]
    token_keys = [
        _normalize_key(token)
        for value in (name, short_name)
        if value
        for token in re.split(r"[^A-Za-z0-9]+", value)
        if len(token) >= 3
    ]

    score, reason = _best_score(
        query_key=query_key,
        ticker_key=ticker_key,
        root_key=root_key,
        isin_key=isin_key,
        text_keys=text_keys,
        token_keys=token_keys,
    )
    return BrokerInstrumentCandidate(
        ticker=ticker,
        name=name,
        short_name=short_name,
        isin=isin,
        currency=currency,
        type=instrument_type,
        score=round(score, 3),
        match_reason=reason,
    )


def _best_score(
    *,
    query_key: str,
    ticker_key: str,
    root_key: str,
    isin_key: str,
    text_keys: list[str],
    token_keys: list[str],
) -> tuple[float, str | None]:
    scores: list[tuple[float, str]] = []
    if query_key and query_key == ticker_key:
        scores.append((100.0, "broker_ticker_exact"))
    if query_key and query_key == root_key:
        scores.append((95.0, "ticker_root_exact"))
    if query_key and query_key == isin_key:
        scores.append((95.0, "isin_exact"))
    if query_key and ticker_key and (query_key in ticker_key or ticker_key in query_key):
        scores.append((85.0, "broker_ticker_contains"))
    if query_key and root_key and (query_key in root_key or root_key in query_key):
        scores.append((80.0, "ticker_root_contains"))

    root_ratio = _similarity(query_key, root_key)
    if root_ratio >= 0.78:
        scores.append((70.0 + root_ratio * 10.0, "ticker_root_fuzzy"))

    for text_key in text_keys:
        if query_key and query_key in text_key:
            scores.append((76.0, "instrument_name_contains"))
        text_ratio = _similarity(query_key, text_key)
        if text_ratio >= 0.86:
            scores.append((64.0 + text_ratio * 10.0, "instrument_name_fuzzy"))

    for token_key in token_keys:
        if query_key == token_key:
            scores.append((78.0, "instrument_name_token_exact"))
        token_ratio = _similarity(query_key, token_key)
        if token_ratio >= 0.84:
            scores.append((60.0 + token_ratio * 10.0, "instrument_name_token_fuzzy"))

    if not scores:
        return 0.0, None
    return max(scores, key=lambda item: item[0])


def _ticker_root(ticker: str) -> str:
    return str(ticker or "").split("_", 1)[0]


def _normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()
