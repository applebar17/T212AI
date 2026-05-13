"""OpenFIGI reference-data client and provider-neutral service."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.client import HTTPResponse
from typing import TYPE_CHECKING, Any

from t212ai.genai.models import ToolError, ToolResult

if TYPE_CHECKING:
    from t212ai.app.config import AppSettings


OPENFIGI_BASE_URL = "https://api.openfigi.com"
OPENFIGI_SOURCE = "openfigi"


class OpenFigiApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: str | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.code = code


@dataclass(slots=True)
class OpenFigiClient:
    api_key: str | None = None
    base_url: str = OPENFIGI_BASE_URL
    timeout_seconds: float = 20.0

    @classmethod
    def from_settings(cls, settings: AppSettings | None = None) -> OpenFigiClient:
        if settings is None:
            from t212ai.app.config import get_app_settings

            resolved = get_app_settings()
        else:
            resolved = settings
        return cls(
            api_key=resolved.openfigi_api_key,
            base_url=resolved.openfigi_base_url,
        )

    def search(
        self,
        *,
        query: str,
        start: str | None = None,
        exch_code: str | None = None,
        mic_code: str | None = None,
        currency: str | None = None,
        market_sector: str | None = None,
        security_type: str | None = None,
        security_type2: str | None = None,
        include_unlisted_equities: bool | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        body = _clean_payload(
            {
                "query": query,
                "start": start,
                "exchCode": exch_code,
                "micCode": mic_code,
                "currency": currency,
                "marketSecDes": market_sector,
                "securityType": security_type,
                "securityType2": security_type2,
                "includeUnlistedEquities": include_unlisted_equities,
            }
        )
        payload = self._request_json(path="/v3/search", body=body)
        if not isinstance(payload, dict):
            raise OpenFigiApiError("OpenFIGI search returned an unexpected payload.")
        data = payload.get("data")
        if isinstance(data, list):
            payload["data"] = data[: max(1, int(limit))]
        return payload

    def map_identifier(
        self,
        *,
        id_type: str,
        id_value: str,
        exch_code: str | None = None,
        mic_code: str | None = None,
        currency: str | None = None,
        market_sector: str | None = None,
        security_type: str | None = None,
        security_type2: str | None = None,
        include_unlisted_equities: bool | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        job = _clean_payload(
            {
                "idType": id_type,
                "idValue": id_value,
                "exchCode": exch_code,
                "micCode": mic_code,
                "currency": currency,
                "marketSecDes": market_sector,
                "securityType": security_type,
                "securityType2": security_type2,
                "includeUnlistedEquities": include_unlisted_equities,
            }
        )
        payload = self._request_json(path="/v3/mapping", body=[job])
        if not isinstance(payload, list):
            raise OpenFigiApiError("OpenFIGI mapping returned an unexpected payload.")
        if payload and isinstance(payload[0], dict):
            data = payload[0].get("data")
            if isinstance(data, list):
                payload[0]["data"] = data[: max(1, int(limit))]
        return payload

    def _request_json(self, *, path: str, body: Any) -> Any:
        url = self._build_url(path)
        encoded_body = json.dumps(body, ensure_ascii=True, sort_keys=True).encode("utf-8")
        request = urllib.request.Request(
            url,
            headers=self._headers(),
            data=encoded_body,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = _read_response_payload(response)
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise OpenFigiApiError(
                f"OpenFIGI request failed with HTTP {exc.code}.",
                status_code=exc.code,
                body=body_text,
                code=_http_error_code(exc.code),
            ) from exc
        except urllib.error.URLError as exc:
            raise OpenFigiApiError(
                f"Network error contacting OpenFIGI: {exc.reason}",
                code="network_error",
            ) from exc
        if not payload:
            raise OpenFigiApiError(
                "OpenFIGI returned an empty response body.",
                code="empty_response",
            )
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise OpenFigiApiError(
                "OpenFIGI returned invalid JSON.",
                code="invalid_json",
                body=payload,
            ) from exc

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "t212ai-openfigi/1.0",
        }
        if str(self.api_key or "").strip():
            headers["X-OPENFIGI-APIKEY"] = str(self.api_key).strip()
        return headers

    def _build_url(self, path: str) -> str:
        cleaned_base = self.base_url.rstrip("/")
        cleaned_path = path if path.startswith("/") else f"/{path}"
        return urllib.parse.urljoin(f"{cleaned_base}/", cleaned_path.lstrip("/"))


@dataclass(slots=True)
class OpenFigiReferenceDataService:
    client: OpenFigiClient
    provider_name: str = OPENFIGI_SOURCE

    def search_security(
        self,
        *,
        query: str,
        exch_code: str | None = None,
        mic_code: str | None = None,
        currency: str | None = None,
        market_sector: str | None = None,
        security_type: str | None = None,
        security_type2: str | None = None,
        include_unlisted_equities: bool | None = None,
        limit: int = 10,
    ) -> ToolResult:
        resolved_query = str(query or "").strip()
        if not resolved_query:
            return _tool_error("query is required.", code="missing_query")
        try:
            payload = self.client.search(
                query=resolved_query,
                exch_code=exch_code,
                mic_code=mic_code,
                currency=currency,
                market_sector=market_sector,
                security_type=security_type,
                security_type2=security_type2,
                include_unlisted_equities=include_unlisted_equities,
                limit=limit,
            )
        except Exception as exc:
            return _exception_result(exc, operation="search")
        candidates = [
            _normalize_candidate(candidate)
            for candidate in payload.get("data", []) or []
            if isinstance(candidate, dict)
        ]
        if not candidates:
            warning = str(payload.get("warning") or payload.get("error") or "").strip()
            return ToolResult(
                status="ok",
                output=f"OpenFIGI returned no reference candidates for {resolved_query!r}.",
                data={
                    "provider": self.provider_name,
                    "query": resolved_query,
                    "candidates": [],
                    "warning": warning or None,
                    "next": payload.get("next"),
                },
            )
        return ToolResult(
            status="ok",
            output=(
                f"OpenFIGI returned {len(candidates)} reference candidate(s) "
                f"for {resolved_query!r}. These are not broker tradability results."
            ),
            data={
                "provider": self.provider_name,
                "query": resolved_query,
                "candidates": candidates,
                "next": payload.get("next"),
                "referenceOnly": True,
            },
        )

    def map_identifier(
        self,
        *,
        id_type: str,
        id_value: str,
        exch_code: str | None = None,
        mic_code: str | None = None,
        currency: str | None = None,
        market_sector: str | None = None,
        security_type: str | None = None,
        security_type2: str | None = None,
        include_unlisted_equities: bool | None = None,
        limit: int = 10,
    ) -> ToolResult:
        resolved_type = str(id_type or "").strip().upper()
        resolved_value = str(id_value or "").strip()
        if not resolved_type:
            return _tool_error("id_type is required.", code="missing_id_type")
        if not resolved_value:
            return _tool_error("id_value is required.", code="missing_id_value")
        try:
            payload = self.client.map_identifier(
                id_type=resolved_type,
                id_value=resolved_value,
                exch_code=exch_code,
                mic_code=mic_code,
                currency=currency,
                market_sector=market_sector,
                security_type=security_type,
                security_type2=security_type2,
                include_unlisted_equities=include_unlisted_equities,
                limit=limit,
            )
        except Exception as exc:
            return _exception_result(exc, operation="mapping")
        first = payload[0] if payload and isinstance(payload[0], dict) else {}
        candidates = [
            _normalize_candidate(
                candidate,
                isin=resolved_value.upper() if resolved_type == "ID_ISIN" else None,
            )
            for candidate in first.get("data", []) or []
            if isinstance(candidate, dict)
        ]
        warning = str(first.get("warning") or first.get("error") or "").strip()
        if not candidates:
            return ToolResult(
                status="ok",
                output=(
                    f"OpenFIGI returned no reference candidates for "
                    f"{resolved_type}:{resolved_value!r}."
                ),
                data={
                    "provider": self.provider_name,
                    "idType": resolved_type,
                    "idValue": resolved_value,
                    "candidates": [],
                    "warning": warning or None,
                },
            )
        return ToolResult(
            status="ok",
            output=(
                f"OpenFIGI mapped {resolved_type}:{resolved_value!r} to "
                f"{len(candidates)} reference candidate(s). Broker resolution is still required."
            ),
            data={
                "provider": self.provider_name,
                "idType": resolved_type,
                "idValue": resolved_value,
                "candidates": candidates,
                "referenceOnly": True,
            },
        )


def _normalize_candidate(candidate: dict[str, Any], *, isin: str | None = None) -> dict[str, Any]:
    return {
        "source": OPENFIGI_SOURCE,
        "name": candidate.get("name"),
        "ticker": candidate.get("ticker"),
        "isin": isin,
        "figi": candidate.get("figi"),
        "compositeFigi": candidate.get("compositeFIGI"),
        "shareClassFigi": candidate.get("shareClassFIGI"),
        "exchCode": candidate.get("exchCode"),
        "marketSector": candidate.get("marketSector"),
        "securityType": candidate.get("securityType"),
        "securityType2": candidate.get("securityType2"),
        "securityDescription": candidate.get("securityDescription"),
    }


def _clean_payload(values: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                continue
            cleaned[key] = stripped
            continue
        cleaned[key] = value
    return cleaned


def _read_response_payload(response: HTTPResponse) -> str:
    raw = response.read()
    if not raw:
        return ""
    return raw.decode("utf-8")


def _http_error_code(status_code: int) -> str:
    if status_code == 429:
        return "rate_limited"
    if status_code == 401:
        return "unauthorized"
    return "http_error"


def _exception_result(exc: Exception, *, operation: str) -> ToolResult:
    if isinstance(exc, OpenFigiApiError):
        return _tool_error(
            str(exc),
            code=exc.code or "openfigi_error",
            retryable=exc.status_code in {429, 500, 503} or exc.code in {"network_error"},
            details={
                "operation": operation,
                "provider": OPENFIGI_SOURCE,
                "status_code": exc.status_code,
            },
        )
    return _tool_error(
        f"OpenFIGI {operation} failed: {exc}",
        code="openfigi_error",
        details={"operation": operation, "provider": OPENFIGI_SOURCE},
    )


def _tool_error(
    message: str,
    *,
    code: str,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> ToolResult:
    return ToolResult(
        status="error",
        output=message,
        error=ToolError(
            message=message,
            code=code,
            type="reference_data",
            retryable=retryable,
            details=details,
        ),
    )
