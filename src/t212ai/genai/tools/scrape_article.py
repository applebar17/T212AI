"""Article/page scraping tool."""

from __future__ import annotations

import html
from html.parser import HTMLParser
import re
import urllib.parse
import urllib.request
from typing import Any

from ..models import ToolError, ToolResult, ToolSpec
from ..tracing import traceable
from .search_registry import SearchResultRegistry

try:  # pragma: no cover - optional dependency
    import trafilatura  # type: ignore
except Exception:  # pragma: no cover
    trafilatura = None  # type: ignore

try:  # pragma: no cover - optional dependency
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover
    BeautifulSoup = None  # type: ignore


DEFAULT_MAX_IMAGES = 5
DEFAULT_SCRAPE_TIMEOUT_SECONDS = 20.0
DEFAULT_USER_AGENT = "t212ai-article-scraper/1.0"


SCRAPE_ARTICLE_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "scrape_article",
        "description": (
            "Fetch a web page URL and extract the main article text plus optional "
            "image URLs. Prefer url_id from searxng_search when available."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Optional full article URL to fetch and extract.",
                },
                "url_id": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": (
                        "Optional id returned by searxng_search (for example url-1)."
                    ),
                },
                "include_images": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to include related image URLs.",
                },
                "max_images": {
                    "type": "integer",
                    "minimum": 0,
                    "default": DEFAULT_MAX_IMAGES,
                    "description": "Maximum number of image URLs to return.",
                },
                "timeout_seconds": {
                    "type": "number",
                    "minimum": 1,
                    "default": DEFAULT_SCRAPE_TIMEOUT_SECONDS,
                    "description": "Network timeout for fetching the URL.",
                },
            },
            "required": ["url", "url_id", "include_images", "max_images", "timeout_seconds"],
            "additionalProperties": False,
        },
    },
}


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        elif tag in {"p", "br", "div", "section", "article", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in {"p", "br", "div", "section", "article", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self.parts.append(data.strip())

    def text(self) -> str:
        raw = " ".join(self.parts)
        return _clean_text(raw)


@traceable(name="scrape_article", run_type="tool")
def scrape_article(
    *,
    url: str | None = None,
    url_id: str | None = None,
    include_images: bool = True,
    max_images: int = DEFAULT_MAX_IMAGES,
    timeout_seconds: float = DEFAULT_SCRAPE_TIMEOUT_SECONDS,
    runtime: SearchResultRegistry | None = None,
    **kwargs: Any,
) -> ToolResult:
    if kwargs:
        return ToolResult(
            status="error",
            error=ToolError(
                message="Unexpected parameters received by scrape_article.",
                code="unexpected_params",
                hint="Remove unsupported fields and retry with the documented schema.",
                retryable=False,
                details={"unexpected_params": sorted(kwargs.keys())},
            ),
        )

    requested_url_id = str(url_id or "").strip() or None
    target_url = str(url or "").strip()

    if requested_url_id:
        if runtime is None:
            return ToolResult(
                status="error",
                error=ToolError(
                    message="url_id cannot be resolved in this runtime.",
                    code="url_id_unavailable",
                    hint="Call scrape_article with a direct url or after searxng_search in the same tool session.",
                    retryable=False,
                    details={"url_id": requested_url_id},
                ),
            )
        mapped_url = runtime.resolve_url(requested_url_id)
        if not mapped_url:
            return ToolResult(
                status="error",
                error=ToolError(
                    message="Unknown url_id for scrape_article.",
                    code="unknown_url_id",
                    hint="Use a url_id returned by searxng_search in this same tool session.",
                    retryable=False,
                    details={
                        "url_id": requested_url_id,
                        "known_url_ids": runtime.known_ids(limit=15),
                    },
                ),
            )
        target_url = mapped_url

    if not target_url:
        return ToolResult(
            status="error",
            error=ToolError(
                message="url or url_id is required and cannot be empty.",
                code="missing_url",
                hint="Provide url_id from searxng_search or a full https:// URL.",
                retryable=False,
            ),
        )

    parsed = urllib.parse.urlparse(target_url)
    if parsed.scheme not in {"http", "https"}:
        return ToolResult(
            status="error",
            error=ToolError(
                message="url must start with http:// or https://",
                code="invalid_url",
                hint="Provide a valid web URL.",
                retryable=False,
                details={"url": target_url},
            ),
        )

    try:
        resolved_max_images = int(max_images)
        resolved_timeout = float(timeout_seconds)
    except (TypeError, ValueError):
        return ToolResult(
            status="error",
            error=ToolError(
                message="max_images and timeout_seconds must be numeric.",
                code="invalid_params",
                hint="Use a non-negative max_images and timeout_seconds >= 1.",
                retryable=False,
            ),
        )
    if resolved_max_images < 0 or resolved_timeout < 1:
        return ToolResult(
            status="error",
            error=ToolError(
                message="max_images must be >= 0 and timeout_seconds must be >= 1.",
                code="invalid_params",
                hint="Use a non-negative max_images and timeout_seconds >= 1.",
                retryable=False,
                details={
                    "max_images": resolved_max_images,
                    "timeout_seconds": resolved_timeout,
                },
            ),
        )

    try:
        html_text = _fetch_html(target_url, timeout_seconds=resolved_timeout)
        article = _extract_article(
            target_url,
            html_text,
            include_images=bool(include_images),
            max_images=resolved_max_images,
        )
    except urllib.error.HTTPError as exc:
        return ToolResult(
            status="error",
            error=ToolError(
                message=f"HTTP error while scraping article: {exc.code}",
                code="http_error",
                type=exc.__class__.__name__,
                hint="Retry later or use another source.",
                retryable=exc.code >= 500 or exc.code == 429,
                details={"url": target_url, "status_code": exc.code},
            ),
        )
    except urllib.error.URLError as exc:
        return ToolResult(
            status="error",
            error=ToolError(
                message=f"Network error while scraping article: {exc.reason}",
                code="request_failed",
                type=exc.__class__.__name__,
                hint="Check connectivity and retry.",
                retryable=True,
                details={"url": target_url},
            ),
        )
    except Exception as exc:  # pragma: no cover
        return ToolResult(
            status="error",
            error=ToolError(
                message=f"scrape_article failed unexpectedly: {exc}",
                code="scrape_failed",
                type=exc.__class__.__name__,
                hint="Retry the call or inspect logs for more detail.",
                retryable=False,
            ),
        )

    payload = {
        "article": article,
        "request": {
            "url": target_url,
            "include_images": bool(include_images),
            "max_images": resolved_max_images,
            "timeout_seconds": resolved_timeout,
        },
    }

    resolved_url_id = requested_url_id
    if runtime is not None:
        resolved_url_id = runtime.register(
            url=target_url,
            payload=payload,
            discovered_via="scrape_article",
            source_name=urllib.parse.urlparse(target_url).netloc,
            title=article.get("title"),
            image_url=(article.get("images") or [None])[0],
            published_at=article.get("published_at"),
        )
        payload["url_id"] = resolved_url_id

    output = f"Extracted {article.get('text_length', 0)} characters from the requested page."
    if resolved_url_id:
        output = f"{output} Resolved via {resolved_url_id}."

    return ToolResult(status="ok", output=output, data=payload)


def _fetch_html(url: str, *, timeout_seconds: float) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _extract_article(
    url: str,
    html_text: str,
    *,
    include_images: bool,
    max_images: int,
) -> dict[str, Any]:
    title = _extract_title(html_text)
    published_at = _extract_published_at(html_text)
    text, extractor_name = _extract_text(html_text)
    images = _extract_images(url, html_text, max_images=max_images) if include_images else []
    excerpt = _build_excerpt(text)
    return {
        "url": url,
        "title": title,
        "published_at": published_at,
        "text": text,
        "text_length": len(text),
        "excerpt": excerpt,
        "images": images,
        "extractor": extractor_name,
    }


def _extract_text(html_text: str) -> tuple[str, str]:
    if trafilatura is not None:  # pragma: no branch
        try:
            extracted = trafilatura.extract(
                html_text,
                output_format="txt",
                include_links=False,
                include_images=False,
                favor_precision=True,
                deduplicate=True,
            )
            cleaned = _clean_text(extracted or "")
            if cleaned:
                return cleaned, "trafilatura"
        except Exception:
            pass

    if BeautifulSoup is not None:  # pragma: no branch
        try:
            soup = BeautifulSoup(html_text, "html.parser")
            for tag in soup(["script", "style", "noscript", "svg", "footer", "nav", "aside", "form"]):
                tag.decompose()
            root = soup.find("article") or soup.find("main") or soup.body or soup
            chunks: list[str] = []
            for element in root.find_all(["h1", "h2", "h3", "p", "li"]):
                text = _clean_text(element.get_text(" ", strip=True))
                if text:
                    chunks.append(text)
            cleaned = _clean_text("\n".join(chunks))
            if cleaned:
                return cleaned, "beautifulsoup"
        except Exception:
            pass

    parser = _HTMLTextExtractor()
    parser.feed(html_text)
    return parser.text(), "htmlparser"


def _extract_title(html_text: str) -> str | None:
    if BeautifulSoup is not None:  # pragma: no branch
        try:
            soup = BeautifulSoup(html_text, "html.parser")
            for selector in (
                ('meta[property="og:title"]', "content"),
                ('meta[name="twitter:title"]', "content"),
                ("title", None),
            ):
                element = soup.select_one(selector[0])
                if not element:
                    continue
                value = (
                    element.get(selector[1]) if selector[1] else element.get_text(" ", strip=True)
                )
                value = _clean_text(value or "")
                if value:
                    return value
        except Exception:
            pass

    match = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
    if match:
        return _clean_text(html.unescape(match.group(1)))
    return None


def _extract_published_at(html_text: str) -> str | None:
    patterns = [
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']pubdate["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']date["\'][^>]+content=["\']([^"\']+)["\']',
        r'<time[^>]+datetime=["\']([^"\']+)["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text, re.IGNORECASE)
        if match:
            value = _clean_text(match.group(1))
            if value:
                return value
    return None


def _extract_images(url: str, html_text: str, *, max_images: int) -> list[str]:
    if max_images <= 0:
        return []

    candidates: list[str] = []
    if BeautifulSoup is not None:  # pragma: no branch
        try:
            soup = BeautifulSoup(html_text, "html.parser")
            for selector in (
                ('meta[property="og:image"]', "content"),
                ('meta[name="twitter:image"]', "content"),
            ):
                element = soup.select_one(selector[0])
                if element and element.get(selector[1]):
                    candidates.append(str(element.get(selector[1])))
            for element in soup.find_all("img", src=True):
                candidates.append(str(element.get("src")))
        except Exception:
            pass

    out: list[str] = []
    for candidate in candidates:
        absolute = urllib.parse.urljoin(url, candidate)
        if absolute not in out and absolute.startswith(("http://", "https://")):
            out.append(absolute)
        if len(out) >= max_images:
            break
    return out


def _build_excerpt(text: str, max_chars: int = 400) -> str | None:
    if not text:
        return None
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def _clean_text(value: str) -> str:
    normalized = html.unescape(value or "")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()
