"""Reddit public JSON data-source integration."""

from .client import REDDIT_BASE_URL, REDDIT_MAX_LIMIT, RedditApiError, RedditClient
from .models import (
    RedditApiErrorContext,
    RedditCommentSummary,
    RedditPostSummary,
    RedditSearchResult,
    RedditSubredditPostsResult,
    RedditThreadDigest,
)
from .protocols import RedditResearchProtocol
from .service import (
    DEFAULT_DISCUSSION_SUBREDDITS,
    RedditResearchService,
    RedditSubredditNotAllowedError,
)
from .tools import (
    REDDIT_RESEARCH_TOOLBOX,
    REDDIT_RESEARCH_TOOLS,
    REDDIT_SEARCH_POSTS_TOOL,
    REDDIT_SUBREDDIT_POSTS_TOOL,
    REDDIT_THREAD_TOOL,
    RedditToolRuntime,
    build_reddit_tool_mapping,
    reddit_search_posts,
    reddit_subreddit_posts,
    reddit_thread,
)

__all__ = [
    "DEFAULT_DISCUSSION_SUBREDDITS",
    "REDDIT_BASE_URL",
    "REDDIT_MAX_LIMIT",
    "REDDIT_RESEARCH_TOOLBOX",
    "REDDIT_RESEARCH_TOOLS",
    "REDDIT_SEARCH_POSTS_TOOL",
    "REDDIT_SUBREDDIT_POSTS_TOOL",
    "REDDIT_THREAD_TOOL",
    "RedditApiError",
    "RedditApiErrorContext",
    "RedditClient",
    "RedditCommentSummary",
    "RedditPostSummary",
    "RedditResearchProtocol",
    "RedditResearchService",
    "RedditSearchResult",
    "RedditSubredditNotAllowedError",
    "RedditSubredditPostsResult",
    "RedditThreadDigest",
    "RedditToolRuntime",
    "build_reddit_tool_mapping",
    "reddit_search_posts",
    "reddit_subreddit_posts",
    "reddit_thread",
]
