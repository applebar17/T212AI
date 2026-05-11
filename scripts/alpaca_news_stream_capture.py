#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


DEFAULT_OUTPUT = REPO_ROOT / "data" / "alpaca_stream" / "news_stream.jsonl"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture Alpaca real-time news websocket events to a local JSONL file.",
    )
    parser.add_argument(
        "--env-file",
        default=str(REPO_ROOT / ".env"),
        help="Path to the env file containing Alpaca credentials.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="JSONL file to append stream events into.",
    )
    parser.add_argument(
        "--symbols",
        action="append",
        default=None,
        help="Optional local symbol filter. Can be passed multiple times.",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=60.0,
        help="Stop after this many seconds.",
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=None,
        help="Stop after writing this many matching news events.",
    )
    parser.add_argument(
        "--sandbox",
        action="store_true",
        help="Use Alpaca's sandbox stream host.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    from t212ai.alpaca import AlpacaStreamClient, capture_alpaca_news_stream
    from t212ai.app.config import get_app_settings

    args = build_parser().parse_args(argv)
    settings = get_app_settings(env_file=args.env_file)
    if not settings.alpaca_api_key or not settings.alpaca_api_secret:
        print(
            "Alpaca API credentials are missing. Configure ALPACA_PAPER_API_KEY/"
            "ALPACA_PAPER_API_SECRET or ALPACA_LIVE_API_KEY/ALPACA_LIVE_API_SECRET."
        )
        return 1

    client = AlpacaStreamClient.from_settings(settings)
    print(f"Connecting to Alpaca news stream. Writing JSONL to: {args.output}")
    if args.symbols:
        print("Local symbol filter: " + ", ".join(args.symbols))
    try:
        result = asyncio.run(
            capture_alpaca_news_stream(
                client,
                args.output,
                symbols=args.symbols or [],
                max_events=args.max_events,
                seconds=args.seconds,
                sandbox=bool(args.sandbox),
            )
        )
    except KeyboardInterrupt:
        print("Stopped.")
        return 0
    except Exception as exc:
        print(f"Alpaca news stream capture failed: {exc}")
        return 1

    print(result.render_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
