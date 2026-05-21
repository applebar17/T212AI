#!/usr/bin/env python3
"""Render sample public Reddit tool outputs to a local JSON file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

DEFAULT_OUTPUT = REPO_ROOT / "data" / "reddit" / "tool_outputs.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Call the public Reddit research tools with small sample inputs and "
            "write their ToolResult payloads as JSON keyed by tool name."
        ),
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="JSON file to write.",
    )
    parser.add_argument(
        "--query",
        default="AAPL",
        help="Sample Reddit search query.",
    )
    parser.add_argument(
        "--search-subreddit",
        default="stocks",
        help="Whitelisted subreddit for reddit_search_posts.",
    )
    parser.add_argument(
        "--posts-subreddit",
        default="wallstreetbets",
        help="Whitelisted subreddit for reddit_subreddit_posts.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=2,
        help="Small sample post limit. The service still hard-caps at 25.",
    )
    parser.add_argument(
        "--comment-limit",
        type=int,
        default=3,
        help="Small sample comment limit for reddit_thread.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    from t212ai.data_sources.reddit import (
        RedditClient,
        RedditResearchService,
        RedditToolRuntime,
        reddit_search_posts,
        reddit_subreddit_posts,
        reddit_thread,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    runtime = RedditToolRuntime(service=RedditResearchService(RedditClient()))
    payload: dict[str, Any] = {}

    posts_result = reddit_subreddit_posts(
        subreddit=args.posts_subreddit,
        sort="hot",
        time=None,
        limit=args.limit,
        runtime=runtime,
    )
    payload["reddit_subreddit_posts"] = posts_result.model_dump(
        exclude_none=True,
        mode="json",
    )

    search_result = reddit_search_posts(
        query=args.query,
        subreddit=args.search_subreddit,
        sort="new",
        time="week",
        limit=args.limit,
        runtime=runtime,
    )
    payload["reddit_search_posts"] = search_result.model_dump(
        exclude_none=True,
        mode="json",
    )

    thread_source = _first_post(posts_result.data) or _first_post(search_result.data)
    if thread_source is None:
        payload["reddit_thread"] = {
            "status": "skipped",
            "output": "No post_id was available from reddit_subreddit_posts or reddit_search_posts.",
        }
    else:
        thread_result = reddit_thread(
            subreddit=thread_source["subreddit"],
            post_id=thread_source["post_id"],
            comment_sort="top",
            comment_limit=args.comment_limit,
            runtime=runtime,
        )
        payload["reddit_thread"] = thread_result.model_dump(
            exclude_none=True,
            mode="json",
        )

    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Wrote Reddit tool outputs to: {output_path}")
    return 0


def _first_post(data: Any) -> dict[str, str] | None:
    if not isinstance(data, dict):
        return None
    posts = data.get("posts")
    if not isinstance(posts, list):
        return None
    for post in posts:
        if not isinstance(post, dict):
            continue
        post_id = str(post.get("post_id") or "").strip()
        subreddit = str(post.get("subreddit") or "").strip()
        if post_id and subreddit:
            return {"post_id": post_id, "subreddit": subreddit}
    return None


if __name__ == "__main__":
    raise SystemExit(main())
