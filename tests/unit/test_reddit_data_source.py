from __future__ import annotations

import urllib.parse

from t212ai.data_sources.reddit import (
    DEFAULT_DISCUSSION_SUBREDDITS,
    REDDIT_RESEARCH_TOOLBOX,
    RedditClient,
    RedditCommentSummary,
    RedditPostSummary,
    RedditSearchResult,
    RedditSubredditPostsResult,
    RedditThreadDigest,
    RedditToolRuntime,
    RedditResearchService,
    build_reddit_tool_mapping,
    reddit_search_posts,
    reddit_subreddit_posts,
)


class StubRedditClient(RedditClient):
    def __init__(self, payload_by_operation: dict[str, object]) -> None:
        super().__init__(user_agent="t212ai-test")
        self.payload_by_operation = payload_by_operation
        self.requests: dict[str, object] = {}

    def _read_json_request(self, request, *, operation: str):  # type: ignore[override]
        self.requests[operation] = request
        return self.payload_by_operation[operation]


class FakeRedditService:
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
        del limit, after
        return RedditSearchResult(
            query=query,
            subreddit=subreddit,
            sort=sort,
            time=time,
            posts=[_fake_post(subreddit or "stocks")],
            meta={"provider": "fake"},
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
        del limit, after
        return RedditSubredditPostsResult(
            subreddit=subreddit,
            sort=sort,
            time=time,
            posts=[_fake_post(subreddit)],
            meta={"provider": "fake"},
        )

    def get_thread_digest(
        self,
        subreddit: str,
        post_id: str,
        *,
        comment_sort: str = "confidence",
        top_comment_limit: int = 8,
    ) -> RedditThreadDigest:
        del top_comment_limit
        return RedditThreadDigest(
            subreddit=subreddit,
            post=_fake_post(subreddit, post_id=post_id),
            comment_sort=comment_sort,
            top_comments=[
                RedditCommentSummary(
                    comment_id="c1",
                    fullname="t1_c1",
                    author="commenter",
                    body="This is a high-signal full comment.",
                    score=80,
                    depth=0,
                )
            ],
            total_comments_seen=10,
            meta={"provider": "fake"},
        )


def _fake_post(subreddit: str, *, post_id: str = "abc123") -> RedditPostSummary:
    return RedditPostSummary(
        post_id=post_id,
        fullname=f"t3_{post_id}",
        subreddit=subreddit,
        title="Apple discussion thread",
        author="analyst123",
        permalink=f"https://www.reddit.com/r/{subreddit}/comments/{post_id}/apple_discussion/",
        url=f"https://www.reddit.com/r/{subreddit}/comments/{post_id}/apple_discussion/",
        selftext="Full post body about demand, margins, and sentiment.",
        score=120,
        num_comments=45,
        upvote_ratio=0.91,
        top_comments=[
            RedditCommentSummary(
                comment_id="c1",
                fullname="t1_c1",
                author="commenter",
                body="Full popular comment body.",
                score=40,
            )
        ],
    )


def test_reddit_client_builds_public_search_query_without_oauth_headers() -> None:
    client = StubRedditClient(
        {
            "search": {
                "data": {
                    "children": [],
                    "after": "t3_next",
                    "before": None,
                }
            }
        }
    )

    client.search(
        "apple",
        subreddit="stocks",
        sort="top",
        time="week",
        limit=50,
    )
    request = client.requests["search"]
    query = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)

    assert "Authorization" not in request.headers
    assert request.headers["User-agent"] == "t212ai-test"
    assert request.full_url.startswith("https://www.reddit.com/r/stocks/search.json?")
    assert query["q"] == ["apple"]
    assert query["restrict_sr"] == ["1"]
    assert query["sort"] == ["top"]
    assert query["t"] == ["week"]
    assert query["limit"] == ["25"]


def test_reddit_research_service_preserves_full_content_and_popular_comments() -> None:
    client = StubRedditClient(
        {
            "subreddit_listing": {
                "data": {
                    "children": [
                        {
                            "kind": "t3",
                            "data": {
                                "id": "abc123",
                                "name": "t3_abc123",
                                "subreddit": "wallstreetbets",
                                "title": "AAPL thread",
                                "selftext": "Long full post body with &amp; escaped text.",
                                "score": 250,
                                "upvote_ratio": 0.88,
                                "num_comments": 2,
                            },
                        }
                    ]
                }
            },
            "comments": [
                {
                    "data": {
                        "children": [
                            {
                                "kind": "t3",
                                "data": {
                                    "id": "abc123",
                                    "name": "t3_abc123",
                                    "subreddit": "wallstreetbets",
                                    "title": "AAPL thread",
                                    "selftext": "Long full post body",
                                    "score": 250,
                                    "upvote_ratio": 0.88,
                                    "num_comments": 2,
                                },
                            }
                        ]
                    }
                },
                {
                    "data": {
                        "children": [
                            {
                                "kind": "t1",
                                "data": {
                                    "id": "c1",
                                    "name": "t1_c1",
                                    "author": "alpha",
                                    "body": "Top-level full comment body",
                                    "score": 40,
                                },
                            },
                            {
                                "kind": "t1",
                                "data": {
                                    "id": "c2",
                                    "name": "t1_c2",
                                    "author": "beta",
                                    "body": "Second full comment body",
                                    "score": 10,
                                },
                            },
                            {
                                "kind": "t1",
                                "data": {
                                    "id": "c3",
                                    "name": "t1_c3",
                                    "author": "gamma",
                                    "body": "Third full comment body",
                                    "score": 5,
                                },
                            },
                        ]
                    }
                },
            ],
        }
    )
    service = RedditResearchService(client)

    result = service.get_subreddit_posts("wallstreetbets", limit=50)

    assert "wallstreetbets" in DEFAULT_DISCUSSION_SUBREDDITS
    assert result.posts[0].post_id == "abc123"
    assert result.posts[0].selftext == "Long full post body with & escaped text."
    assert result.posts[0].score == 250
    assert result.posts[0].upvote_ratio == 0.88
    assert [comment.comment_id for comment in result.posts[0].top_comments] == ["c1", "c2"]
    assert result.posts[0].top_comments[0].body == "Top-level full comment body"


def test_reddit_research_service_blocks_non_whitelisted_subreddits() -> None:
    service = RedditResearchService(StubRedditClient({}))

    try:
        service.get_subreddit_posts("random")
    except Exception as exc:
        assert exc.__class__.__name__ == "RedditSubredditNotAllowedError"
    else:
        raise AssertionError("Expected non-whitelisted subreddit to fail")


def test_reddit_search_tool_returns_content_rich_context() -> None:
    runtime = RedditToolRuntime(service=FakeRedditService())  # type: ignore[arg-type]

    result = reddit_search_posts(
        query="apple",
        subreddit="stocks",
        sort="relevance",
        time="month",
        limit=5,
        runtime=runtime,
    )

    assert result.status == "ok"
    assert result.output is not None
    assert "community/social research context" in result.output
    assert "Use data.posts for full post/comment content" in result.output
    assert result.data["posts"][0]["post_id"] == "abc123"
    assert result.data["posts"][0]["content"] == (
        "Full post body about demand, margins, and sentiment."
    )
    assert result.data["posts"][0]["comments"][0]["body"] == "Full popular comment body."
    assert result.data["posts"][0]["popularity"] == {
        "comments": 45,
        "score": 120,
        "upvote_ratio": 0.91,
    }
    assert "fullname" not in result.data["posts"][0]
    assert "author" not in result.data["posts"][0]
    assert "comment_id" not in result.data["posts"][0]["comments"][0]


def test_reddit_subreddit_tool_and_mapping() -> None:
    runtime = RedditToolRuntime(service=FakeRedditService())  # type: ignore[arg-type]
    mapping = build_reddit_tool_mapping(runtime)

    assert REDDIT_RESEARCH_TOOLBOX.name == "reddit_research"
    assert "reddit_search_posts" in REDDIT_RESEARCH_TOOLBOX.tools_by_name
    assert "reddit_subreddit_posts" in REDDIT_RESEARCH_TOOLBOX.tools_by_name
    assert "reddit_thread" in REDDIT_RESEARCH_TOOLBOX.tools_by_name
    assert "reddit_subreddit_posts" in mapping

    result = reddit_subreddit_posts(
        subreddit="wallstreetbets",
        sort="hot",
        time=None,
        limit=5,
        runtime=runtime,
    )

    assert result.status == "ok"
    assert "r/wallstreetbets" in result.output
