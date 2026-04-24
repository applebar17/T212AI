"""Protocols for Reddit research services."""

from __future__ import annotations

from typing import Protocol

from .models import (
    RedditDiscussionScanResult,
    RedditSearchResult,
    RedditSubredditSnapshot,
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

    def get_subreddit_snapshot(
        self,
        subreddit: str,
        *,
        listing: str = "hot",
        time: str | None = None,
        limit: int = 10,
    ) -> RedditSubredditSnapshot: ...

    def get_thread_digest(
        self,
        subreddit: str,
        post_id: str,
        *,
        comment_sort: str = "confidence",
        top_comment_limit: int = 8,
    ) -> RedditThreadDigest: ...

    def scan_company_discussion(
        self,
        ticker: str,
        *,
        company_name: str | None = None,
        subreddits: list[str] | None = None,
        time: str = "month",
        limit_per_subreddit: int = 5,
        max_results: int = 20,
    ) -> RedditDiscussionScanResult: ...
