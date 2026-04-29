"""Check Trading 212 broker-native instrument ticker resolution locally.

This script reads the normal app `.env`, fetches `/equity/metadata/instruments`,
and prints resolver output for one or more symbols/names. It does not place
orders.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from t212ai.app.config import get_app_settings  # noqa: E402
from t212ai.brokers.trading212 import Trading212Client, Trading212BrokerService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve public symbols or company names to Trading 212 broker-native "
            "instrument tickers using the configured demo/live environment."
        )
    )
    parser.add_argument(
        "queries",
        nargs="*",
        default=["GOOGL", "GOOGLE", "AAPL"],
        help="Ticker, ISIN, broker ticker, or instrument/company name to resolve.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=8,
        help="Maximum candidates per query.",
    )
    args = parser.parse_args()

    settings = get_app_settings()
    client = Trading212Client.from_settings(settings)
    service = Trading212BrokerService(client)

    payload = {
        "provider": "trading212",
        "environment": settings.trading212_environment,
        "base_url": settings.trading212_base_url,
        "queries": [
            service.resolve_instrument(query, limit=args.limit).model_dump(
                by_alias=True,
                exclude_none=True,
                mode="json",
            )
            for query in args.queries
        ],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
