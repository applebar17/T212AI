from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from t212ai.app.bootstrap import assess_settings
from t212ai.app.config import get_app_settings
from t212ai.genai.tools import build_market_analyst_toolbox
from t212ai.market_signals import (
    MarketSignalService,
    MarketSignalToolRuntime,
    market_signal_archive,
    market_signal_create,
    market_signal_search,
)
from t212ai.persistence.database import build_engine, build_session_factory, ensure_schema


def _service(tmp_path: Path) -> MarketSignalService:
    engine = build_engine(f"sqlite:///{tmp_path / 'signals.db'}")
    ensure_schema(engine)
    return MarketSignalService(build_session_factory(engine))


def test_market_signal_service_creates_searches_and_archives(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = service.create_signal(
        title="AI capex demand",
        summary="Cloud capex commentary may support semiconductor demand.",
        symbols=["nvda"],
        sectors=["Semiconductors"],
        tags=["ai capex"],
        signal_type="catalyst",
        direction="bullish",
        impact_horizon="medium_term",
        source="user",
        source_refs=["https://example.test/source"],
    )
    service.create_signal(
        title="Old index note",
        summary="This broad-market note is stale and should not appear after archive.",
        tags=["broad_market"],
    )

    matches = service.search_signals(symbols=["NVDA"], limit=8)

    assert len(matches) == 1
    assert matches[0].signal.signal_id == first.signal_id
    assert matches[0].matched_fields == ["symbols"]
    assert matches[0].signal.symbols == ["NVDA"]
    assert matches[0].signal.sectors == ["semiconductors"]
    assert matches[0].signal.tags == ["ai_capex"]

    archived = service.archive_signal(first.signal_id)
    assert archived.status == "archived"
    assert service.search_signals(symbols=["NVDA"], limit=8) == []


def test_market_signal_search_excludes_expired_active_signals_by_default(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    expired = service.create_signal(
        title="Expired CPI setup",
        summary="Old inflation setup should be excluded unless requested explicitly.",
        sectors=["macro"],
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )

    assert service.search_signals(sectors=["macro"], limit=8) == []
    matches = service.search_signals(
        sectors=["macro"],
        include_expired=True,
        limit=8,
    )
    assert [match.signal.signal_id for match in matches] == [expired.signal_id]


def test_market_signal_search_broadly_matches_symbol_sector_or_tag(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    symbol_match = service.create_signal(
        title="Apple services note",
        summary="Services mix is relevant for Apple margin expectations.",
        symbols=["AAPL"],
        tags=["margins"],
    )
    sector_match = service.create_signal(
        title="Banks rate sensitivity",
        summary="Higher-for-longer rates may affect bank net interest margins.",
        sectors=["banks"],
        tags=["rates"],
    )
    tag_match = service.create_signal(
        title="Earnings season volatility",
        summary="Earnings may lift realized volatility across large-cap tech.",
        tags=["earnings"],
    )

    matches = service.search_signals(
        symbols=["AAPL"],
        sectors=["banks"],
        tags=["earnings"],
        limit=8,
    )

    ids = [match.signal.signal_id for match in matches]
    assert ids == [symbol_match.signal_id, sector_match.signal_id, tag_match.signal_id]
    assert matches[0].matched_fields == ["symbols"]
    assert matches[1].matched_fields == ["sectors"]
    assert matches[2].matched_fields == ["tags"]


def test_market_signal_create_validation(tmp_path: Path) -> None:
    service = _service(tmp_path)

    with pytest.raises(ValueError, match="title is required"):
        service.create_signal(title="", summary="Valid summary", tags=["risk"])

    with pytest.raises(ValueError, match="summary is required"):
        service.create_signal(title="Valid title", summary="", tags=["risk"])

    with pytest.raises(ValueError, match="At least one symbol"):
        service.create_signal(title="Valid title", summary="Valid summary")


def test_market_signal_tools_create_search_and_archive(tmp_path: Path) -> None:
    service = _service(tmp_path)
    runtime = MarketSignalToolRuntime(service=service)

    created = market_signal_create(
        title="Regulatory pressure",
        summary="New policy scrutiny may affect mega-cap platform sentiment.",
        symbols=[],
        sectors=["internet"],
        tags=["regulation"],
        signal_type="regulatory",
        direction="bearish",
        impact_horizon="short_term",
        source="agent",
        source_refs=[],
        expires_at=None,
        runtime=runtime,
    )

    assert created.status == "ok"
    signal = created.data["signal"]
    assert signal["status"] == "active"
    assert signal["source"] == "agent"
    assert signal["direction"] == "bearish"

    searched = market_signal_search(
        symbols=None,
        sectors=["internet"],
        tags=None,
        signal_types=None,
        directions=None,
        impact_horizons=None,
        sources=None,
        active_only=True,
        include_expired=False,
        limit=8,
        runtime=runtime,
    )

    assert searched.status == "ok"
    assert searched.data["count"] == 1
    assert searched.data["matches"][0]["matchedFields"] == ["sectors"]

    archived = market_signal_archive(
        signal_id=signal["signalId"],
        source="agent",
        runtime=runtime,
    )

    assert archived.status == "ok"
    assert archived.data["signal"]["status"] == "archived"
    assert service.search_signals(sectors=["internet"], limit=8) == []


def test_market_signal_tools_only_appear_when_database_capability_is_available() -> None:
    enabled_settings = get_app_settings()
    enabled_toolbox = build_market_analyst_toolbox(
        settings=enabled_settings,
        assessment=assess_settings(enabled_settings),
    )
    disabled_settings = get_app_settings(env={"DATABASE_URL": ""})
    disabled_toolbox = build_market_analyst_toolbox(
        settings=disabled_settings,
        assessment=assess_settings(disabled_settings),
    )

    assert "market_signal_search" in enabled_toolbox.tools_by_name
    assert "market_signal_search" not in disabled_toolbox.tools_by_name
