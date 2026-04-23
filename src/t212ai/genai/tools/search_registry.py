"""Run-scoped URL registry for search and scrape tools."""

from __future__ import annotations

from dataclasses import dataclass, field
import urllib.parse
from typing import Any


@dataclass
class SearchResultRegistry:
    """In-memory registry mapping run-scoped url ids to discovered URLs."""

    prefix: str = "url"
    session: Any | None = None
    job_run_id: str | None = None
    next_index: int = 1
    _by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    _id_by_url: dict[str, str] = field(default_factory=dict)

    def register(
        self,
        *,
        url: str,
        payload: dict[str, Any] | None = None,
        discovered_via: str = "other",
        parent_alias: str | None = None,
        source_name: str | None = None,
        title: str | None = None,
        image_url: str | None = None,
        published_at: str | None = None,
    ) -> str:
        normalized = self._normalize_url(url)
        existing_id = self._id_by_url.get(normalized)
        if existing_id:
            if payload and existing_id in self._by_id:
                self._by_id[existing_id]["payload"] = payload
            return existing_id

        result_id = f"{self.prefix}-{self.next_index}"
        self.next_index += 1
        self._id_by_url[normalized] = result_id
        self._by_id[result_id] = {
            "url": str(url).strip(),
            "payload": payload or {},
            "discovered_via": discovered_via,
            "parent_alias": parent_alias,
            "source_name": source_name,
            "title": title,
            "image_url": image_url,
            "published_at": published_at,
        }
        return result_id

    def resolve_url(self, result_id: str | None) -> str | None:
        key = str(result_id or "").strip()
        if not key:
            return None
        record = self._by_id.get(key)
        if not isinstance(record, dict):
            return None
        url = str(record.get("url") or "").strip()
        return url or None

    def known_ids(self, *, limit: int = 20) -> list[str]:
        return list(self._by_id.keys())[: max(0, int(limit))]

    def get_record(self, result_id: str | None) -> dict[str, Any] | None:
        key = str(result_id or "").strip()
        record = self._by_id.get(key)
        return record if isinstance(record, dict) else None

    @staticmethod
    def _normalize_url(url: str) -> str:
        raw = str(url or "").strip()
        if not raw:
            return ""
        parsed = urllib.parse.urlparse(raw)
        if not parsed.scheme or not parsed.netloc:
            return raw.lower()
        clean = parsed._replace(fragment="", query="")
        normalized = urllib.parse.urlunparse(clean).rstrip("/")
        return normalized.lower()
