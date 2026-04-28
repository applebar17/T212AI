from __future__ import annotations

from datetime import date, timedelta

from t212ai.app.bootstrap import assess_settings
from t212ai.app.config import get_app_settings
from t212ai.data_sources.sec_edgar import (
    EdgarInsiderManager,
    SEC_EDGAR_DISCLOSURE_TOOLBOX,
    SecEdgarToolRuntime,
    edgar_company_disclosure_snapshot,
    edgar_recent_major_stake_activity,
    edgar_recent_ownership_activity,
)
from t212ai.genai.tools import MARKET_ANALYST_TOOLBOX, build_market_analyst_toolbox


class FakeSecEdgarClient:
    def get_company_tickers(self) -> dict[str, object]:
        return {
            "0": {
                "cik_str": 320193,
                "ticker": "AAPL",
                "title": "Apple Inc.",
            }
        }

    def get_submissions(self, cik: str) -> dict[str, object]:
        del cik
        today = date.today()
        return {
            "filings": {
                "recent": {
                    "form": ["4", "8-K", "SC 13G", "10-Q/A", "S-1"],
                    "filingDate": [
                        (today - timedelta(days=1)).isoformat(),
                        (today - timedelta(days=2)).isoformat(),
                        (today - timedelta(days=3)).isoformat(),
                        (today - timedelta(days=4)).isoformat(),
                        (today - timedelta(days=400)).isoformat(),
                    ],
                    "accessionNumber": [
                        "0000320193-26-000001",
                        "0000320193-26-000002",
                        "0000320193-26-000003",
                        "0000320193-26-000004",
                        "0000320193-25-000999",
                    ],
                    "primaryDocument": [
                        "xslF345X05/wk-form4_1.xml",
                        "current8k.htm",
                        "stake13g.htm",
                        "q1-10q.htm",
                        "old-s1.htm",
                    ],
                },
                "files": [
                    {
                        "name": "CIK0000320193-submissions-001.json",
                        "filingFrom": (today - timedelta(days=10)).isoformat(),
                        "filingTo": today.isoformat(),
                    }
                ],
            }
        }

    def get_submissions_file(self, name: str) -> dict[str, object]:
        assert name == "CIK0000320193-submissions-001.json"
        today = date.today()
        return {
            "form": ["3/A", "5"],
            "filingDate": [
                (today - timedelta(days=5)).isoformat(),
                (today - timedelta(days=6)).isoformat(),
            ],
            "accessionNumber": [
                "0000320193-26-000005",
                "0000320193-26-000006",
            ],
            "primaryDocument": [
                "ownership3a.xml",
                "ownership5.xml",
            ],
        }


def test_edgar_insider_manager_builds_recent_ownership_activity() -> None:
    manager = EdgarInsiderManager(FakeSecEdgarClient())  # type: ignore[arg-type]

    result = manager.recent_ownership_activity("AAPL", since_days=30, limit=10)

    assert result.symbol == "AAPL"
    assert result.company_name == "Apple Inc."
    assert result.filing_counts["4"] == 1
    assert result.filing_counts["3"] == 1
    assert result.filing_counts["5"] == 1
    assert len(result.recent_filings) == 3
    assert result.recent_filings[0].filing_url is not None


def test_edgar_tools_return_normalized_activity_context() -> None:
    runtime = SecEdgarToolRuntime(manager=EdgarInsiderManager(FakeSecEdgarClient()))  # type: ignore[arg-type]

    ownership = edgar_recent_ownership_activity(
        symbol="AAPL",
        since_days=30,
        limit=10,
        runtime=runtime,
    )
    stake = edgar_recent_major_stake_activity(
        symbol="AAPL",
        since_days=90,
        limit=10,
        runtime=runtime,
    )
    snapshot = edgar_company_disclosure_snapshot(
        symbol="AAPL",
        since_days=30,
        limit=10,
        runtime=runtime,
    )

    assert ownership.status == "ok"
    assert ownership.output is not None
    assert "ownership activity" in ownership.output
    assert stake.status == "ok"
    assert stake.output is not None
    assert "major stake activity" in stake.output
    assert snapshot.status == "ok"
    assert snapshot.output is not None
    assert "disclosure snapshot" in snapshot.output
    assert snapshot.data["filing_counts"]["8-K"] == 1
    assert snapshot.data["filing_counts"]["13G"] == 1


def test_sec_edgar_toolbox_and_market_analyst_toolbox_include_edgar_tools() -> None:
    assert "edgar_recent_ownership_activity" in SEC_EDGAR_DISCLOSURE_TOOLBOX.tools_by_name
    assert "edgar_recent_major_stake_activity" in SEC_EDGAR_DISCLOSURE_TOOLBOX.tools_by_name
    assert "edgar_company_disclosure_snapshot" in SEC_EDGAR_DISCLOSURE_TOOLBOX.tools_by_name
    assert "edgar_recent_ownership_activity" in MARKET_ANALYST_TOOLBOX.tools_by_name
    assert "edgar_recent_major_stake_activity" in MARKET_ANALYST_TOOLBOX.tools_by_name
    assert "edgar_company_disclosure_snapshot" in MARKET_ANALYST_TOOLBOX.tools_by_name


def test_market_analyst_toolbox_hides_edgar_tools_when_disclosure_is_disabled() -> None:
    settings = get_app_settings(env={"DISCLOSURE_PROVIDER": "none"})
    toolbox = build_market_analyst_toolbox(
        settings=settings,
        assessment=assess_settings(settings),
    )

    assert "edgar_recent_ownership_activity" not in toolbox.tools_by_name
    assert "edgar_recent_major_stake_activity" not in toolbox.tools_by_name
    assert "edgar_company_disclosure_snapshot" not in toolbox.tools_by_name
