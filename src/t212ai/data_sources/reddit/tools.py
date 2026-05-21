"""Public Reddit research tool definitions."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Any, Callable

from t212ai.genai.models import ToolError, ToolResult, ToolSpec
from t212ai.genai.tools.tools import ToolBox, build_tool_index
from t212ai.genai.tracing import (
    set_trace_metadata,
    traceable,
)

from .client import RedditApiError, RedditClient
from .protocols import RedditResearchProtocol
from .service import RedditResearchService, RedditSubredditNotAllowedError


@dataclass(slots=True)
class RedditToolRuntime:
    service: RedditResearchProtocol


_REDDIT_CONTEXT_WARNING = (
    "Reddit is community/social research context only. Verify claims with market, "
    "news, and filing tools before treating them as actionable."
)


REDDIT_SEARCH_POSTS_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "reddit_search_posts",
        "description": (
            "Search whitelisted finance/business Reddit communities through public JSON. "
            "Returns full post text, post_id, popularity proxies, and up to 2 popular comments. "
            + _REDDIT_CONTEXT_WARNING
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query text."},
                "subreddit": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": (
                        "Optional whitelisted subreddit name without r/. If omitted, "
                        "search the configured finance/business subreddit whitelist."
                    ),
                },
                "sort": {
                    "type": "string",
                    "enum": ["relevance", "hot", "top", "new", "comments"],
                    "default": "relevance",
                },
                "time": {
                    "type": "string",
                    "enum": ["hour", "day", "week", "month", "year", "all"],
                    "default": "month",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 25,
                    "default": 10,
                    "description": "Maximum posts to return. The service hard-caps at 25.",
                },
            },
            "required": ["query", "subreddit", "sort", "time", "limit"],
            "additionalProperties": False,
        },
    },
}

REDDIT_SUBREDDIT_POSTS_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "reddit_subreddit_posts",
        "description": (
            "Fetch posts from one whitelisted finance/business subreddit through public JSON. "
            "Use for current community discussion snapshots. Includes full post text, post_id, "
            "popularity proxies, and up to 2 popular comments per post. "
            + _REDDIT_CONTEXT_WARNING
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "subreddit": {"type": "string", "description": "Whitelisted subreddit name without r/."},
                "sort": {
                    "type": "string",
                    "enum": ["hot", "new", "top", "rising"],
                    "default": "hot",
                },
                "time": {
                    "type": ["string", "null"],
                    "enum": ["hour", "day", "week", "month", "year", "all", None],
                    "default": None,
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 25,
                    "default": 10,
                    "description": "Maximum posts to return. The service hard-caps at 25.",
                },
            },
            "required": ["subreddit", "sort", "time", "limit"],
            "additionalProperties": False,
        },
    },
}

REDDIT_THREAD_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "reddit_thread",
        "description": (
            "Fetch one Reddit thread by subreddit and post_id. Returns full post text and "
            "full selected comment bodies with popularity proxies. "
            + _REDDIT_CONTEXT_WARNING
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "subreddit": {"type": "string", "description": "Whitelisted subreddit name without r/."},
                "post_id": {
                    "type": "string",
                    "description": "Reddit post id, with or without the t3_ prefix.",
                },
                "comment_sort": {
                    "type": "string",
                    "enum": ["confidence", "top", "new", "controversial", "old", "qa"],
                    "default": "confidence",
                },
                "comment_limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 25,
                    "default": 8,
                    "description": "Maximum comments to return. The service hard-caps at 25.",
                },
            },
            "required": ["subreddit", "post_id", "comment_sort", "comment_limit"],
            "additionalProperties": False,
        },
    },
}


def build_reddit_tool_mapping(
    runtime: RedditToolRuntime | None = None,
) -> dict[str, Callable[..., ToolResult]]:
    resolved_runtime = runtime or RedditToolRuntime(
        service=RedditResearchService(RedditClient.from_settings())
    )
    return {
        "reddit_search_posts": partial(reddit_search_posts, runtime=resolved_runtime),
        "reddit_subreddit_posts": partial(
            reddit_subreddit_posts,
            runtime=resolved_runtime,
        ),
        "reddit_thread": partial(reddit_thread, runtime=resolved_runtime),
    }


@traceable(
    name="reddit_search_posts",
    run_type="tool"
)
def reddit_search_posts(
    *,
    query: str,
    subreddit: str | None,
    sort: str,
    time: str,
    limit: int,
    runtime: RedditToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider="reddit", tool_name="reddit_search_posts")
    try:
        result = runtime.service.search_posts(
            query,
            subreddit=subreddit,
            sort=sort,
            time=time,
            limit=limit,
        )
    except Exception as exc:
        return _exception_result(exc, operation="search_posts")
    return ToolResult(
        status="ok",
        output=_format_posts_summary(
            f"Reddit search for '{result.query}'"
            + (f" in r/{result.subreddit}" if result.subreddit else ""),
            result.posts,
        ),
        data={
            "query": result.query,
            "subreddit": result.subreddit,
            "sort": result.sort,
            "time": result.time,
            "posts": [_agent_post_payload(post) for post in result.posts],
        },
    )


@traceable(
    name="reddit_subreddit_posts",
    run_type="tool"
)
def reddit_subreddit_posts(
    *,
    subreddit: str,
    sort: str,
    time: str | None,
    limit: int,
    runtime: RedditToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider="reddit", tool_name="reddit_subreddit_posts")
    try:
        result = runtime.service.get_subreddit_posts(
            subreddit,
            sort=sort,
            time=time,
            limit=limit,
        )
    except Exception as exc:
        return _exception_result(exc, operation="subreddit_posts")
    return ToolResult(
        status="ok",
        output=_format_posts_summary(
            f"Reddit r/{result.subreddit} {result.sort} posts",
            result.posts,
        ),
        data={
            "subreddit": result.subreddit,
            "sort": result.sort,
            "time": result.time,
            "posts": [_agent_post_payload(post) for post in result.posts],
        },
    )


@traceable(
    name="reddit_thread",
    run_type="tool"
)
def reddit_thread(
    *,
    subreddit: str,
    post_id: str,
    comment_sort: str,
    comment_limit: int,
    runtime: RedditToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider="reddit", tool_name="reddit_thread")
    try:
        result = runtime.service.get_thread_digest(
            subreddit,
            post_id,
            comment_sort=comment_sort,
            top_comment_limit=comment_limit,
        )
    except Exception as exc:
        return _exception_result(exc, operation="thread")
    return ToolResult(
        status="ok",
        output=_format_thread_summary(result),
        data={
            "subreddit": result.subreddit,
            "comment_sort": result.comment_sort,
            "post": _agent_post_payload(result.post, include_embedded_comments=False),
            "comments": [_agent_comment_payload(comment) for comment in result.top_comments],
        },
    )


def _format_posts_summary(label: str, posts: list[Any]) -> str:
    if not posts:
        return f"{label} returned no posts. {_REDDIT_CONTEXT_WARNING}"
    titles = "; ".join(
        f"{post.post_id}: {post.title} (score={post.score}, comments={post.num_comments})"
        for post in posts[:5]
    )
    return (
        f"{label} returned {len(posts)} post(s). Top posts: {titles}. "
        f"Use data.posts for full post/comment content. {_REDDIT_CONTEXT_WARNING}"
    )


def _format_thread_summary(result: Any) -> str:
    post = result.post
    return (
        f"Reddit thread r/{result.subreddit} post_id={post.post_id} returned "
        f"{len(result.top_comments)} comment(s). Title: {post.title}. "
        f"Use data.post and data.comments for full content. {_REDDIT_CONTEXT_WARNING}"
    )


def _agent_post_payload(
    post: Any,
    *,
    include_embedded_comments: bool = True,
) -> dict[str, Any]:
    payload = {
        "post_id": post.post_id,
        "subreddit": post.subreddit,
        "title": post.title,
        "created_at": post.created_at,
        "flair": post.flair,
        "popularity": {
            "score": post.score,
            "upvote_ratio": post.upvote_ratio,
            "comments": post.num_comments,
        },
        "content": post.selftext,
        "permalink": post.permalink,
    }
    if include_embedded_comments:
        payload["comments"] = [
            _agent_comment_payload(comment)
            for comment in post.top_comments
        ]
    return _drop_none(payload)


def _agent_comment_payload(comment: Any) -> dict[str, Any]:
    return _drop_none(
        {
            "score": comment.score,
            "body": comment.body,
        }
    )


def _drop_none(value: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.items():
        if item is None:
            continue
        if isinstance(item, dict):
            nested = _drop_none(item)
            if nested:
                result[key] = nested
            continue
        if isinstance(item, list):
            filtered = [entry for entry in item if entry not in ({}, None)]
            if filtered:
                result[key] = filtered
            continue
        result[key] = item
    return result


def _exception_result(exc: Exception, *, operation: str) -> ToolResult:
    if isinstance(exc, RedditApiError):
        retryable = bool(exc.context.retryable)
        details = {
            "operation": exc.context.operation,
            "endpoint": exc.context.endpoint,
            "status_code": exc.context.status_code,
            **exc.context.details,
        }
        code = "reddit_api_error"
        message = exc.context.message or str(exc)
        hint = "Retry later or reduce the request size." if retryable else "Validate subreddit, post_id, and request parameters."
    elif isinstance(exc, RedditSubredditNotAllowedError):
        retryable = False
        details = {"subreddit": exc.subreddit, "allowed_subreddits": exc.allowed}
        code = "reddit_subreddit_not_allowed"
        message = str(exc)
        hint = "Use one of the configured finance/business subreddits."
    else:
        retryable = False
        details = {}
        code = "reddit_tool_error"
        message = str(exc)
        hint = "Validate subreddit, post_id, and request parameters."
    return ToolResult(
        status="error",
        output=(
            f"Reddit {operation} failed. Reason: {message}. "
            "Use Reddit only as community context and pivot to other research providers if needed."
        ),
        error=ToolError(
            message=message,
            code=code,
            type=exc.__class__.__name__,
            hint=hint,
            retryable=retryable,
            details=details or None,
        ),
    )


REDDIT_RESEARCH_TOOLS: list[ToolSpec] = [
    REDDIT_SEARCH_POSTS_TOOL,
    REDDIT_SUBREDDIT_POSTS_TOOL,
    REDDIT_THREAD_TOOL,
]

REDDIT_RESEARCH_TOOLBOX = ToolBox(
    name="reddit_research",
    tools=REDDIT_RESEARCH_TOOLS,
    tools_by_name=build_tool_index(REDDIT_RESEARCH_TOOLS),
)
