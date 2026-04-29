from __future__ import annotations

import json
from typing import Any

from t212ai.genai.tools.scrape_article import scrape_article, scrape_page
from t212ai.genai.tools.search_registry import SearchResultRegistry
from t212ai.genai.tools.searxng import searxng_search


class _Headers:
    def get_content_charset(self) -> str:
        return "utf-8"


class _FakeResponse:
    headers = _Headers()

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def _page_html(title: str = "Example Page") -> bytes:
    return f"""
    <html>
      <head>
        <title>{title}</title>
        <meta property="article:published_time" content="2026-04-29T10:00:00Z">
      </head>
      <body>
        <main>
          <h1>{title}</h1>
          <p>First paragraph with useful market context.</p>
          <p>Second paragraph with additional detail.</p>
        </main>
      </body>
    </html>
    """.encode()


def test_scrape_page_extracts_page_payload_and_article_alias(monkeypatch) -> None:
    import t212ai.genai.tools.scrape_article as scrape_module

    monkeypatch.setattr(scrape_module, "trafilatura", None)
    monkeypatch.setattr(scrape_module, "BeautifulSoup", None)

    captured: dict[str, Any] = {}

    def _fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return _FakeResponse(_page_html())

    monkeypatch.setattr(scrape_module.urllib.request, "urlopen", _fake_urlopen)
    registry = SearchResultRegistry()

    result = scrape_page(
        url="https://example.com/news",
        include_images=False,
        timeout_seconds=5,
        runtime=registry,
    )

    assert result.status == "ok"
    assert captured == {"url": "https://example.com/news", "timeout": 5.0}
    assert result.data["url_id"] == "url-1"
    assert result.data["page"]["url"] == "https://example.com/news"
    assert result.data["page"]["title"] == "Example Page"
    assert result.data["page"]["published_at"] == "2026-04-29T10:00:00Z"
    assert "First paragraph" in result.data["page"]["excerpt"]

    alias = scrape_article(url_id="url-1", include_images=False, runtime=registry)

    assert alias.status == "ok"
    assert "article" in alias.data
    assert alias.data["article"]["url"] == "https://example.com/news"
    assert "page" not in alias.data


def test_searxng_search_can_enrich_top_results_with_compact_page_context(
    monkeypatch,
) -> None:
    import t212ai.genai.tools.scrape_article as scrape_module
    import t212ai.genai.tools.searxng as searxng_module

    monkeypatch.setattr(scrape_module, "trafilatura", None)
    monkeypatch.setattr(scrape_module, "BeautifulSoup", None)

    def _fake_urlopen(request, timeout):
        del timeout
        if request.full_url.startswith("https://search.local/search?"):
            payload = {
                "results": [
                    {
                        "title": "Result One",
                        "url": "https://example.com/one",
                        "content": "Raw SearXNG snippet one.",
                        "engine": "duckduckgo",
                    },
                    {
                        "title": "Result Two",
                        "url": "https://example.com/two",
                        "content": "Raw SearXNG snippet two.",
                        "engine": "brave",
                    },
                ]
            }
            return _FakeResponse(json.dumps(payload).encode())
        if request.full_url == "https://example.com/one":
            return _FakeResponse(_page_html("Scraped Result One"))
        if request.full_url == "https://example.com/two":
            return _FakeResponse(_page_html("Scraped Result Two"))
        raise AssertionError(f"unexpected URL {request.full_url}")

    monkeypatch.setattr(searxng_module.urllib.request, "urlopen", _fake_urlopen)

    result = searxng_search(
        query="market news",
        base_url="https://search.local",
        max_results=2,
        scrape_results=True,
        scrape_top_n=1,
        include_scraped_text=False,
    )

    assert result.status == "ok"
    assert result.data["meta"]["scrape"]["enabled"] is True
    assert result.data["meta"]["scrape"]["scraped_count"] == 1
    assert len(result.data["results"]) == 2
    assert result.data["results"][0]["page"]["title"] == "Scraped Result One"
    assert "First paragraph" in result.data["results"][0]["page"]["excerpt"]
    assert "text" not in result.data["results"][0]["page"]
    assert result.data["results"][0]["page_scrape"]["status"] == "ok"
    assert "page" not in result.data["results"][1]
