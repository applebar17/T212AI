"""Protocols for Reddit research services."""

from __future__ import annotations

from typing import Protocol

from .models import (
    RedditSearchResult,
    RedditSubredditPostsResult,
    RedditThreadDigest,
)


class RedditResearchProtocol(Protocol):
    def search_posts(
        self,
        query: str,
        *,
        subreddit: str | None = None,
        sort: str = "relevance",
        time: str = "month",
        limit: int = 10,
        after: str | None = None,
    ) -> RedditSearchResult: ...

    def get_subreddit_posts(
        self,
        subreddit: str,
        *,
        sort: str = "hot",
        time: str | None = None,
        limit: int = 10,
        after: str | None = None,
    ) -> RedditSubredditPostsResult: ...

    def get_thread_digest(
        self,
        subreddit: str,
        post_id: str,
        *,
        comment_sort: str = "confidence",
        top_comment_limit: int = 8,
    ) -> RedditThreadDigest: ...
