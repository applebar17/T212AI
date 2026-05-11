from __future__ import annotations

import asyncio
import json

from t212ai.alpaca.market_data import AlpacaMarketDataClient
from t212ai.alpaca.streaming import (
    AlpacaNewsEvent,
    AlpacaStreamClient,
    AlpacaStreamError,
    AlpacaStreamEvent,
    AlpacaStreamSubscription,
    capture_alpaca_news_stream,
    parse_stream_message,
)


def _client() -> AlpacaStreamClient:
    return AlpacaStreamClient(
        api_key="alpaca-key",
        api_secret="alpaca-secret",
        data_feed="iex",
    )


def test_alpaca_stream_url_construction() -> None:
    client = _client()

    assert client.news_stream_url() == "wss://stream.data.alpaca.markets/v1beta1/news"
    assert client.stock_stream_url() == "wss://stream.data.alpaca.markets/v2/iex"
    assert client.stock_stream_url(feed="sip") == "wss://stream.data.alpaca.markets/v2/sip"
    assert (
        client.stock_stream_url(feed="boats")
        == "wss://stream.data.alpaca.markets/v1beta1/boats"
    )
    assert (
        client.test_stream_url(sandbox=True)
        == "wss://stream.data.sandbox.alpaca.markets/v2/test"
    )


def test_market_data_client_exposes_stream_urls() -> None:
    client = AlpacaMarketDataClient(
        api_key="alpaca-key",
        api_secret="alpaca-secret",
        data_feed="delayed_sip",
    )

    assert client.news_stream_url().endswith("/v1beta1/news")
    assert client.stock_stream_url().endswith("/v2/delayed_sip")


def test_subscription_message_omits_empty_channels_and_keeps_wildcard() -> None:
    subscription = AlpacaStreamSubscription(
        news=["*"],
        trades=["aapl", "AAPL", "msft"],
        bars=[],
    )

    assert subscription.to_message() == {
        "action": "subscribe",
        "news": ["*"],
        "trades": ["AAPL", "MSFT"],
    }


def test_parse_stream_message_handles_control_and_news_batches() -> None:
    events = parse_stream_message(
        json.dumps(
            [
                {"T": "success", "msg": "authenticated"},
                {"T": "subscription", "news": ["*"]},
                {
                    "T": "n",
                    "id": 123,
                    "headline": "MP Materials signs supply agreement",
                    "summary": "Summary",
                    "author": "Benzinga Newsdesk",
                    "created_at": "2026-05-11T10:00:00Z",
                    "updated_at": "2026-05-11T10:00:01Z",
                    "content": "<p>Body</p>",
                    "url": "https://example.test/news",
                    "symbols": ["mp", "usar"],
                    "source": "benzinga",
                },
            ]
        ),
        stream="news",
    )

    assert [event.message_type for event in events] == ["success", "subscription", "n"]
    news_event = events[-1]
    assert news_event.symbol is None
    assert news_event.news is not None
    assert news_event.news.id == 123
    assert news_event.news.symbols == ["MP", "USAR"]
    assert news_event.to_news_record()["headline"] == (
        "MP Materials signs supply agreement"
    )


def test_stream_error_maps_provider_error_code() -> None:
    event = parse_stream_message(
        '[{"T":"error","code":406,"msg":"connection limit exceeded"}]',
        stream="news",
    )[0]

    error = AlpacaStreamError.from_event(event)

    assert error.status_code == 406
    assert error.code == "connection_limit_exceeded"
    assert "connection limit exceeded" in str(error)


def test_capture_alpaca_news_stream_appends_jsonl_and_filters_symbols(tmp_path) -> None:
    class FakeStreamClient:
        async def connect_and_subscribe(self, *_args, **_kwargs):
            yield _news_stream_event(1, ["AAPL"])
            yield _news_stream_event(2, ["MP"])
            yield _news_stream_event(3, ["USAR"])

    output_path = tmp_path / "news.jsonl"

    result = asyncio.run(
        capture_alpaca_news_stream(
            FakeStreamClient(),  # type: ignore[arg-type]
            output_path,
            symbols=["MP", "USAR"],
            max_events=2,
        )
    )

    lines = output_path.read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    assert result.received_count == 3
    assert result.written_count == 2
    assert result.skipped_count == 1
    assert [record["id"] for record in records] == [2, 3]
    assert records[0]["symbols"] == ["MP"]
    assert records[0]["raw"]["id"] == 2


def _news_stream_event(identifier: int, symbols: list[str]) -> AlpacaStreamEvent:
    raw = {
        "T": "n",
        "id": identifier,
        "headline": f"Headline {identifier}",
        "summary": "Summary",
        "content": "Content",
        "author": "Author",
        "created_at": "2026-05-11T10:00:00Z",
        "updated_at": "2026-05-11T10:00:01Z",
        "url": "https://example.test/news",
        "symbols": symbols,
        "source": "benzinga",
    }
    return AlpacaStreamEvent(
        stream="news",
        message_type="n",
        symbol=symbols[0] if len(symbols) == 1 else None,
        received_at="2026-05-11T10:00:02Z",
        raw=raw,
        news=AlpacaNewsEvent(
            id=identifier,
            headline=f"Headline {identifier}",
            summary="Summary",
            content="Content",
            author="Author",
            created_at="2026-05-11T10:00:00Z",
            updated_at="2026-05-11T10:00:01Z",
            url="https://example.test/news",
            symbols=symbols,
            source="benzinga",
        ),
    )
