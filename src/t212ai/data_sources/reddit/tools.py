"""Reddit research tool definitions."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Any, Callable

from t212ai.genai.models import ToolError, ToolResult, ToolSpec
from t212ai.genai.tools.tools import ToolBox, build_tool_index
from t212ai.genai.tracing import (
    _trace_tool_function_inputs,
    _trace_tool_function_outputs,
    set_trace_metadata,
    traceable,
)

from .client import RedditApiError, RedditClient
from .protocols import RedditResearchProtocol
from .service import RedditResearchService


@dataclass(slots=True)
class RedditToolRuntime:
    service: RedditResearchProtocol


REDDIT_SEARCH_POSTS_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "reddit_search_posts",
        "description": (
            "Search Reddit posts for retail discussion, anecdotal sentiment, and "
            "community framing. Use as research context, not authoritative market data."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query text."},
                "subreddit": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Optional subreddit name, without r/.",
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
                },
            },
            "required": ["query", "subreddit", "sort", "time", "limit"],
            "additionalProperties": False,
        },
    },
}

REDDIT_SUBREDDIT_SNAPSHOT_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "reddit_subreddit_snapshot",
        "description": (
            "Fetch a subreddit profile plus a current listing snapshot to understand "
            "what that community is discussing."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "subreddit": {"type": "string", "description": "Subreddit name without r/."},
                "listing": {
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
                },
            },
            "required": ["subreddit", "listing", "time", "limit"],
            "additionalProperties": False,
        },
    },
}

REDDIT_THREAD_DIGEST_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "reddit_thread_digest",
        "description": (
            "Fetch one Reddit thread and summarize the post plus the highest-signal comments."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "subreddit": {"type": "string", "description": "Subreddit name without r/."},
                "post_id": {
                    "type": "string",
                    "description": "Reddit post id, with or without the t3_ prefix.",
                },
                "comment_sort": {
                    "type": "string",
                    "enum": ["confidence", "top", "new", "controversial", "old", "qa"],
                    "default": "confidence",
                },
                "top_comment_limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 8,
                },
            },
            "required": ["subreddit", "post_id", "comment_sort", "top_comment_limit"],
            "additionalProperties": False,
        },
    },
}

REDDIT_COMPANY_DISCUSSION_SCAN_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "reddit_company_discussion_scan",
        "description": (
            "Scan selected Reddit investing communities for ticker/company discussion. "
            "Useful for anecdotal sentiment and recurring retail themes."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Ticker symbol, e.g. AAPL."},
                "company_name": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Optional company name for broader search coverage.",
                },
                "subreddits": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "default": None,
                    "description": "Optional subreddit override list.",
                },
                "time": {
                    "type": "string",
                    "enum": ["day", "week", "month", "year", "all"],
                    "default": "month",
                },
                "limit_per_subreddit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 5,
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 30,
                    "default": 20,
                },
            },
            "required": [
                "ticker",
                "company_name",
                "subreddits",
                "time",
                "limit_per_subreddit",
                "max_results",
            ],
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
        "reddit_subreddit_snapshot": partial(
            reddit_subreddit_snapshot,
            runtime=resolved_runtime,
        ),
        "reddit_thread_digest": partial(reddit_thread_digest, runtime=resolved_runtime),
        "reddit_company_discussion_scan": partial(
            reddit_company_discussion_scan,
            runtime=resolved_runtime,
        ),
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
        output=_format_search_output(result),
        data=result.to_dict(),
    )


@traceable(
    name="reddit_subreddit_snapshot",
    run_type="tool"
)
def reddit_subreddit_snapshot(
    *,
    subreddit: str,
    listing: str,
    time: str | None,
    limit: int,
    runtime: RedditToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider="reddit", tool_name="reddit_subreddit_snapshot")
    try:
        result = runtime.service.get_subreddit_snapshot(
            subreddit,
            listing=listing,
            time=time,
            limit=limit,
        )
    except Exception as exc:
        return _exception_result(exc, operation="subreddit_snapshot")
    return ToolResult(
        status="ok",
        output=_format_subreddit_snapshot_output(result),
        data=result.to_dict(),
    )


@traceable(
    name="reddit_thread_digest",
    run_type="tool"
)
def reddit_thread_digest(
    *,
    subreddit: str,
    post_id: str,
    comment_sort: str,
    top_comment_limit: int,
    runtime: RedditToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider="reddit", tool_name="reddit_thread_digest")
    try:
        result = runtime.service.get_thread_digest(
            subreddit,
            post_id,
            comment_sort=comment_sort,
            top_comment_limit=top_comment_limit,
        )
    except Exception as exc:
        return _exception_result(exc, operation="thread_digest")
    return ToolResult(
        status="ok",
        output=_format_thread_digest_output(result),
        data=result.to_dict(),
    )


@traceable(
    name="reddit_company_discussion_scan",
    run_type="tool"
)
def reddit_company_discussion_scan(
    *,
    ticker: str,
    company_name: str | None,
    subreddits: list[str] | None,
    time: str,
    limit_per_subreddit: int,
    max_results: int,
    runtime: RedditToolRuntime,
) -> ToolResult:
    set_trace_metadata(provider="reddit", tool_name="reddit_company_discussion_scan")
    try:
        result = runtime.service.scan_company_discussion(
            ticker,
            company_name=company_name,
            subreddits=subreddits,
            time=time,
            limit_per_subreddit=limit_per_subreddit,
            max_results=max_results,
        )
    except Exception as exc:
        return _exception_result(exc, operation="company_discussion_scan")
    return ToolResult(
        status="ok",
        output=_format_company_scan_output(result),
        data=result.to_dict(),
    )


def _format_search_output(result: Any) -> str:
    scope = f" in r/{result.subreddit}" if result.subreddit else ""
    if not result.posts:
        return (
            f"Reddit search found no posts for '{result.query}'{scope}. "
            "Try a broader query, another subreddit, or a different time window."
        )
    top = "; ".join(
        f"r/{post.subreddit}: {post.title} (score={post.score}, comments={post.num_comments})"
        for post in result.posts[:5]
    )
    return (
        f"Reddit search for '{result.query}'{scope} returned {len(result.posts)} post(s). "
        f"Top hits: {top}. "
        "Use this as anecdotal community context, not verified market data or broker state."
    )


def _format_subreddit_snapshot_output(result: Any) -> str:
    about = result.about or {}
    return (
        f"Reddit subreddit snapshot for r/{result.subreddit}. "
        f"title={about.get('title')}, subscribers={about.get('subscribers')}, "
        f"active_users={about.get('activeUserCount')}, posts_returned={len(result.posts)}. "
        "Use this to understand the current discussion environment before trusting post-level signals."
    )


def _format_thread_digest_output(result: Any) -> str:
    post = result.post
    lines = [
        f"Reddit thread digest for r/{result.subreddit}.",
        (
            "Post: "
            f"title={post.title}, score={post.score}, comments={post.num_comments}, "
            f"author={post.author}."
        ),
        (
            f"Top comments returned={len(result.top_comments)} "
            f"(total comments scanned={result.total_comments_seen})."
        ),
    ]
    for comment in result.top_comments[:5]:
        lines.append(
            "- "
            f"author={comment.author}, score={comment.score}, depth={comment.depth}, "
            f"body_preview={comment.body_preview}"
        )
    lines.append(
        "Interpret Reddit comments as community anecdotes and framing, not verified facts."
    )
    return "\n".join(lines)


def _format_company_scan_output(result: Any) -> str:
    if not result.posts:
        return (
            f"Reddit company discussion scan found no posts for {result.ticker}. "
            "Broaden the company name, expand subreddits, or use other research sources."
        )
    top = "; ".join(
        f"r/{post.subreddit}: {post.title} (score={post.score}, comments={post.num_comments})"
        for post in result.posts[:6]
    )
    return (
        f"Reddit company discussion scan for {result.ticker} searched "
        f"{len(result.subreddits)} subreddit(s) and returned {len(result.posts)} unique post(s), "
        f"removing {result.duplicates_removed} duplicate hit(s). "
        f"Top discussion threads: {top}. "
        "Treat this as retail/community signal context only."
    )


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
    else:
        retryable = False
        details = {}
        code = "reddit_tool_error"
        message = str(exc)
    return ToolResult(
        status="error",
        output=(
            f"Reddit {operation} failed. Reason: {message}. "
            "Retry with a narrower request, or pivot to web search and other research providers."
        ),
        error=ToolError(
            message=message,
            code=code,
            type=exc.__class__.__name__,
            hint=(
                "Retry later or reduce the request size."
                if retryable
                else "Validate OAuth credentials, User-Agent, subreddit/post id, and request parameters."
            ),
            retryable=retryable,
            details=details or None,
        ),
    )


REDDIT_RESEARCH_TOOLS: list[ToolSpec] = [
    REDDIT_SEARCH_POSTS_TOOL,
    REDDIT_SUBREDDIT_SNAPSHOT_TOOL,
    REDDIT_THREAD_DIGEST_TOOL,
    REDDIT_COMPANY_DISCUSSION_SCAN_TOOL,
]

REDDIT_RESEARCH_TOOLBOX = ToolBox(
    name="reddit_research",
    tools=REDDIT_RESEARCH_TOOLS,
    tools_by_name=build_tool_index(REDDIT_RESEARCH_TOOLS),
)
