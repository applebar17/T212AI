"""SearXNG web-search tool."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..models import ToolError, ToolResult, ToolSpec
from ..tracing import traceable
from .search_registry import SearchResultRegistry


DEFAULT_SEARXNG_TIMEOUT_SECONDS = 20.0
DEFAULT_SEARXNG_LANG = "en"
DEFAULT_SEARXNG_PAGE = 1
DEFAULT_SEARXNG_SAFESEARCH = 1
DEFAULT_SEARXNG_FORMAT = "json"
DEFAULT_SEARXNG_MAX_RESULTS = 8
MAX_SEARXNG_MAX_RESULTS = 20
DEFAULT_USER_AGENT = "t212ai-searxng/1.0"
SEARXNG_BASE_URL_ENV = "SEARXNG_BASE_URL"
LOGGER = logging.getLogger(__name__)


SEARXNG_SEARCH_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "searxng_search",
        "description": (
            "Search the internet via a SearXNG instance and return normalized web results. "
            "Results include title, snippet, url, source, and a url_id that can be passed to scrape_article."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query to send to SearXNG.",
                },
                "categories": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Comma-separated categories list (for example general,news).",
                },
                "language": {
                    "type": "string",
                    "default": DEFAULT_SEARXNG_LANG,
                    "description": "Language code (for example en, it, fr).",
                },
                "time_range": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Time filter (for example day, week, month, year).",
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_SEARXNG_MAX_RESULTS,
                    "default": DEFAULT_SEARXNG_MAX_RESULTS,
                    "description": "Maximum number of normalized results to return.",
                },
            },
            "required": ["query", "categories", "language", "time_range", "max_results"],
            "additionalProperties": False,
        },
    },
}


@traceable(name="searxng_search", run_type="tool")
def searxng_search(
    *,
    query: str,
    categories: str | None = None,
    language: str = DEFAULT_SEARXNG_LANG,
    time_range: str | None = None,
    max_results: int = DEFAULT_SEARXNG_MAX_RESULTS,
    base_url: str | None = None,
    runtime: SearchResultRegistry | None = None,
    timeout_seconds: float = DEFAULT_SEARXNG_TIMEOUT_SECONDS,
) -> ToolResult:
    resolved_query = str(query or "").strip()
    if not resolved_query:
        return ToolResult(
            status="error",
            error=ToolError(
                message="query is required and cannot be empty.",
                code="missing_query",
                retryable=False,
            ),
        )

    try:
        resolved_max_results = max(1, min(int(max_results), MAX_SEARXNG_MAX_RESULTS))
        resolved_timeout = max(1.0, float(timeout_seconds))
    except (TypeError, ValueError):
        return ToolResult(
            status="error",
            error=ToolError(
                message="max_results and timeout_seconds must be numeric.",
                code="invalid_params",
                retryable=False,
            ),
        )

    resolved_base_url = _normalize_base_url(base_url or os.getenv(SEARXNG_BASE_URL_ENV))
    if not resolved_base_url:
        return ToolResult(
            status="error",
            error=ToolError(
                message="SearXNG base URL is not configured.",
                code="missing_searxng_base_url",
                hint=f"Set {SEARXNG_BASE_URL_ENV} or pass base_url explicitly.",
                retryable=False,
            ),
        )

    params = {
        "q": resolved_query,
        "language": language or DEFAULT_SEARXNG_LANG,
        "pageno": DEFAULT_SEARXNG_PAGE,
        "safesearch": DEFAULT_SEARXNG_SAFESEARCH,
        "format": DEFAULT_SEARXNG_FORMAT,
    }
    if categories:
        params["categories"] = categories
    if time_range:
        params["time_range"] = time_range

    url = f"{resolved_base_url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=resolved_timeout) as response:
            payload = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return ToolResult(
            status="error",
            error=ToolError(
                message=f"SearXNG request failed with HTTP {exc.code}.",
                code="http_error",
                type=exc.__class__.__name__,
                hint="Verify the endpoint and retry.",
                retryable=exc.code >= 500 or exc.code == 429,
                details={"status_code": exc.code, "url": url},
            ),
        )
    except urllib.error.URLError as exc:
        return ToolResult(
            status="error",
            error=ToolError(
                message=f"Network error contacting SearXNG: {exc.reason}",
                code="request_failed",
                type=exc.__class__.__name__,
                hint="Check network connectivity and retry.",
                retryable=True,
                details={"url": url},
            ),
        )
    except Exception as exc:  # pragma: no cover
        return ToolResult(
            status="error",
            error=ToolError(
                message=f"Unexpected error contacting SearXNG: {exc}",
                code="request_failed",
                type=exc.__class__.__name__,
                hint="Retry the query or inspect logs for details.",
                retryable=False,
            ),
        )

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        return ToolResult(
            status="error",
            error=ToolError(
                message="SearXNG returned invalid JSON.",
                code="invalid_json",
                type=exc.__class__.__name__,
                hint="Check the configured SearXNG endpoint.",
                retryable=False,
                details={"url": url},
            ),
        )

    raw_results = parsed.get("results") or []
    registry = runtime or SearchResultRegistry(prefix="url")
    normalized_results: list[dict[str, Any]] = []
    for item in raw_results:
        normalized = _normalize_result(item)
        if not normalized.get("url"):
            continue
        url_id = registry.register(
            url=normalized["url"],
            payload=normalized,
            discovered_via="searxng_search",
            source_name=normalized.get("source"),
            title=normalized.get("title"),
            image_url=normalized.get("thumbnail"),
            published_at=normalized.get("published_at"),
        )
        normalized["url_id"] = url_id
        normalized_results.append(normalized)
        if len(normalized_results) >= resolved_max_results:
            break

    output = (
        f"Found {len(normalized_results)} web results for '{resolved_query}'."
        if normalized_results
        else f"No web results found for '{resolved_query}'."
    )
    return ToolResult(
        status="ok",
        output=output,
        data={
            "results": normalized_results,
            "meta": {
                "query": resolved_query,
                "categories": categories,
                "language": language,
                "time_range": time_range,
                "max_results": resolved_max_results,
                "base_url": resolved_base_url,
            },
        },
    )


def _normalize_base_url(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = urllib.parse.urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return None
    path = parsed.path.rstrip("/")
    if not path.endswith("/search"):
        path = f"{path}/search" if path else "/search"
    normalized = parsed._replace(path=path, params="", query="", fragment="")
    return urllib.parse.urlunparse(normalized)


def _normalize_result(item: dict[str, Any]) -> dict[str, Any]:
    url = _clean_text(item.get("url"))
    source = _clean_text(item.get("source")) or _hostname(url)
    content = _clean_text(item.get("content")) or _clean_text(item.get("snippet"))
    return {
        "title": _clean_text(item.get("title")),
        "url": url,
        "source": source,
        "content": content,
        "published_at": _clean_text(
            item.get("publishedDate") or item.get("published_at") or item.get("date")
        ),
        "engine": _clean_text(item.get("engine")),
        "category": _clean_text(item.get("category")),
        "thumbnail": _clean_text(item.get("thumbnail")),
    }


def _hostname(url: str | None) -> str | None:
    parsed = urllib.parse.urlparse(str(url or "").strip())
    return parsed.netloc or None


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
