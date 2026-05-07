"""SQL-backed market signal memory service."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from typing import Iterator
from uuid import uuid4

from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session, sessionmaker

from .models import (
    MarketSignal,
    MarketSignalDirection,
    MarketSignalHorizon,
    MarketSignalSearchMatch,
    MarketSignalSource,
    MarketSignalStatus,
    MarketSignalType,
)
from .orm import MarketSignalRow


class MarketSignalService:
    """Stores compact, auditable market signals for future agent context."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create_signal(
        self,
        *,
        title: str,
        summary: str,
        symbols: list[str] | None = None,
        sectors: list[str] | None = None,
        tags: list[str] | None = None,
        signal_type: MarketSignalType | str = MarketSignalType.OTHER,
        direction: MarketSignalDirection | str = MarketSignalDirection.UNKNOWN,
        impact_horizon: MarketSignalHorizon | str = MarketSignalHorizon.UNKNOWN,
        source: MarketSignalSource | str = MarketSignalSource.AGENT,
        source_refs: list[str] | None = None,
        expires_at: datetime | None = None,
    ) -> MarketSignal:
        resolved_symbols = _clean_symbols(symbols)
        resolved_sectors = _clean_terms(sectors)
        resolved_tags = _clean_terms(tags)
        if not (resolved_symbols or resolved_sectors or resolved_tags):
            raise ValueError("At least one symbol, sector, or tag is required.")

        now = _utc_now()
        row = MarketSignalRow(
            signal_id=_new_signal_id(),
            title=_required_text(title, "title"),
            summary=_required_text(summary, "summary"),
            symbols_json=_json_array(resolved_symbols),
            sectors_json=_json_array(resolved_sectors),
            tags_json=_json_array(resolved_tags),
            signal_type=_coerce_enum(MarketSignalType, signal_type).value,
            direction=_coerce_enum(MarketSignalDirection, direction).value,
            impact_horizon=_coerce_enum(MarketSignalHorizon, impact_horizon).value,
            source=_coerce_enum(MarketSignalSource, source).value,
            source_refs_json=_json_array(_clean_refs(source_refs)),
            status=MarketSignalStatus.ACTIVE.value,
            created_at=now,
            updated_at=now,
            expires_at=_ensure_aware(expires_at) if expires_at is not None else None,
        )
        with self._session_scope() as session:
            session.add(row)
            session.flush()
            return _signal_model(row)

    def search_signals(
        self,
        *,
        symbols: list[str] | None = None,
        sectors: list[str] | None = None,
        tags: list[str] | None = None,
        signal_types: list[str] | None = None,
        directions: list[str] | None = None,
        impact_horizons: list[str] | None = None,
        sources: list[str] | None = None,
        statuses: list[str] | None = None,
        active_only: bool = True,
        include_expired: bool = False,
        limit: int = 8,
    ) -> list[MarketSignalSearchMatch]:
        topical_filters = _TopicalFilters(
            symbols=set(_clean_symbols(symbols)),
            sectors=set(_clean_terms(sectors)),
            tags=set(_clean_terms(tags)),
        )
        now = _utc_now()
        resolved_limit = max(1, min(50, int(limit or 8)))
        with self._session_scope() as session:
            query = select(MarketSignalRow)
            if active_only:
                query = query.where(MarketSignalRow.status == MarketSignalStatus.ACTIVE.value)
            elif statuses:
                query = query.where(MarketSignalRow.status.in_(_coerce_statuses(statuses)))
            if not include_expired:
                query = query.where(
                    (MarketSignalRow.expires_at.is_(None))
                    | (MarketSignalRow.expires_at > now)
                )
            query = query.order_by(desc(MarketSignalRow.updated_at)).limit(250)
            rows = list(session.scalars(query).all())

        matches: list[tuple[int, datetime, MarketSignalSearchMatch]] = []
        for row in rows:
            if not _matches_scalar_filters(
                row,
                signal_types=signal_types,
                directions=directions,
                impact_horizons=impact_horizons,
                sources=sources,
            ):
                continue
            matched_fields = _matched_topical_fields(row, topical_filters)
            if topical_filters.has_any and not matched_fields:
                continue
            rank = _rank_for_match(matched_fields)
            matches.append(
                (
                    rank,
                    _ensure_aware(row.updated_at),
                    MarketSignalSearchMatch(
                        signal=_signal_model(row),
                        matched_fields=matched_fields,
                    ),
                )
            )
        matches.sort(key=lambda item: (-item[0], -item[1].timestamp(), item[2].signal.signal_id))
        return [match for _, _, match in matches[:resolved_limit]]

    def archive_signal(
        self,
        signal_id: str,
        *,
        source: MarketSignalSource | str = MarketSignalSource.AGENT,
    ) -> MarketSignal:
        del source
        with self._session_scope() as session:
            row = session.get(MarketSignalRow, str(signal_id))
            if row is None:
                raise ValueError(f"Market signal '{signal_id}' was not found.")
            row.status = MarketSignalStatus.ARCHIVED.value
            row.updated_at = _utc_now()
            session.flush()
            return _signal_model(row)

    def mark_expired_stale(self, now: datetime | None = None) -> int:
        cutoff = _ensure_aware(now) if now is not None else _utc_now()
        changed = 0
        with self._session_scope() as session:
            rows = session.scalars(
                select(MarketSignalRow).where(
                    MarketSignalRow.status == MarketSignalStatus.ACTIVE.value,
                    MarketSignalRow.expires_at.is_not(None),
                    MarketSignalRow.expires_at <= cutoff,
                )
            ).all()
            for row in rows:
                row.status = MarketSignalStatus.STALE.value
                row.updated_at = cutoff
                changed += 1
        return changed

    def delete_archived_before(self, cutoff: datetime) -> int:
        resolved_cutoff = _ensure_aware(cutoff)
        with self._session_scope() as session:
            result = session.execute(
                delete(MarketSignalRow).where(
                    MarketSignalRow.status == MarketSignalStatus.ARCHIVED.value,
                    MarketSignalRow.updated_at < resolved_cutoff,
                )
            )
            return int(result.rowcount or 0)

    @contextmanager
    def _session_scope(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


class _TopicalFilters:
    def __init__(self, *, symbols: set[str], sectors: set[str], tags: set[str]) -> None:
        self.symbols = symbols
        self.sectors = sectors
        self.tags = tags

    @property
    def has_any(self) -> bool:
        return bool(self.symbols or self.sectors or self.tags)


def _signal_model(row: MarketSignalRow) -> MarketSignal:
    return MarketSignal(
        signal_id=row.signal_id,
        title=row.title,
        summary=row.summary,
        symbols=_load_json_array(row.symbols_json),
        sectors=_load_json_array(row.sectors_json),
        tags=_load_json_array(row.tags_json),
        signal_type=MarketSignalType(row.signal_type),
        direction=MarketSignalDirection(row.direction),
        impact_horizon=MarketSignalHorizon(row.impact_horizon),
        source=MarketSignalSource(row.source),
        source_refs=_load_json_array(row.source_refs_json),
        status=MarketSignalStatus(row.status),
        created_at=_ensure_aware(row.created_at),
        updated_at=_ensure_aware(row.updated_at),
        expires_at=_ensure_aware(row.expires_at) if row.expires_at is not None else None,
    )


def _matches_scalar_filters(
    row: MarketSignalRow,
    *,
    signal_types: list[str] | None,
    directions: list[str] | None,
    impact_horizons: list[str] | None,
    sources: list[str] | None,
) -> bool:
    return (
        _value_in_filter(row.signal_type, signal_types, MarketSignalType)
        and _value_in_filter(row.direction, directions, MarketSignalDirection)
        and _value_in_filter(row.impact_horizon, impact_horizons, MarketSignalHorizon)
        and _value_in_filter(row.source, sources, MarketSignalSource)
    )


def _value_in_filter(value: str, filters: list[str] | None, enum_type: type) -> bool:
    if not filters:
        return True
    allowed = {_coerce_enum(enum_type, item).value for item in filters}
    return value in allowed


def _matched_topical_fields(
    row: MarketSignalRow,
    filters: _TopicalFilters,
) -> list[str]:
    matched: list[str] = []
    row_symbols = set(_load_json_array(row.symbols_json))
    row_sectors = set(_load_json_array(row.sectors_json))
    row_tags = set(_load_json_array(row.tags_json))
    if filters.symbols and row_symbols.intersection(filters.symbols):
        matched.append("symbols")
    if filters.sectors and row_sectors.intersection(filters.sectors):
        matched.append("sectors")
    if filters.tags and row_tags.intersection(filters.tags):
        matched.append("tags")
    return matched


def _rank_for_match(matched_fields: list[str]) -> int:
    if "symbols" in matched_fields:
        return 30
    if "sectors" in matched_fields:
        return 20
    if "tags" in matched_fields:
        return 10
    return 0


def _coerce_statuses(values: list[str]) -> list[str]:
    return [_coerce_enum(MarketSignalStatus, value).value for value in values]


def _coerce_enum(enum_type: type, value):
    raw = str(value or "").strip().lower()
    if not raw:
        raise ValueError(f"{enum_type.__name__} value is required.")
    try:
        return enum_type(raw)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ValueError(f"{enum_type.__name__} must be one of: {allowed}.") from exc


def _required_text(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required.")
    return text


def _clean_symbols(values: list[str] | None) -> list[str]:
    return _dedupe(str(value or "").strip().upper() for value in values or [])


def _clean_terms(values: list[str] | None) -> list[str]:
    return _dedupe(str(value or "").strip().lower().replace(" ", "_") for value in values or [])


def _clean_refs(values: list[str] | None) -> list[str]:
    return _dedupe(str(value or "").strip() for value in values or [])


def _dedupe(values) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _json_array(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=True, separators=(",", ":"))


def _load_json_array(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    return [str(item) for item in loaded if str(item).strip()]


def _new_signal_id() -> str:
    return f"ms_{uuid4().hex[:12]}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
