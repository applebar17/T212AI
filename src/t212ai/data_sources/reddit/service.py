"""Higher-level public Reddit research service."""

from __future__ import annotations

from html import unescape
import math
import re
from typing import Any

from .client import REDDIT_MAX_LIMIT, RedditClient
from .models import (
    RedditCommentSummary,
    RedditPostSummary,
    RedditSearchResult,
    RedditSubredditPostsResult,
    RedditThreadDigest,
)


DEFAULT_DISCUSSION_SUBREDDITS = [
    "stocks",
    "investing",
    "wallstreetbets",
    "SecurityAnalysis",
    "ValueInvesting",
    "StockMarket",
    "pennystocks",
    "options",
    "algotrading",
    "Economics",
    "business",
    "finance",
]
POPULAR_COMMENTS_PER_POST = 2


class RedditSubredditNotAllowedError(ValueError):
    def __init__(self, subreddit: str, allowed: list[str]) -> None:
        super().__init__(
            f"Subreddit r/{subreddit} is not in the configured finance/business whitelist."
        )
        self.subreddit = subreddit
        self.allowed = allowed


class RedditResearchService:
    def __init__(
        self,
        client: RedditClient,
        *,
        allowed_subreddits: list[str] | None = None,
    ) -> None:
        self.client = client
        self.allowed_subreddits = _dedupe_subreddits(
            allowed_subreddits or DEFAULT_DISCUSSION_SUBREDDITS
        )

    def search_posts(
        self,
        query: str,
        *,
        subreddit: str | None = None,
        sort: str = "relevance",
        time: str = "month",
        limit: int = 10,
        after: str | None = None,
    ) -> RedditSearchResult:
        resolved_limit = _bounded_limit(limit)
        resolved_subreddit = self._validate_optional_subreddit(subreddit)
        if resolved_subreddit is None:
            posts, after_value, before_value = self._search_whitelist(
                query,
                sort=sort,
                time=time,
                limit=resolved_limit,
            )
            searched_subreddits = self.allowed_subreddits
        else:
            payload = self.client.search(
                query,
                subreddit=resolved_subreddit,
                sort=sort,
                time=time,
                limit=resolved_limit,
                after=after,
            )
            listing = _extract_listing(payload)
            posts = self._posts_from_listing(
                listing,
                comment_limit=POPULAR_COMMENTS_PER_POST,
            )
            after_value = listing.get("after")
            before_value = listing.get("before")
            searched_subreddits = [resolved_subreddit]
        return RedditSearchResult(
            query=query,
            subreddit=resolved_subreddit,
            sort=sort,
            time=time,
            posts=posts,
            after=after_value,
            before=before_value,
            meta={
                "provider": "reddit_public_json",
                "resultCount": len(posts),
                "searchedSubreddits": searched_subreddits,
            },
        )

    def get_subreddit_posts(
        self,
        subreddit: str,
        *,
        sort: str = "hot",
        time: str | None = None,
        limit: int = 10,
        after: str | None = None,
    ) -> RedditSubredditPostsResult:
        resolved_subreddit = self._validate_subreddit(subreddit)
        payload = self.client.subreddit_listing(
            resolved_subreddit,
            listing=sort,
            time=time,
            limit=_bounded_limit(limit),
            after=after,
        )
        listing = _extract_listing(payload)
        posts = self._posts_from_listing(listing, comment_limit=POPULAR_COMMENTS_PER_POST)
        return RedditSubredditPostsResult(
            subreddit=resolved_subreddit,
            sort=sort,
            time=time,
            posts=posts,
            after=listing.get("after"),
            before=listing.get("before"),
            meta={"provider": "reddit_public_json", "resultCount": len(posts)},
        )

    def get_thread_digest(
        self,
        subreddit: str,
        post_id: str,
        *,
        comment_sort: str = "confidence",
        top_comment_limit: int = 8,
    ) -> RedditThreadDigest:
        resolved_subreddit = self._validate_subreddit(subreddit)
        payload = self.client.comments(
            resolved_subreddit,
            post_id,
            sort=comment_sort,
            limit=_bounded_limit(top_comment_limit),
        )
        return self._thread_from_payload(
            payload,
            subreddit=resolved_subreddit,
            comment_sort=comment_sort,
            top_comment_limit=top_comment_limit,
        )

    def _posts_from_listing(
        self,
        listing: dict[str, Any],
        *,
        comment_limit: int,
    ) -> list[RedditPostSummary]:
        posts: list[RedditPostSummary] = []
        for child in listing.get("children") or []:
            if child.get("kind") != "t3":
                continue
            post = _post_from_child(child)
            posts.append(self._attach_popular_comments(post, limit=comment_limit))
        return posts

    def _search_whitelist(
        self,
        query: str,
        *,
        sort: str,
        time: str,
        limit: int,
    ) -> tuple[list[RedditPostSummary], str | None, str | None]:
        per_subreddit = max(1, math.ceil(limit / max(1, len(self.allowed_subreddits))))
        merged: dict[str, RedditPostSummary] = {}
        after_value: str | None = None
        before_value: str | None = None
        for subreddit in self.allowed_subreddits:
            if len(merged) >= limit:
                break
            payload = self.client.search(
                query,
                subreddit=subreddit,
                sort=sort,
                time=time,
                limit=per_subreddit,
            )
            listing = _extract_listing(payload)
            after_value = after_value or listing.get("after")
            before_value = before_value or listing.get("before")
            for post in self._posts_from_listing(
                listing,
                comment_limit=POPULAR_COMMENTS_PER_POST,
            ):
                key = post.fullname or post.permalink or post.post_id
                if key in merged:
                    continue
                merged[key] = post
                if len(merged) >= limit:
                    break
        ranked = sorted(
            merged.values(),
            key=lambda post: (
                post.score or 0,
                post.num_comments or 0,
                post.created_at or "",
            ),
            reverse=True,
        )
        return ranked[:limit], after_value, before_value

    def _attach_popular_comments(
        self,
        post: RedditPostSummary,
        *,
        limit: int,
    ) -> RedditPostSummary:
        if not post.post_id or not post.subreddit or limit <= 0:
            return post
        try:
            payload = self.client.comments(
                post.subreddit,
                post.post_id,
                sort="top",
                limit=max(limit, 2),
                depth=2,
            )
            thread = self._thread_from_payload(
                payload,
                subreddit=post.subreddit,
                comment_sort="top",
                top_comment_limit=limit,
            )
        except Exception:
            return post
        return RedditPostSummary(
            post_id=post.post_id,
            fullname=post.fullname,
            subreddit=post.subreddit,
            title=post.title,
            author=post.author,
            permalink=post.permalink,
            url=post.url,
            selftext=post.selftext,
            created_at=post.created_at,
            score=post.score,
            num_comments=post.num_comments,
            upvote_ratio=post.upvote_ratio,
            over_18=post.over_18,
            is_self=post.is_self,
            flair=post.flair,
            top_comments=thread.top_comments[:limit],
        )

    def _thread_from_payload(
        self,
        payload: list[dict[str, Any]],
        *,
        subreddit: str,
        comment_sort: str,
        top_comment_limit: int,
    ) -> RedditThreadDigest:
        if len(payload) < 2:
            raise ValueError("Reddit comments payload was incomplete.")
        post_listing = _extract_listing(payload[0])
        post_children = post_listing.get("children") or []
        if not post_children:
            raise ValueError("Reddit comments payload did not include the post.")
        post = _post_from_child(post_children[0])

        comment_listing = _extract_listing(payload[1])
        flat_comments = _flatten_comments(comment_listing.get("children") or [])
        ranked_comments = sorted(
            flat_comments,
            key=lambda item: (item.score or 0, item.depth * -1),
            reverse=True,
        )
        top_comments = ranked_comments[: max(1, min(REDDIT_MAX_LIMIT, int(top_comment_limit)))]
        return RedditThreadDigest(
            subreddit=subreddit,
            post=post,
            comment_sort=comment_sort,
            top_comments=top_comments,
            total_comments_seen=len(flat_comments),
            meta={"provider": "reddit_public_json"},
        )

    def _validate_optional_subreddit(self, subreddit: str | None) -> str | None:
        if subreddit is None or not str(subreddit).strip():
            return None
        return self._validate_subreddit(subreddit)

    def _validate_subreddit(self, subreddit: str) -> str:
        resolved = _clean_subreddit_name(subreddit)
        allowed_by_lower = {item.lower(): item for item in self.allowed_subreddits}
        if resolved.lower() not in allowed_by_lower:
            raise RedditSubredditNotAllowedError(resolved, self.allowed_subreddits)
        return allowed_by_lower[resolved.lower()]


def _extract_listing(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("Reddit listing payload was missing a data object.")
    return data


def _post_from_child(child: dict[str, Any]) -> RedditPostSummary:
    data = child.get("data") or {}
    return RedditPostSummary(
        post_id=str(data.get("id") or ""),
        fullname=str(data.get("name") or ""),
        subreddit=str(data.get("subreddit") or ""),
        title=_clean_text(data.get("title")) or "",
        author=_nullable_text(data.get("author")),
        permalink=_to_reddit_url(data.get("permalink")),
        url=_nullable_text(data.get("url")),
        selftext=_clean_text(data.get("selftext")),
        created_at=_to_iso(data.get("created_utc")),
        score=_to_int(data.get("score")),
        num_comments=_to_int(data.get("num_comments")),
        upvote_ratio=_to_float(data.get("upvote_ratio")),
        over_18=bool(data.get("over_18")),
        is_self=bool(data.get("is_self")),
        flair=_nullable_text(data.get("link_flair_text")),
    )


def _flatten_comments(children: list[dict[str, Any]], *, depth: int = 0) -> list[RedditCommentSummary]:
    comments: list[RedditCommentSummary] = []
    for child in children:
        if child.get("kind") != "t1":
            continue
        data = child.get("data") or {}
        comments.append(
            RedditCommentSummary(
                comment_id=str(data.get("id") or ""),
                fullname=str(data.get("name") or ""),
                author=_nullable_text(data.get("author")),
                body=_clean_text(data.get("body")),
                permalink=_to_reddit_url(data.get("permalink")),
                created_at=_to_iso(data.get("created_utc")),
                score=_to_int(data.get("score")),
                parent_id=_nullable_text(data.get("parent_id")),
                depth=depth,
            )
        )
        replies = data.get("replies")
        if isinstance(replies, dict):
            reply_data = replies.get("data") or {}
            reply_children = reply_data.get("children") or []
            comments.extend(_flatten_comments(reply_children, depth=depth + 1))
    return comments


def _dedupe_subreddits(items: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        subreddit = _clean_subreddit_name(item)
        key = subreddit.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(subreddit)
    return deduped


def _clean_subreddit_name(value: Any) -> str:
    text = str(value or "").strip().removeprefix("r/").strip("/")
    if not text:
        raise ValueError("subreddit is required.")
    return text


def _clean_text(value: Any) -> str | None:
    text = _nullable_text(value)
    if text is None:
        return None
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _nullable_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_iso(value: Any) -> str | None:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    return _timestamp_to_iso(timestamp)


def _timestamp_to_iso(value: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat().replace(
        "+00:00",
        "Z",
    )


def _to_reddit_url(value: Any) -> str | None:
    text = _nullable_text(value)
    if text is None:
        return None
    if text.startswith("http://") or text.startswith("https://"):
        return text
    return "https://www.reddit.com" + text


def _to_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _bounded_limit(value: int) -> int:
    return max(1, min(REDDIT_MAX_LIMIT, int(value)))
