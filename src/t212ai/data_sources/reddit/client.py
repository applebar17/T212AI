"""Reddit Data API client for read-only research flows."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from datetime import datetime, timezone
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from t212ai.app.config import AppSettings, get_app_settings

from .models import RedditAccessToken, RedditApiErrorContext


REDDIT_BASE_URL = "https://oauth.reddit.com"
REDDIT_AUTH_URL = "https://www.reddit.com/api/v1/access_token"


class RedditApiError(RuntimeError):
    def __init__(self, context: RedditApiErrorContext) -> None:
        super().__init__(context.message or "Reddit API request failed.")
        self.context = context


class RedditClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        user_agent: str,
        username: str | None = None,
        password: str | None = None,
        refresh_token: str | None = None,
        base_url: str = REDDIT_BASE_URL,
        auth_url: str = REDDIT_AUTH_URL,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.client_id = _required_text(client_id, "client_id")
        self.client_secret = _required_text(client_secret, "client_secret")
        self.user_agent = _required_text(user_agent, "user_agent")
        self.username = str(username or "").strip() or None
        self.password = str(password or "").strip() or None
        self.refresh_token = str(refresh_token or "").strip() or None
        self.base_url = base_url.rstrip("/")
        self.auth_url = auth_url
        self.timeout_seconds = float(timeout_seconds)
        self._access_token: RedditAccessToken | None = None

        if not self.refresh_token and not (self.username and self.password):
            raise RuntimeError(
                "Reddit credentials are incomplete. Provide REDDIT_REFRESH_TOKEN or "
                "REDDIT_USERNAME and REDDIT_PASSWORD."
            )

    @classmethod
    def from_settings(cls, settings: AppSettings | None = None) -> "RedditClient":
        resolved = settings or get_app_settings()
        if not resolved.reddit_client_id or not resolved.reddit_client_secret:
            raise RuntimeError(
                "REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are required."
            )
        user_agent = resolved.reddit_user_agent or _default_user_agent(
            resolved.reddit_username
        )
        return cls(
            client_id=resolved.reddit_client_id,
            client_secret=resolved.reddit_client_secret,
            username=resolved.reddit_username,
            password=resolved.reddit_password,
            refresh_token=resolved.reddit_refresh_token,
            user_agent=user_agent,
            base_url=resolved.reddit_base_url,
            auth_url=resolved.reddit_auth_url,
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
            "limit": _bounded(limit, minimum=1, maximum=100),
            "raw_json": 1,
            "type": "link",
        }
        path = "/search"
        if subreddit:
            params["restrict_sr"] = 1
            path = f"/r/{_clean_subreddit(subreddit)}/search"
        if after:
            params["after"] = after
        return self._get_json(path, params=params, operation="search")

    def subreddit_about(self, subreddit: str) -> dict[str, Any]:
        path = f"/r/{_clean_subreddit(subreddit)}/about"
        return self._get_json(path, params={"raw_json": 1}, operation="subreddit_about")

    def subreddit_listing(
        self,
        subreddit: str,
        *,
        listing: str = "hot",
        time: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        resolved_listing = _required_text(listing, "listing").lower()
        params: dict[str, Any] = {
            "limit": _bounded(limit, minimum=1, maximum=100),
            "raw_json": 1,
        }
        if time:
            params["t"] = time
        path = f"/r/{_clean_subreddit(subreddit)}/{resolved_listing}"
        return self._get_json(path, params=params, operation="subreddit_listing")

    def comments(
        self,
        subreddit: str,
        post_id: str,
        *,
        sort: str = "confidence",
        limit: int = 20,
        depth: int = 3,
    ) -> list[dict[str, Any]]:
        params = {
            "sort": sort,
            "limit": _bounded(limit, minimum=1, maximum=100),
            "depth": _bounded(depth, minimum=1, maximum=10),
            "raw_json": 1,
        }
        path = f"/r/{_clean_subreddit(subreddit)}/comments/{_clean_post_id(post_id)}"
        payload = self._get_json(path, params=params, operation="comments")
        if not isinstance(payload, list):
            raise RedditApiError(
                RedditApiErrorContext(
                    operation="comments",
                    endpoint=path,
                    message="Reddit comments endpoint returned a non-list payload.",
                    retryable=False,
                )
            )
        return payload

    def _get_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None,
        operation: str,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        token = self._ensure_token()
        query = urllib.parse.urlencode(
            {key: value for key, value in (params or {}).items() if value is not None}
        )
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"bearer {token.access_token}",
                "User-Agent": self.user_agent,
            },
        )
        return self._read_json_request(request, operation=operation)

    def _ensure_token(self) -> RedditAccessToken:
        if self._access_token is None or self._access_token.is_expired():
            self._access_token = self._authenticate()
        return self._access_token

    def _authenticate(self) -> RedditAccessToken:
        form = self._build_auth_form()
        headers = {
            "Authorization": _basic_auth_header(self.client_id, self.client_secret),
            "User-Agent": self.user_agent,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        request = urllib.request.Request(
            self.auth_url,
            data=urllib.parse.urlencode(form).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        payload = self._read_json_request(request, operation="authenticate")
        if not isinstance(payload, dict):
            raise RedditApiError(
                RedditApiErrorContext(
                    operation="authenticate",
                    endpoint=self.auth_url,
                    message="Reddit auth endpoint returned a non-object payload.",
                    retryable=False,
                )
            )
        access_token = payload.get("access_token")
        if not access_token:
            raise RedditApiError(
                RedditApiErrorContext(
                    operation="authenticate",
                    endpoint=self.auth_url,
                    message="Reddit auth endpoint did not return an access token.",
                    retryable=False,
                    details={"payload_keys": list(payload.keys())[:20]},
                )
            )
        return RedditAccessToken(
            access_token=str(access_token),
            token_type=str(payload.get("token_type") or "bearer"),
            expires_in=int(payload.get("expires_in") or 3600),
            scope=str(payload.get("scope") or "").strip() or None,
            issued_at=datetime.now(timezone.utc),
        )

    def _build_auth_form(self) -> dict[str, Any]:
        if self.refresh_token:
            return {"grant_type": "refresh_token", "refresh_token": self.refresh_token}
        return {
            "grant_type": "password",
            "username": _required_text(self.username or "", "username"),
            "password": _required_text(self.password or "", "password"),
        }

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
            raise RedditApiError(
                RedditApiErrorContext(
                    operation=operation,
                    endpoint=request.full_url,
                    message="Reddit returned an unsupported payload type.",
                    retryable=False,
                    details={"payload_type": type(payload).__name__},
                )
            )
        return payload


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


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _default_user_agent(username: str | None) -> str:
    handle = str(username or "unknown").strip() or "unknown"
    return f"server:t212ai:v0.1.0 (by /u/{handle})"


def _required_text(value: str, field_name: str) -> str:
    resolved = str(value or "").strip()
    if not resolved:
        raise ValueError(f"{field_name} is required.")
    return resolved


def _bounded(value: int, *, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def _clean_subreddit(value: str) -> str:
    resolved = _required_text(value, "subreddit")
    return resolved.removeprefix("r/").strip("/")


def _clean_post_id(value: str) -> str:
    resolved = _required_text(value, "post_id")
    return resolved.removeprefix("t3_").strip("/")
