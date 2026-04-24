"""Higher-level Reddit research service."""

from __future__ import annotations

from typing import Any

from .client import RedditClient
from .models import (
    RedditCommentSummary,
    RedditDiscussionScanResult,
    RedditPostSummary,
    RedditSearchResult,
    RedditSubredditSnapshot,
    RedditThreadDigest,
)


DEFAULT_DISCUSSION_SUBREDDITS = [
    "stocks",
    "investing",
    "wallstreetbets",
    "SecurityAnalysis",
]


class RedditResearchService:
    def __init__(self, client: RedditClient) -> None:
        self.client = client

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
        payload = self.client.search(
            query,
            subreddit=subreddit,
            sort=sort,
            time=time,
            limit=limit,
            after=after,
        )
        listing = _extract_listing(payload)
        children = listing.get("children") or []
        posts = [_post_from_child(child) for child in children if child.get("kind") == "t3"]
        return RedditSearchResult(
            query=query,
            subreddit=subreddit,
            sort=sort,
            time=time,
            posts=posts,
            after=listing.get("after"),
            before=listing.get("before"),
            meta={"provider": "reddit_data_api", "resultCount": len(posts)},
        )

    def get_subreddit_snapshot(
        self,
        subreddit: str,
        *,
        listing: str = "hot",
        time: str | None = None,
        limit: int = 10,
    ) -> RedditSubredditSnapshot:
        about_payload = self.client.subreddit_about(subreddit)
        listing_payload = self.client.subreddit_listing(
            subreddit,
            listing=listing,
            time=time,
            limit=limit,
        )
        about = _extract_subreddit_about(about_payload)
        listing_data = _extract_listing(listing_payload)
        posts = [
            _post_from_child(child)
            for child in (listing_data.get("children") or [])
            if child.get("kind") == "t3"
        ]
        return RedditSubredditSnapshot(
            subreddit=subreddit,
            listing=listing,
            about=about,
            posts=posts,
            meta={"provider": "reddit_data_api", "resultCount": len(posts)},
        )

    def get_thread_digest(
        self,
        subreddit: str,
        post_id: str,
        *,
        comment_sort: str = "confidence",
        top_comment_limit: int = 8,
    ) -> RedditThreadDigest:
        payload = self.client.comments(
            subreddit,
            post_id,
            sort=comment_sort,
            limit=max(10, int(top_comment_limit)),
        )
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
        top_comments = ranked_comments[: max(1, int(top_comment_limit))]
        return RedditThreadDigest(
            subreddit=subreddit,
            post=post,
            comment_sort=comment_sort,
            top_comments=top_comments,
            total_comments_seen=len(flat_comments),
            meta={"provider": "reddit_data_api"},
        )

    def scan_company_discussion(
        self,
        ticker: str,
        *,
        company_name: str | None = None,
        subreddits: list[str] | None = None,
        time: str = "month",
        limit_per_subreddit: int = 5,
        max_results: int = 20,
    ) -> RedditDiscussionScanResult:
        resolved_ticker = str(ticker or "").strip().upper()
        if not resolved_ticker:
            raise ValueError("ticker is required.")
        communities = [
            str(item).strip()
            for item in (subreddits or DEFAULT_DISCUSSION_SUBREDDITS)
            if str(item).strip()
        ]
        queries = _build_discussion_queries(resolved_ticker, company_name=company_name)
        merged: dict[str, RedditPostSummary] = {}
        duplicates_removed = 0
        for subreddit in communities:
            for query in queries:
                result = self.search_posts(
                    query,
                    subreddit=subreddit,
                    sort="relevance",
                    time=time,
                    limit=limit_per_subreddit,
                )
                for post in result.posts:
                    key = post.permalink or post.fullname
                    if key in merged:
                        duplicates_removed += 1
                        continue
                    merged[key] = post
        ranked = sorted(
            merged.values(),
            key=lambda post: (
                post.score or 0,
                post.num_comments or 0,
                post.created_at or "",
            ),
            reverse=True,
        )
        posts = ranked[: max(1, int(max_results))]
        return RedditDiscussionScanResult(
            ticker=resolved_ticker,
            company_name=str(company_name or "").strip() or None,
            subreddits=communities,
            query_terms=queries,
            posts=posts,
            duplicates_removed=duplicates_removed,
            meta={"provider": "reddit_data_api", "scannedSubreddits": len(communities)},
        )


def _extract_listing(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("Reddit listing payload was missing a data object.")
    return data


def _extract_subreddit_about(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("Reddit subreddit payload was missing a data object.")
    return {
        "displayName": data.get("display_name"),
        "title": data.get("title"),
        "publicDescription": data.get("public_description"),
        "subscribers": data.get("subscribers"),
        "activeUserCount": data.get("active_user_count"),
        "over18": data.get("over18"),
        "url": data.get("url"),
    }


def _post_from_child(child: dict[str, Any]) -> RedditPostSummary:
    data = child.get("data") or {}
    return RedditPostSummary(
        id=str(data.get("id") or ""),
        fullname=str(data.get("name") or ""),
        subreddit=str(data.get("subreddit") or ""),
        title=str(data.get("title") or ""),
        author=_nullable_text(data.get("author")),
        permalink=_to_reddit_url(data.get("permalink")),
        url=_nullable_text(data.get("url")),
        selftext_preview=_preview_text(data.get("selftext"), max_chars=320),
        created_at=_to_iso(data.get("created_utc")),
        score=_to_int(data.get("score")),
        num_comments=_to_int(data.get("num_comments")),
        upvote_ratio=_to_float(data.get("upvote_ratio")),
        over_18=bool(data.get("over_18")),
        is_self=bool(data.get("is_self")),
        link_flair_text=_nullable_text(data.get("link_flair_text")),
    )


def _flatten_comments(children: list[dict[str, Any]], *, depth: int = 0) -> list[RedditCommentSummary]:
    comments: list[RedditCommentSummary] = []
    for child in children:
        if child.get("kind") != "t1":
            continue
        data = child.get("data") or {}
        comments.append(
            RedditCommentSummary(
                id=str(data.get("id") or ""),
                fullname=str(data.get("name") or ""),
                author=_nullable_text(data.get("author")),
                body_preview=_preview_text(data.get("body"), max_chars=360),
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


def _build_discussion_queries(ticker: str, *, company_name: str | None) -> list[str]:
    queries = [ticker]
    resolved_name = str(company_name or "").strip()
    if resolved_name:
        queries.append(resolved_name)
        queries.append(f"{resolved_name} {ticker}")
    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        normalized = query.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(query)
    return deduped


def _preview_text(value: Any, *, max_chars: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


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
