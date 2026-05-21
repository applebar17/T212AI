"""Public Reddit JSON client for read-only research flows."""

from __future__ import annotations

from collections.abc import Mapping
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from t212ai.app.config import AppSettings, get_app_settings

from .models import RedditApiErrorContext


REDDIT_BASE_URL = "https://www.reddit.com"
REDDIT_DEFAULT_USER_AGENT = "t212ai/0.1 public-json-client"
REDDIT_MAX_LIMIT = 25


class RedditApiError(RuntimeError):
    def __init__(self, context: RedditApiErrorContext) -> None:
        super().__init__(context.message or "Reddit public JSON request failed.")
        self.context = context


class RedditClient:
    def __init__(
        self,
        *,
        user_agent: str | None = None,
        base_url: str = REDDIT_BASE_URL,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.user_agent = str(user_agent or REDDIT_DEFAULT_USER_AGENT).strip()
        self.base_url = str(base_url or REDDIT_BASE_URL).strip().rstrip("/")
        self.timeout_seconds = float(timeout_seconds)

    @classmethod
    def from_settings(cls, settings: AppSettings | None = None) -> "RedditClient":
        resolved = settings or get_app_settings()
        return cls(
            user_agent=resolved.reddit_user_agent,
            base_url=resolved.reddit_base_url,
        )

    def search(
        self,
        query: str,
        *,
        subreddit: str | None = None,
        sort: str = "relevance",
        time: str = "month",
        limit: int = 10,
        after: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "q": _required_text(query, "query"),
            "sort": sort,
            "t": time,
            "limit": _bounded_limit(limit),
            "raw_json": 1,
            "type": "link",
        }
        path = "/search.json"
        if subreddit:
            params["restrict_sr"] = 1
            path = f"/r/{_clean_subreddit(subreddit)}/search.json"
        if after:
            params["after"] = after
        payload = self._get_json(path, params=params, operation="search")
        if not isinstance(payload, dict):
            raise self._unexpected_payload("search", path, payload)
        return payload

    def subreddit_listing(
        self,
        subreddit: str,
        *,
        listing: str = "hot",
        time: str | None = None,
        limit: int = 10,
        after: str | None = None,
    ) -> dict[str, Any]:
        resolved_listing = _required_text(listing, "listing").lower()
        params: dict[str, Any] = {
            "limit": _bounded_limit(limit),
            "raw_json": 1,
        }
        if time:
            params["t"] = time
        if after:
            params["after"] = after
        path = f"/r/{_clean_subreddit(subreddit)}/{resolved_listing}.json"
        payload = self._get_json(path, params=params, operation="subreddit_listing")
        if not isinstance(payload, dict):
            raise self._unexpected_payload("subreddit_listing", path, payload)
        return payload

    def comments(
        self,
        subreddit: str,
        post_id: str,
        *,
        sort: str = "confidence",
        limit: int = 10,
        depth: int = 3,
    ) -> list[dict[str, Any]]:
        params = {
            "sort": sort,
            "limit": _bounded_limit(limit),
            "depth": _bounded(depth, minimum=1, maximum=10),
            "raw_json": 1,
        }
        path = f"/r/{_clean_subreddit(subreddit)}/comments/{_clean_post_id(post_id)}.json"
        payload = self._get_json(path, params=params, operation="comments")
        if not isinstance(payload, list):
            raise self._unexpected_payload("comments", path, payload)
        return payload

    def _get_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None,
        operation: str,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        query = urllib.parse.urlencode(
            {key: value for key, value in (params or {}).items() if value is not None}
        )
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
            },
        )
        return self._read_json_request(request, operation=operation)

    def _read_json_request(
        self,
        request: urllib.request.Request,
        *,
        operation: str,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raw_body = exc.read().decode("utf-8", errors="replace")
            raise RedditApiError(
                RedditApiErrorContext(
                    operation=operation,
                    endpoint=request.full_url,
                    status_code=exc.code,
                    message=f"Reddit HTTP {exc.code} during {operation}.",
                    retryable=exc.code >= 500 or exc.code == 429,
                    details={"body": raw_body[:600]},
                )
            ) from exc
        except urllib.error.URLError as exc:
            raise RedditApiError(
                RedditApiErrorContext(
                    operation=operation,
                    endpoint=request.full_url,
                    message=f"Network error contacting Reddit: {exc.reason}",
                    retryable=True,
                )
            ) from exc

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RedditApiError(
                RedditApiErrorContext(
                    operation=operation,
                    endpoint=request.full_url,
                    message="Reddit returned invalid JSON.",
                    retryable=False,
                    details={"body": raw[:600]},
                )
            ) from exc

        if isinstance(payload, dict):
            _raise_for_api_error(payload, operation=operation, endpoint=request.full_url)
        elif not isinstance(payload, list):
            raise self._unexpected_payload(operation, request.full_url, payload)
        return payload

    @staticmethod
    def _unexpected_payload(
        operation: str,
        endpoint: str,
        payload: object,
    ) -> RedditApiError:
        return RedditApiError(
            RedditApiErrorContext(
                operation=operation,
                endpoint=endpoint,
                message="Reddit returned an unsupported payload type.",
                retryable=False,
                details={"payload_type": type(payload).__name__},
            )
        )


def _raise_for_api_error(
    payload: dict[str, Any],
    *,
    operation: str,
    endpoint: str,
) -> None:
    for key in ("error", "message", "reason"):
        if key not in payload:
            continue
        value = payload.get(key)
        if key == "error" and value in (None, 0, "0"):
            continue
        raise RedditApiError(
            RedditApiErrorContext(
                operation=operation,
                endpoint=endpoint,
                message=f"Reddit API returned {key}: {value}",
                retryable=value in {429, "RATELIMIT"},
                details={"payload_keys": list(payload.keys())[:20]},
            )
        )


def _required_text(value: str, field_name: str) -> str:
    resolved = str(value or "").strip()
    if not resolved:
        raise ValueError(f"{field_name} is required.")
    return resolved


def _bounded(value: int, *, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def _bounded_limit(value: int) -> int:
    return _bounded(value, minimum=1, maximum=REDDIT_MAX_LIMIT)


def _clean_subreddit(value: str) -> str:
    resolved = _required_text(value, "subreddit")
    return resolved.removeprefix("r/").strip("/")


def _clean_post_id(value: str) -> str:
    resolved = _required_text(value, "post_id")
    return resolved.removeprefix("t3_").strip("/")
