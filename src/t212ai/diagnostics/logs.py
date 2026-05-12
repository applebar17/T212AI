"""Read-only navigation for structured application logs."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from t212ai.app.logging import redact_log_text, redact_log_value

LOG_FIELD_NAMES = (
    "timestamp",
    "level",
    "logger",
    "event",
    "component",
    "agent_name",
    "selected_agent",
    "step",
    "tool_name",
    "status",
    "error_type",
    "error_code",
    "chat_id",
    "message_id",
    "request_id",
    "model",
    "provider",
    "provider_error_code",
    "provider_policy_code",
    "content_filter_triggered",
    "content_filter_summary",
    "content_filter_categories",
    "content_filter_blocked_categories",
    "content_filter_detected_categories",
    "prompt_fingerprint",
    "toolbox_name",
)


class LogRecordView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_number: int
    timestamp: str | None = None
    level: str | None = None
    logger: str | None = None
    event: str | None = None
    component: str | None = None
    agent_name: str | None = None
    selected_agent: str | None = None
    step: str | None = None
    tool_name: str | None = None
    status: str | None = None
    error_type: str | None = None
    error_code: str | None = None
    chat_id: str | None = None
    message_id: str | None = None
    request_id: str | None = None
    model: str | None = None
    provider: str | None = None
    provider_error_code: str | None = None
    provider_policy_code: str | None = None
    content_filter_triggered: str | None = None
    content_filter_summary: str | None = None
    content_filter_categories: str | None = None
    content_filter_blocked_categories: str | None = None
    content_filter_detected_categories: str | None = None
    prompt_fingerprint: str | None = None
    toolbox_name: str | None = None
    message: str | None = None


class LogQueryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    records: list[LogRecordView] = Field(default_factory=list)
    matched_count: int = 0
    truncated: bool = False


@dataclass(slots=True)
class LogFileNavigator:
    path: Path | str
    max_records: int = 500
    max_bytes: int = 262_144
    message_limit: int = 360

    def available(self) -> bool:
        return Path(self.path).expanduser().is_file()

    def tail(self, *, limit: int = 50, **filters: Any) -> LogQueryResult:
        records = self._matching_records(**filters)
        capped_limit = self._limit(limit)
        return LogQueryResult(
            records=records[-capped_limit:],
            matched_count=len(records),
            truncated=len(records) > capped_limit,
        )

    def query(
        self,
        *,
        since: str | None = None,
        until: str | None = None,
        limit: int = 100,
        **filters: Any,
    ) -> LogQueryResult:
        records = self._matching_records(since=since, until=until, **filters)
        capped_limit = self._limit(limit)
        return LogQueryResult(
            records=records[-capped_limit:],
            matched_count=len(records),
            truncated=len(records) > capped_limit,
        )

    def context(
        self,
        *,
        line_number: int,
        before: int = 5,
        after: int = 5,
    ) -> LogQueryResult:
        before = max(0, min(int(before), 50))
        after = max(0, min(int(after), 50))
        lower = max(1, int(line_number) - before)
        upper = int(line_number) + after
        records = [
            record
            for record in self._iter_records()
            if lower <= record.line_number <= upper
        ]
        return LogQueryResult(records=records, matched_count=len(records), truncated=False)

    def counts(
        self,
        *,
        group_by: str,
        since: str | None = None,
        until: str | None = None,
        limit: int = 50,
        **filters: Any,
    ) -> dict[str, Any]:
        if group_by not in LOG_FIELD_NAMES:
            group_by = "event"
        records = self._matching_records(since=since, until=until, **filters)
        counter: Counter[str] = Counter(
            str(getattr(record, group_by) or "unknown") for record in records
        )
        capped_limit = self._limit(limit)
        return {
            "groupBy": group_by,
            "matchedCount": len(records),
            "counts": [
                {"value": value, "count": count}
                for value, count in counter.most_common(capped_limit)
            ],
            "truncated": len(counter) > capped_limit,
        }

    def _matching_records(
        self,
        *,
        since: str | None = None,
        until: str | None = None,
        contains: str | None = None,
        **filters: Any,
    ) -> list[LogRecordView]:
        since_dt = _parse_timestamp(since)
        until_dt = _parse_timestamp(until)
        normalized_filters = {
            key: str(value).lower()
            for key, value in filters.items()
            if key in LOG_FIELD_NAMES and value not in (None, "")
        }
        contains_text = str(contains or "").strip().lower()
        matches: list[LogRecordView] = []
        for record in self._iter_records():
            timestamp_dt = _parse_timestamp(record.timestamp)
            if since_dt and timestamp_dt and timestamp_dt < since_dt:
                continue
            if until_dt and timestamp_dt and timestamp_dt > until_dt:
                continue
            if not _matches_filters(record, normalized_filters):
                continue
            if contains_text and contains_text not in _record_search_text(record).lower():
                continue
            matches.append(record)
        return matches[-self.max_records :]

    def _iter_records(self) -> Iterable[LogRecordView]:
        path = Path(self.path).expanduser()
        if not path.is_file():
            return []
        return list(_iter_limited_records(path, self.max_bytes, self.message_limit))

    def _limit(self, limit: int) -> int:
        return max(1, min(int(limit or 1), self.max_records))


def _iter_limited_records(
    path: Path,
    max_bytes: int,
    message_limit: int,
) -> Iterable[LogRecordView]:
    size = path.stat().st_size
    start = max(0, size - max(0, int(max_bytes)))
    with path.open("rb") as handle:
        if start:
            handle.seek(start)
            handle.readline()
            start = handle.tell()
        line_number = _count_lines_before(path, start) + 1
        for raw in handle:
            text = raw.decode("utf-8", errors="replace").rstrip("\n")
            yield _parse_line(text, line_number=line_number, message_limit=message_limit)
            line_number += 1


def _count_lines_before(path: Path, byte_offset: int) -> int:
    if byte_offset <= 0:
        return 0
    count = 0
    remaining = byte_offset
    with path.open("rb") as handle:
        while remaining > 0:
            chunk = handle.read(min(65_536, remaining))
            if not chunk:
                break
            count += chunk.count(b"\n")
            remaining -= len(chunk)
    return count


def _parse_line(
    text: str,
    *,
    line_number: int,
    message_limit: int,
) -> LogRecordView:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return LogRecordView(
            line_number=line_number,
            message=_truncate(redact_log_text(text), message_limit),
        )
    if not isinstance(payload, dict):
        return LogRecordView(
            line_number=line_number,
            message=_truncate(redact_log_text(text), message_limit),
        )
    sanitized = redact_log_value(payload)
    assert isinstance(sanitized, dict)
    fields = {
        name: _optional_str(sanitized.get(name))
        for name in LOG_FIELD_NAMES
    }
    return LogRecordView(
        line_number=line_number,
        **fields,
        message=_truncate(_optional_str(sanitized.get("message")), message_limit),
    )


def _matches_filters(record: LogRecordView, filters: dict[str, str]) -> bool:
    for key, expected in filters.items():
        actual = getattr(record, key, None)
        if str(actual or "").lower() != expected:
            return False
    return True


def _record_search_text(record: LogRecordView) -> str:
    return " ".join(
        str(value)
        for value in record.model_dump(exclude_none=True).values()
    )


def _parse_timestamp(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidates = [raw]
    if raw.endswith("Z"):
        candidates.append(raw[:-1] + "+00:00")
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    for fmt in ("%Y-%m-%d %H:%M:%S,%f", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=UTC)
    return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value)
    return raw if raw else None


def _truncate(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."
