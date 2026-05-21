"""Reddit public JSON research models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RedditApiErrorContext:
    operation: str
    endpoint: str | None = None
    status_code: int | None = None
    message: str | None = None
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RedditCommentSummary:
    comment_id: str
    fullname: str
    author: str | None = None
    body: str | None = None
    permalink: str | None = None
    created_at: str | None = None
    score: int | None = None
    parent_id: str | None = None
    depth: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "comment_id": self.comment_id,
            "fullname": self.fullname,
            "author": self.author,
            "body": self.body,
            "permalink": self.permalink,
            "created_at": self.created_at,
            "score": self.score,
            "parent_id": self.parent_id,
            "depth": self.depth,
        }


@dataclass(frozen=True, slots=True)
class RedditPostSummary:
    post_id: str
    fullname: str
    subreddit: str
    title: str
    author: str | None = None
    permalink: str | None = None
    url: str | None = None
    selftext: str | None = None
    created_at: str | None = None
    score: int | None = None
    num_comments: int | None = None
    upvote_ratio: float | None = None
    over_18: bool = False
    is_self: bool = False
    flair: str | None = None
    top_comments: list[RedditCommentSummary] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.post_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "post_id": self.post_id,
            "fullname": self.fullname,
            "subreddit": self.subreddit,
            "title": self.title,
            "author": self.author,
            "permalink": self.permalink,
            "url": self.url,
            "selftext": self.selftext,
            "created_at": self.created_at,
            "score": self.score,
            "num_comments": self.num_comments,
            "upvote_ratio": self.upvote_ratio,
            "over_18": self.over_18,
            "is_self": self.is_self,
            "flair": self.flair,
            "top_comments": [comment.to_dict() for comment in self.top_comments],
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
class RedditSubredditPostsResult:
    subreddit: str
    sort: str
    time: str | None
    posts: list[RedditPostSummary] = field(default_factory=list)
    after: str | None = None
    before: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subreddit": self.subreddit,
            "sort": self.sort,
            "time": self.time,
            "posts": [post.to_dict() for post in self.posts],
            "after": self.after,
            "before": self.before,
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
            "comment_sort": self.comment_sort,
            "top_comments": [comment.to_dict() for comment in self.top_comments],
            "total_comments_seen": self.total_comments_seen,
            "meta": self.meta,
        }
