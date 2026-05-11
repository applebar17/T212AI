"""Alpaca websocket market-data streaming helpers."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .base import AlpacaApiError, AlpacaBaseClient


@dataclass(slots=True)
class AlpacaStreamSubscription:
    news: list[str] = field(default_factory=list)
    trades: list[str] = field(default_factory=list)
    quotes: list[str] = field(default_factory=list)
    bars: list[str] = field(default_factory=list)
    updated_bars: list[str] = field(default_factory=list)
    daily_bars: list[str] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    imbalances: list[str] = field(default_factory=list)

    @classmethod
    def news_all(cls) -> AlpacaStreamSubscription:
        return cls(news=["*"])

    def to_message(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"action": "subscribe"}
        channel_map = {
            "news": self.news,
            "trades": self.trades,
            "quotes": self.quotes,
            "bars": self.bars,
            "updatedBars": self.updated_bars,
            "dailyBars": self.daily_bars,
            "statuses": self.statuses,
            "imbalances": self.imbalances,
        }
        for channel, symbols in channel_map.items():
            cleaned = _clean_symbols(symbols, allow_wildcard=True)
            if cleaned:
                payload[channel] = cleaned
        if len(payload) == 1:
            raise ValueError("At least one Alpaca stream subscription channel is required.")
        return payload


@dataclass(slots=True)
class AlpacaNewsEvent:
    id: int | None
    headline: str | None
    summary: str | None
    content: str | None
    author: str | None
    created_at: str | None
    updated_at: str | None
    url: str | None
    symbols: list[str]
    source: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "headline": self.headline,
            "summary": self.summary,
            "content": self.content,
            "author": self.author,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "url": self.url,
            "symbols": list(self.symbols),
            "source": self.source,
        }


@dataclass(slots=True)
class AlpacaStreamEvent:
    stream: str
    message_type: str
    symbol: str | None
    received_at: str
    raw: dict[str, Any]
    news: AlpacaNewsEvent | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "stream": self.stream,
            "message_type": self.message_type,
            "symbol": self.symbol,
            "received_at": self.received_at,
            "raw": self.raw,
        }
        if self.news is not None:
            payload["news"] = self.news.to_dict()
        return payload

    def to_news_record(self) -> dict[str, Any]:
        if self.news is None:
            raise ValueError("Stream event is not a news event.")
        return {
            "received_at": self.received_at,
            "stream": self.stream,
            "message_type": self.message_type,
            **self.news.to_dict(),
            "raw": self.raw,
        }


class AlpacaStreamError(AlpacaApiError):
    @classmethod
    def from_event(cls, event: AlpacaStreamEvent) -> AlpacaStreamError:
        code = event.raw.get("code")
        message = event.raw.get("msg") or event.raw.get("message") or "Alpaca stream error."
        return cls(
            f"Alpaca stream error {code}: {message}",
            status_code=_safe_int(code),
            body=json.dumps(event.raw, ensure_ascii=True, sort_keys=True),
            code=_stream_error_code(code),
        )


@dataclass(slots=True)
class AlpacaNewsCaptureResult:
    output_path: str
    received_count: int
    written_count: int
    skipped_count: int
    started_at: str
    finished_at: str

    def render_text(self) -> str:
        return (
            "Alpaca news stream capture completed.\n"
            f"output: {self.output_path}\n"
            f"receivedNews: {self.received_count}\n"
            f"written: {self.written_count}\n"
            f"skippedByFilter: {self.skipped_count}"
        )


class AlpacaStreamClient(AlpacaBaseClient):
    provider_name = "alpaca"

    @classmethod
    def from_client(cls, client: AlpacaBaseClient) -> AlpacaStreamClient:
        return cls(
            api_key=client.api_key,
            api_secret=client.api_secret,
            environment=client.environment,
            market_data_base_url=client.market_data_base_url,
            stream_base_url=client.stream_base_url,
            stream_sandbox_base_url=client.stream_sandbox_base_url,
            paper_trading_base_url=client.paper_trading_base_url,
            live_trading_base_url=client.live_trading_base_url,
            data_feed=client.data_feed,
            timeout_seconds=client.timeout_seconds,
        )

    def news_stream_url(self, *, sandbox: bool = False) -> str:
        return f"{self._stream_base(sandbox=sandbox)}/v1beta1/news"

    def stock_stream_url(
        self,
        *,
        feed: str | None = None,
        sandbox: bool = False,
    ) -> str:
        resolved_feed = _normalize_stock_feed(feed or self.data_feed)
        return f"{self._stream_base(sandbox=sandbox)}/{resolved_feed}"

    def test_stream_url(self, *, sandbox: bool = False) -> str:
        return f"{self._stream_base(sandbox=sandbox)}/v2/test"

    def stream_url(
        self,
        *,
        stream: str = "news",
        feed: str | None = None,
        sandbox: bool = False,
    ) -> str:
        normalized = str(stream or "news").strip().lower()
        if normalized == "news":
            return self.news_stream_url(sandbox=sandbox)
        if normalized in {"stock", "stocks", "market_data"}:
            return self.stock_stream_url(feed=feed, sandbox=sandbox)
        if normalized == "test":
            return self.test_stream_url(sandbox=sandbox)
        raise ValueError(f"Unsupported Alpaca stream '{stream}'.")

    async def connect_and_subscribe(
        self,
        subscription: AlpacaStreamSubscription,
        *,
        stream: str = "news",
        feed: str | None = None,
        sandbox: bool = False,
        raise_on_error: bool = True,
    ) -> AsyncIterator[AlpacaStreamEvent]:
        try:
            import websockets
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError(
                "The 'websockets' package is required for Alpaca streaming."
            ) from exc

        url = self.stream_url(stream=stream, feed=feed, sandbox=sandbox)
        async with websockets.connect(url, open_timeout=self.timeout_seconds) as websocket:
            await websocket.send(
                json.dumps(
                    {
                        "action": "auth",
                        "key": self.api_key,
                        "secret": self.api_secret,
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                )
            )
            await websocket.send(
                json.dumps(subscription.to_message(), ensure_ascii=True, sort_keys=True)
            )
            async for message in websocket:
                for event in parse_stream_message(message, stream=stream):
                    if event.message_type == "error" and raise_on_error:
                        raise AlpacaStreamError.from_event(event)
                    yield event

    def _stream_base(self, *, sandbox: bool) -> str:
        base = self.stream_sandbox_base_url if sandbox else self.stream_base_url
        return str(base or "").rstrip("/")


async def capture_alpaca_news_stream(
    client: AlpacaStreamClient,
    output_path: str | Path,
    *,
    symbols: list[str] | tuple[str, ...] | None = None,
    max_events: int | None = None,
    seconds: float | None = None,
    sandbox: bool = False,
) -> AlpacaNewsCaptureResult:
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    filter_symbols = set(_clean_symbols(symbols or [], allow_wildcard=False))
    started_at = _utc_now_iso()
    started_monotonic = time.monotonic()
    deadline = None if seconds is None else started_monotonic + max(0.0, float(seconds))
    received_count = 0
    written_count = 0
    skipped_count = 0
    stream = client.connect_and_subscribe(
        AlpacaStreamSubscription.news_all(),
        stream="news",
        sandbox=sandbox,
    )
    iterator = stream.__aiter__()
    try:
        with path.open("a", encoding="utf-8") as handle:
            while max_events is None or written_count < max(0, int(max_events)):
                event = await _next_stream_event(iterator, deadline=deadline)
                if event is None:
                    break
                if event.news is None:
                    continue
                received_count += 1
                if filter_symbols and filter_symbols.isdisjoint(event.news.symbols):
                    skipped_count += 1
                    continue
                handle.write(json.dumps(event.to_news_record(), ensure_ascii=True, sort_keys=True))
                handle.write("\n")
                handle.flush()
                written_count += 1
    finally:
        close = getattr(stream, "aclose", None)
        if callable(close):
            await close()
    return AlpacaNewsCaptureResult(
        output_path=str(path),
        received_count=received_count,
        written_count=written_count,
        skipped_count=skipped_count,
        started_at=started_at,
        finished_at=_utc_now_iso(),
    )


async def _next_stream_event(
    iterator: AsyncIterator[AlpacaStreamEvent],
    *,
    deadline: float | None,
) -> AlpacaStreamEvent | None:
    try:
        if deadline is None:
            return await iterator.__anext__()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        return await asyncio.wait_for(iterator.__anext__(), timeout=remaining)
    except TimeoutError:
        return None
    except StopAsyncIteration:
        return None


def parse_stream_message(
    message: str | bytes,
    *,
    stream: str,
) -> list[AlpacaStreamEvent]:
    payload = _decode_stream_payload(message)
    records = payload if isinstance(payload, list) else [payload]
    received_at = _utc_now_iso()
    events: list[AlpacaStreamEvent] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        events.append(_event_from_record(record, stream=stream, received_at=received_at))
    return events


def _decode_stream_payload(message: str | bytes) -> Any:
    text = message.decode("utf-8", errors="replace") if isinstance(message, bytes) else message
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise AlpacaStreamError(
            "Alpaca stream returned invalid JSON.",
            body=text,
            code="invalid_json",
        ) from exc


def _event_from_record(
    record: dict[str, Any],
    *,
    stream: str,
    received_at: str,
) -> AlpacaStreamEvent:
    message_type = str(record.get("T") or record.get("stream") or "unknown")
    news = _news_from_record(record) if message_type == "n" else None
    return AlpacaStreamEvent(
        stream=stream,
        message_type=message_type,
        symbol=_event_symbol(record, news),
        received_at=received_at,
        raw=record,
        news=news,
    )


def _news_from_record(record: dict[str, Any]) -> AlpacaNewsEvent:
    return AlpacaNewsEvent(
        id=_safe_int(record.get("id")),
        headline=_optional_text(record.get("headline")),
        summary=_optional_text(record.get("summary")),
        content=_optional_text(record.get("content")),
        author=_optional_text(record.get("author")),
        created_at=_optional_text(record.get("created_at")),
        updated_at=_optional_text(record.get("updated_at")),
        url=_optional_text(record.get("url")),
        symbols=_clean_symbols(record.get("symbols") or [], allow_wildcard=False),
        source=_optional_text(record.get("source")),
    )


def _event_symbol(record: dict[str, Any], news: AlpacaNewsEvent | None) -> str | None:
    symbol = _optional_text(record.get("S"))
    if symbol:
        return symbol.upper()
    if news is not None and len(news.symbols) == 1:
        return news.symbols[0]
    return None


def _normalize_stock_feed(feed: str) -> str:
    normalized = str(feed or "iex").strip().lower().strip("/")
    if "/" in normalized:
        return normalized
    if normalized in {"sip", "iex", "delayed_sip"}:
        return f"v2/{normalized}"
    if normalized in {"boats", "overnight"}:
        return f"v1beta1/{normalized}"
    raise ValueError(f"Unsupported Alpaca stock stream feed '{feed}'.")


def _clean_symbols(
    symbols: list[str] | tuple[str, ...],
    *,
    allow_wildcard: bool,
) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in symbols:
        symbol = str(raw or "").strip().upper()
        if not symbol:
            continue
        if symbol == "*" and not allow_wildcard:
            continue
        if symbol in seen:
            continue
        seen.add(symbol)
        cleaned.append(symbol)
    return cleaned


def _stream_error_code(code: Any) -> str:
    mapping = {
        400: "invalid_syntax",
        401: "not_authenticated",
        402: "auth_failed",
        403: "already_authenticated",
        404: "auth_timeout",
        405: "symbol_limit_exceeded",
        406: "connection_limit_exceeded",
        407: "slow_client",
        409: "insufficient_subscription",
        410: "invalid_subscribe_action",
        500: "internal_error",
    }
    return mapping.get(_safe_int(code), "stream_error")


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
