"""Alpaca news event normalization for LLM-facing workflows."""

from __future__ import annotations

import html
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .streaming import AlpacaNewsEvent, AlpacaStreamEvent

DEFAULT_CONTENT_LIMIT = 6_000
DEFAULT_FIELD_LIMIT = 800


class CleanedNewsPacket(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: int | None = None
    source: str | None = None
    headline: str | None = None
    summary: str | None = None
    content_text: str | None = Field(default=None, alias="contentText")
    symbols: list[str] = Field(default_factory=list)
    url: str | None = None
    created_at: str | None = Field(default=None, alias="createdAt")
    updated_at: str | None = Field(default=None, alias="updatedAt")
    received_at: str | None = Field(default=None, alias="receivedAt")
    dedupe_key: str = Field(alias="dedupeKey")


def clean_alpaca_news_event(
    event: AlpacaStreamEvent | AlpacaNewsEvent,
    *,
    received_at: str | None = None,
    content_limit: int = DEFAULT_CONTENT_LIMIT,
) -> CleanedNewsPacket:
    news = event.news if isinstance(event, AlpacaStreamEvent) else event
    if news is None:
        raise ValueError("Alpaca stream event does not contain a news payload.")
    resolved_received_at = (
        event.received_at if isinstance(event, AlpacaStreamEvent) else received_at
    )
    source = _clean_field(news.source, limit=120)
    url = _clean_field(news.url, limit=1_500)
    headline = _clean_html_text(news.headline, limit=DEFAULT_FIELD_LIMIT)
    summary = _clean_html_text(news.summary, limit=DEFAULT_FIELD_LIMIT)
    content_text = _clean_html_text(news.content, limit=content_limit)
    symbols = _clean_symbols(news.symbols)
    return CleanedNewsPacket(
        id=news.id,
        source=source,
        headline=headline,
        summary=summary,
        contentText=content_text,
        symbols=symbols,
        url=url,
        createdAt=_clean_field(news.created_at, limit=80),
        updatedAt=_clean_field(news.updated_at, limit=80),
        receivedAt=_clean_field(resolved_received_at, limit=80),
        dedupeKey=_dedupe_key(
            source=source,
            news_id=news.id,
            url=url,
            headline=headline,
            created_at=news.created_at,
        ),
    )


def clean_news_payload(payload: dict[str, Any]) -> CleanedNewsPacket:
    news = AlpacaNewsEvent(
        id=_safe_int(payload.get("id")),
        headline=_optional_text(payload.get("headline")),
        summary=_optional_text(payload.get("summary")),
        content=_optional_text(payload.get("content") or payload.get("contentText")),
        author=_optional_text(payload.get("author")),
        created_at=_optional_text(payload.get("created_at") or payload.get("createdAt")),
        updated_at=_optional_text(payload.get("updated_at") or payload.get("updatedAt")),
        url=_optional_text(payload.get("url")),
        symbols=_clean_symbols(payload.get("symbols") or []),
        source=_optional_text(payload.get("source")),
    )
    return clean_alpaca_news_event(
        news,
        received_at=_optional_text(payload.get("received_at") or payload.get("receivedAt")),
    )


def _clean_html_text(value: str | None, *, limit: int) -> str | None:
    if value is None:
        return None
    raw = str(value)
    try:
        from bs4 import BeautifulSoup  # type: ignore

        text = BeautifulSoup(raw, "html.parser").get_text(" ")
    except Exception:
        text = re.sub(r"<[^>]+>", " ", raw)
    return _trim(_compact_whitespace(html.unescape(text)), limit=limit)


def _clean_field(value: str | None, *, limit: int = DEFAULT_FIELD_LIMIT) -> str | None:
    if value is None:
        return None
    return _trim(_compact_whitespace(html.unescape(str(value))), limit=limit)


def _compact_whitespace(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text or ""


def _trim(value: str, *, limit: int) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    resolved_limit = max(32, int(limit))
    if len(text) <= resolved_limit:
        return text
    return text[:resolved_limit].rstrip() + "... [truncated]"


def _clean_symbols(values: Any) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    if not isinstance(values, (list, tuple, set)):
        return cleaned
    for value in values:
        symbol = str(value or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        cleaned.append(symbol)
    return cleaned


def _dedupe_key(
    *,
    source: str | None,
    news_id: int | None,
    url: str | None,
    headline: str | None,
    created_at: str | None,
) -> str:
    if source and news_id is not None:
        return f"{source}:{news_id}"
    if url:
        return f"url:{url}"
    basis = "|".join(
        item for item in (source, headline, _optional_text(created_at)) if item
    )
    return f"news:{basis or 'unknown'}"


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
