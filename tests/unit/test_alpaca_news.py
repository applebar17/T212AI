from __future__ import annotations

from t212ai.alpaca.news import clean_alpaca_news_event, clean_news_payload
from t212ai.alpaca.streaming import AlpacaNewsEvent


def test_clean_news_payload_strips_html_unescapes_and_dedupes_symbols() -> None:
    packet = clean_news_payload(
        {
            "id": "123",
            "headline": " MP&nbsp;Materials raises guidance ",
            "summary": "<p>Fresh&nbsp;update</p>",
            "content": "<div>Rare earth <strong>demand</strong> &amp; margins improve.</div>",
            "url": "https://example.test/news/mp",
            "symbols": ["mp", "USAR", "mp"],
            "source": "benzinga",
            "created_at": "2026-05-11T10:00:00Z",
            "updated_at": "2026-05-11T10:01:00Z",
            "received_at": "2026-05-11T10:01:05Z",
        }
    )

    assert packet.id == 123
    assert packet.headline == "MP Materials raises guidance"
    assert packet.summary == "Fresh update"
    assert packet.content_text == "Rare earth demand & margins improve."
    assert packet.symbols == ["MP", "USAR"]
    assert packet.dedupe_key == "benzinga:123"
    assert packet.received_at == "2026-05-11T10:01:05Z"


def test_clean_alpaca_news_event_truncates_and_falls_back_to_url_dedupe() -> None:
    news = AlpacaNewsEvent(
        id=None,
        headline="Long form article",
        summary="Summary",
        content="<p>" + ("x" * 80) + "</p>",
        author="Author",
        created_at="2026-05-11T10:00:00Z",
        updated_at="2026-05-11T10:01:00Z",
        url="https://example.test/news/fallback",
        symbols=["mp"],
        source=None,
    )

    packet = clean_alpaca_news_event(news, received_at="2026-05-11T10:01:05Z", content_limit=40)

    assert packet.content_text is not None
    assert packet.content_text.endswith("... [truncated]")
    assert packet.dedupe_key == "url:https://example.test/news/fallback"
    assert packet.symbols == ["MP"]
