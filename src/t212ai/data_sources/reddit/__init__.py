"""Reddit research data-source integration."""

from .client import RedditApiError, RedditClient
from .models import (
    RedditAccessToken,
    RedditApiErrorContext,
    RedditCommentSummary,
    RedditDiscussionScanResult,
    RedditPostSummary,
    RedditSearchResult,
    RedditSubredditSnapshot,
    RedditThreadDigest,
)
from .protocols import RedditResearchProtocol
from .service import DEFAULT_DISCUSSION_SUBREDDITS, RedditResearchService
from .tools import (
    REDDIT_COMPANY_DISCUSSION_SCAN_TOOL,
    REDDIT_RESEARCH_TOOLBOX,
    REDDIT_RESEARCH_TOOLS,
    REDDIT_SEARCH_POSTS_TOOL,
    REDDIT_SUBREDDIT_SNAPSHOT_TOOL,
    REDDIT_THREAD_DIGEST_TOOL,
    RedditToolRuntime,
    build_reddit_tool_mapping,
    reddit_company_discussion_scan,
    reddit_search_posts,
    reddit_subreddit_snapshot,
    reddit_thread_digest,
)

__all__ = [
    "DEFAULT_DISCUSSION_SUBREDDITS",
    "REDDIT_COMPANY_DISCUSSION_SCAN_TOOL",
    "REDDIT_RESEARCH_TOOLBOX",
    "REDDIT_RESEARCH_TOOLS",
    "REDDIT_SEARCH_POSTS_TOOL",
    "REDDIT_SUBREDDIT_SNAPSHOT_TOOL",
    "REDDIT_THREAD_DIGEST_TOOL",
    "RedditAccessToken",
    "RedditApiError",
    "RedditApiErrorContext",
    "RedditClient",
    "RedditCommentSummary",
    "RedditDiscussionScanResult",
    "RedditPostSummary",
    "RedditResearchProtocol",
    "RedditResearchService",
    "RedditSearchResult",
    "RedditSubredditSnapshot",
    "RedditThreadDigest",
    "RedditToolRuntime",
    "build_reddit_tool_mapping",
    "reddit_company_discussion_scan",
    "reddit_search_posts",
    "reddit_subreddit_snapshot",
    "reddit_thread_digest",
]
