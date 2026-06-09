"""EODHD symbol-reference API client."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any

from t212ai.app.config import AppSettings, get_app_settings

from .models import (
    EodhdErrorContext,
    EodhdIdentifierRecord,
    EodhdIdMappingResult,
    EodhdSearchCandidate,
    EodhdSearchResult,
)


EODHD_BASE_URL = "https://eodhd.com/api"
SEARCH_TYPES = frozenset({"all", "stock", "etf", "fund", "bond", "index", "crypto"})
SECRET_QUERY_KEYS = frozenset({"api_token"})


class EodhdApiError(RuntimeError):
    def __init__(self, context: EodhdErrorContext) -> None:
        super().__init__(context.message or "EODHD request failed.")
        self.context = context


class EodhdClient:
    def __init__(
        self,
        *,
        api_token: str,
        base_url: str = EODHD_BASE_URL,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not str(api_token or "").strip():
            raise RuntimeError("EODHD_API_TOKEN is required.")
        self.api_token = str(api_token).strip()
        self.base_url = str(base_url or EODHD_BASE_URL).rstrip("/")
        self.timeout_seconds = float(timeout_seconds)

    @classmethod
    def from_settings(cls, settings: AppSettings | None = None) -> "EodhdClient":
        resolved = settings or get_app_settings()
        if not resolved.eodhd_api_token:
            raise RuntimeError("EODHD_API_TOKEN is required.")
        return cls(
            api_token=resolved.eodhd_api_token,
            base_url=resolved.eodhd_base_url,
        )

    def search(
        self,
        query: str,
        *,
        limit: int = 15,
        asset_type: str = "all",
        exchange: str | None = None,
        bonds_only: bool = False,
    ) -> EodhdSearchResult:
        resolved_query = _required_text(query, "query")
        resolved_limit = _bounded_int(limit, default=15, minimum=1, maximum=500)
        resolved_type = _normalize_search_type(asset_type)
        endpoint = f"{self.base_url}/search/{urllib.parse.quote(resolved_query, safe='')}"
        params: dict[str, Any] = {
            "api_token": self.api_token,
            "fmt": "json",
            "limit": resolved_limit,
            "type": resolved_type,
        }
        if str(exchange or "").strip():
            params["exchange"] = str(exchange).strip()
        if bonds_only:
            params["bonds_only"] = 1
        raw = self._read_json(endpoint, params=params, operation="search")
        if not isinstance(raw, list):
            raise EodhdApiError(
                EodhdErrorContext(
                    operation="search",
                    endpoint=endpoint,
                    message="EODHD search returned a non-list JSON payload.",
                    details={"payload_type": type(raw).__name__},
                )
            )
        return EodhdSearchResult(
            query=resolved_query,
            candidates=[_parse_search_candidate(item) for item in raw if isinstance(item, Mapping)],
            request_params=_sanitize_params(params),
            endpoint=endpoint,
        )

    def id_mapping(
        self,
        *,
        symbol: str | None = None,
        exchange: str | None = None,
        isin: str | None = None,
        figi: str | None = None,
        lei: str | None = None,
        cusip: str | None = None,
        cik: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> EodhdIdMappingResult:
        filters = _id_mapping_filters(
            symbol=symbol,
            exchange=exchange,
            isin=isin,
            figi=figi,
            lei=lei,
            cusip=cusip,
            cik=cik,
        )
        if not filters:
            raise ValueError(
                "At least one identifier filter is required: symbol, exchange, isin, "
                "figi, lei, cusip, or cik."
            )
        resolved_limit = _bounded_int(limit, default=100, minimum=1, maximum=1000)
        resolved_offset = max(0, _bounded_int(offset, default=0, minimum=0, maximum=10_000_000))
        endpoint = f"{self.base_url}/id-mapping"
        params: dict[str, Any] = {
            "api_token": self.api_token,
            "fmt": "json",
            "page[limit]": resolved_limit,
            "page[offset]": resolved_offset,
            **filters,
        }
        raw = self._read_json(endpoint, params=params, operation="id_mapping")
        records_payload, meta, next_url = _id_mapping_payload(raw)
        records = [
            _parse_identifier_record(item)
            for item in records_payload
            if isinstance(item, Mapping)
        ]
        total = _optional_int(meta.get("total")) if isinstance(meta, Mapping) else None
        response_limit = _optional_int(meta.get("limit")) if isinstance(meta, Mapping) else None
        response_offset = _optional_int(meta.get("offset")) if isinstance(meta, Mapping) else None
        return EodhdIdMappingResult(
            records=records,
            total=total if total is not None else len(records),
            limit=response_limit if response_limit is not None else resolved_limit,
            offset=response_offset if response_offset is not None else resolved_offset,
            next_url=_sanitize_url(next_url),
            request_params=_sanitize_params(params),
            endpoint=endpoint,
        )

    def _read_json(
        self,
        endpoint: str,
        *,
        params: Mapping[str, Any],
        operation: str,
    ) -> Any:
        url = _build_url(endpoint, params)
        try:
            with urllib.request.urlopen(url, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raw_body = exc.read().decode("utf-8", errors="replace")
            raise EodhdApiError(
                EodhdErrorContext(
                    operation=operation,
                    endpoint=endpoint,
                    status_code=exc.code,
                    message=f"EODHD HTTP {exc.code} while calling {operation}.",
                    retryable=exc.code in {408, 429, 500, 502, 503, 504},
                    details={"body_preview": _sanitize_text(raw_body[:400], self.api_token)},
                )
            ) from exc
        except urllib.error.URLError as exc:
            raise EodhdApiError(
                EodhdErrorContext(
                    operation=operation,
                    endpoint=endpoint,
                    message=f"Network error contacting EODHD for {operation}: {exc.reason}.",
                    retryable=True,
                )
            ) from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EodhdApiError(
                EodhdErrorContext(
                    operation=operation,
                    endpoint=endpoint,
                    message=f"EODHD returned invalid JSON for {operation}.",
                    retryable=False,
                    details={"body_preview": _sanitize_text(raw[:400], self.api_token)},
                )
            ) from exc


def _build_url(endpoint: str, params: Mapping[str, Any]) -> str:
    return endpoint + "?" + urllib.parse.urlencode(
        {key: value for key, value in params.items() if value is not None}
    )


def _required_text(value: str, name: str) -> str:
    resolved = str(value or "").strip()
    if not resolved:
        raise ValueError(f"{name} is required.")
    return resolved


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _normalize_search_type(value: str | None) -> str:
    resolved = str(value or "all").strip().lower()
    if resolved not in SEARCH_TYPES:
        raise ValueError(
            "asset_type must be one of: " + ", ".join(sorted(SEARCH_TYPES)) + "."
        )
    return resolved


def _id_mapping_filters(**values: str | None) -> dict[str, str]:
    mapping = {
        "symbol": "filter[symbol]",
        "exchange": "filter[ex]",
        "isin": "filter[isin]",
        "figi": "filter[figi]",
        "lei": "filter[lei]",
        "cusip": "filter[cusip]",
        "cik": "filter[cik]",
    }
    return {
        mapping[key]: str(value).strip()
        for key, value in values.items()
        if str(value or "").strip()
    }


def _parse_search_candidate(item: Mapping[str, Any]) -> EodhdSearchCandidate:
    raw = dict(item)
    code = _text(raw.get("Code") or raw.get("code"))
    exchange = _text(raw.get("Exchange") or raw.get("exchange"))
    provider_symbol = _provider_symbol(code, exchange)
    return EodhdSearchCandidate(
        code=code or "",
        exchange=exchange,
        provider_symbol=provider_symbol,
        name=_text(raw.get("Name") or raw.get("name")),
        instrument_type=_text(raw.get("Type") or raw.get("type")),
        country=_text(raw.get("Country") or raw.get("country")),
        currency=_text(raw.get("Currency") or raw.get("currency")),
        isin=_text(raw.get("ISIN") or raw.get("isin")),
        previous_close=_optional_float(raw.get("previousClose") or raw.get("previous_close")),
        previous_close_date=_text(
            raw.get("previousCloseDate") or raw.get("previous_close_date")
        ),
        is_primary=_optional_bool(raw.get("isPrimary") or raw.get("is_primary")),
        raw=raw,
    )


def _id_mapping_payload(raw: Any) -> tuple[list[Any], Mapping[str, Any], str | None]:
    if isinstance(raw, list):
        return raw, {"total": len(raw)}, None
    if not isinstance(raw, Mapping):
        raise EodhdApiError(
            EodhdErrorContext(
                operation="id_mapping",
                endpoint=f"{EODHD_BASE_URL}/id-mapping",
                message="EODHD ID mapping returned a non-object JSON payload.",
                details={"payload_type": type(raw).__name__},
            )
        )
    data = raw.get("data")
    if not isinstance(data, list):
        raise EodhdApiError(
            EodhdErrorContext(
                operation="id_mapping",
                endpoint=f"{EODHD_BASE_URL}/id-mapping",
                message="EODHD ID mapping returned a payload without a data array.",
                details={"data_type": type(data).__name__},
            )
        )
    meta = raw.get("meta") if isinstance(raw.get("meta"), Mapping) else {}
    links = raw.get("links") if isinstance(raw.get("links"), Mapping) else {}
    return data, meta, _text(links.get("next"))


def _parse_identifier_record(item: Mapping[str, Any]) -> EodhdIdentifierRecord:
    raw = dict(item)
    code = _text(raw.get("Code") or raw.get("code"))
    exchange = _text(raw.get("Exchange") or raw.get("exchange"))
    return EodhdIdentifierRecord(
        provider_symbol=_text(raw.get("symbol")) or _provider_symbol(code, exchange),
        isin=_text(raw.get("isin") or raw.get("ISIN")),
        figi=_text(raw.get("figi") or raw.get("FIGI")),
        lei=_text(raw.get("lei") or raw.get("LEI")),
        cusip=_text(raw.get("cusip") or raw.get("CUSIP")),
        cik=_text(raw.get("cik") or raw.get("CIK")),
        raw=raw,
    )


def _provider_symbol(code: str | None, exchange: str | None) -> str | None:
    if not code:
        return None
    if exchange:
        return f"{code}.{exchange}"
    return code


def _text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def _sanitize_params(params: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in params.items()
        if key.lower() not in SECRET_QUERY_KEYS
    }


def _sanitize_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urllib.parse.urlsplit(value)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    sanitized = urllib.parse.urlencode(
        [(key, item) for key, item in query if key.lower() not in SECRET_QUERY_KEYS]
    )
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, sanitized, parsed.fragment)
    )


def _sanitize_text(value: str, token: str | None) -> str:
    if not value:
        return value
    sanitized = value.replace("YOUR_API_TOKEN", "<redacted>")
    if token:
        sanitized = sanitized.replace(str(token), "<redacted>")
    return sanitized
