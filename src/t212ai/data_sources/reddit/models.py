"""Reddit research models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True, slots=True)
class RedditAccessToken:
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 3600
    scope: str | None = None
    issued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def expires_at(self) -> datetime:
        return self.issued_at + timedelta(seconds=max(0, int(self.expires_in)))

    def is_expired(self, *, skew_seconds: int = 60) -> bool:
        return datetime.now(timezone.utc) >= (
            self.expires_at - timedelta(seconds=max(0, int(skew_seconds)))
        )


@dataclass(frozen=True, slots=True)
class RedditApiErrorContext:
    operation: str
    endpoint: str | None = None
    status_code: int | None = None
    message: str | None = None
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RedditPostSummary:
    id: str
    fullname: str
    subreddit: str
    title: str
    author: str | None = None
    permalink: str | None = None
    url: str | None = None
    selftext_preview: str | None = None
    created_at: str | None = None
    score: int | None = None
    num_comments: int | None = None
    upvote_ratio: float | None = None
    over_18: bool = False
    is_self: bool = False
    link_flair_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "fullname": self.fullname,
            "subreddit": self.subreddit,
            "title": self.title,
            "author": self.author,
            "permalink": self.permalink,
            "url": self.url,
            "selftextPreview": self.selftext_preview,
            "createdAt": self.created_at,
            "score": self.score,
            "numComments": self.num_comments,
            "upvoteRatio": self.upvote_ratio,
            "over18": self.over_18,
            "isSelf": self.is_self,
            "linkFlairText": self.link_flair_text,
        }


@dataclass(frozen=True, slots=True)
class RedditCommentSummary:
    id: str
    fullname: str
    author: str | None = None
    body_preview: str | None = None
    permalink: str | None = None
    created_at: str | None = None
    score: int | None = None
    parent_id: str | None = None
    depth: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "fullname": self.fullname,
            "author": self.author,
            "bodyPreview": self.body_preview,
            "permalink": self.permalink,
            "createdAt": self.created_at,
            "score": self.score,
            "parentId": self.parent_id,
            "depth": self.depth,
        }


@dataclass(frozen=True, slots=True)
class RedditSearchResult:
    query: str
    subreddit: str | None
    sort: str
    time: str
    posts: list[RedditPostSummary] = field(default_factory=list)
    after: str | None = None
    before: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "subreddit": self.subreddit,
            "sort": self.sort,
            "time": self.time,
            "posts": [post.to_dict() for post in self.posts],
            "after": self.after,
            "before": self.before,
            "meta": self.meta,
        }


@dataclass(frozen=True, slots=True)
class RedditSubredditSnapshot:
    subreddit: str
    listing: str
    about: dict[str, Any]
    posts: list[RedditPostSummary] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subreddit": self.subreddit,
            "listing": self.listing,
            "about": self.about,
            "posts": [post.to_dict() for post in self.posts],
            "meta": self.meta,
        }


@dataclass(frozen=True, slots=True)
class RedditThreadDigest:
    subreddit: str
    post: RedditPostSummary
    comment_sort: str
    top_comments: list[RedditCommentSummary] = field(default_factory=list)
    total_comments_seen: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subreddit": self.subreddit,
            "post": self.post.to_dict(),
            "commentSort": self.comment_sort,
            "topComments": [comment.to_dict() for comment in self.top_comments],
            "totalCommentsSeen": self.total_comments_seen,
            "meta": self.meta,
        }


@dataclass(frozen=True, slots=True)
class RedditDiscussionScanResult:
    ticker: str
    company_name: str | None
    subreddits: list[str]
    query_terms: list[str]
    posts: list[RedditPostSummary] = field(default_factory=list)
    duplicates_removed: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "companyName": self.company_name,
            "subreddits": self.subreddits,
            "queryTerms": self.query_terms,
            "posts": [post.to_dict() for post in self.posts],
            "duplicatesRemoved": self.duplicates_removed,
            "meta": self.meta,
        }
