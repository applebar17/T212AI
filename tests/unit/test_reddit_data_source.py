from __future__ import annotations

import urllib.parse

from t212ai.data_sources.reddit import (
    REDDIT_RESEARCH_TOOLBOX,
    RedditAccessToken,
    RedditClient,
    RedditCommentSummary,
    RedditDiscussionScanResult,
    RedditPostSummary,
    RedditSearchResult,
    RedditSubredditSnapshot,
    RedditThreadDigest,
    RedditToolRuntime,
    RedditResearchService,
    build_reddit_tool_mapping,
    reddit_company_discussion_scan,
    reddit_search_posts,
)


class StubRedditClient(RedditClient):
    def __init__(self, payload_by_operation: dict[str, object]) -> None:
        super().__init__(
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
            user_agent="server:t212ai:test (by /u/tester)",
        )
        self.payload_by_operation = payload_by_operation
        self.requests: dict[str, object] = {}

    def _ensure_token(self) -> RedditAccessToken:
        return RedditAccessToken(access_token="token")

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
            posts=[
                RedditPostSummary(
                    id="abc123",
                    fullname="t3_abc123",
                    subreddit=subreddit or "stocks",
                    title="Apple discussion thread",
                    author="analyst123",
                    permalink="https://www.reddit.com/r/stocks/comments/abc123/apple_discussion/",
                    score=120,
                    num_comments=45,
                )
            ],
            meta={"provider": "fake"},
        )

    def get_subreddit_snapshot(
        self,
        subreddit: str,
        *,
        listing: str = "hot",
        time: str | None = None,
        limit: int = 10,
    ) -> RedditSubredditSnapshot:
        del time, limit
        return RedditSubredditSnapshot(
            subreddit=subreddit,
            listing=listing,
            about={"title": "Stocks", "subscribers": 5000000, "activeUserCount": 12345},
            posts=[],
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
            post=RedditPostSummary(
                id=post_id,
                fullname=f"t3_{post_id}",
                subreddit=subreddit,
                title="Thread title",
                author="poster",
                score=200,
                num_comments=50,
            ),
            comment_sort=comment_sort,
            top_comments=[
                RedditCommentSummary(
                    id="c1",
                    fullname="t1_c1",
                    author="commenter",
                    body_preview="This is a high-signal comment.",
                    score=80,
                    depth=0,
                )
            ],
            total_comments_seen=10,
            meta={"provider": "fake"},
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
        del time, limit_per_subreddit, max_results
        communities = subreddits or ["stocks", "investing"]
        return RedditDiscussionScanResult(
            ticker=ticker,
            company_name=company_name,
            subreddits=communities,
            query_terms=[ticker, company_name or ticker],
            posts=[
                RedditPostSummary(
                    id="scan1",
                    fullname="t3_scan1",
                    subreddit="stocks",
                    title="AAPL sentiment thread",
                    score=500,
                    num_comments=180,
                )
            ],
            duplicates_removed=2,
            meta={"provider": "fake"},
        )


def test_reddit_client_builds_search_query_with_oauth_headers() -> None:
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
        limit=5,
    )
    request = client.requests["search"]
    query = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)

    assert request.headers["Authorization"] == "bearer token"
    assert query["q"] == ["apple"]
    assert query["restrict_sr"] == ["1"]
    assert query["sort"] == ["top"]
    assert query["t"] == ["week"]
    assert query["limit"] == ["5"]


def test_reddit_research_service_flattens_comments_for_thread_digest() -> None:
    client = StubRedditClient(
        {
            "comments": [
                {
                    "data": {
                        "children": [
                            {
                                "kind": "t3",
                                "data": {
                                    "id": "abc123",
                                    "name": "t3_abc123",
                                    "subreddit": "stocks",
                                    "title": "Apple thread",
                                    "author": "poster",
                                    "score": 250,
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
                                    "body": "Top-level comment",
                                    "score": 40,
                                    "replies": {
                                        "data": {
                                            "children": [
                                                {
                                                    "kind": "t1",
                                                    "data": {
                                                        "id": "c2",
                                                        "name": "t1_c2",
                                                        "author": "beta",
                                                        "body": "Reply comment",
                                                        "score": 10,
                                                    },
                                                }
                                            ]
                                        }
                                    },
                                },
                            }
                        ]
                    }
                },
            ]
        }
    )
    service = RedditResearchService(client)

    result = service.get_thread_digest("stocks", "abc123", top_comment_limit=5)

    assert result.post.title == "Apple thread"
    assert result.total_comments_seen == 2
    assert result.top_comments[0].author == "alpha"


def test_reddit_search_tool_returns_verbose_context() -> None:
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
    assert "anecdotal community context" in result.output
    assert "Apple discussion thread" in result.output


def test_reddit_company_scan_tool_returns_discussion_summary() -> None:
    runtime = RedditToolRuntime(service=FakeRedditService())  # type: ignore[arg-type]

    result = reddit_company_discussion_scan(
        ticker="AAPL",
        company_name="Apple",
        subreddits=None,
        time="month",
        limit_per_subreddit=5,
        max_results=10,
        runtime=runtime,
    )

    assert result.status == "ok"
    assert result.output is not None
    assert "duplicate hit(s)" in result.output
    assert "retail/community signal context" in result.output
    assert result.data["ticker"] == "AAPL"


def test_reddit_toolbox_and_mapping() -> None:
    runtime = RedditToolRuntime(service=FakeRedditService())  # type: ignore[arg-type]
    mapping = build_reddit_tool_mapping(runtime)

    assert REDDIT_RESEARCH_TOOLBOX.name == "reddit_research"
    assert "reddit_search_posts" in REDDIT_RESEARCH_TOOLBOX.tools_by_name
    assert "reddit_company_discussion_scan" in mapping
