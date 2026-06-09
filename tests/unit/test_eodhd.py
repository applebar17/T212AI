from __future__ import annotations

from io import BytesIO
import json
import urllib.error
import urllib.parse

from t212ai.capabilities.services import EodhdSymbolReferenceService
from t212ai.data_sources.eodhd import EodhdApiError, EodhdClient
from t212ai.data_sources.eodhd.models import (
    EodhdIdentifierRecord,
    EodhdIdMappingResult,
    EodhdSearchCandidate,
    EodhdSearchResult,
)
from t212ai.genai.tools.symbol_reference import (
    symbol_reference_map_identifiers,
    symbol_reference_search,
)


class _FakeResponse:
    def __init__(self, body: object) -> None:
        self.body = json.dumps(body).encode("utf-8") if not isinstance(body, bytes) else body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def read(self) -> bytes:
        return self.body


class _FakeSymbolReferenceService:
    provider_name = "eodhd"

    def search(self, query: str, **_kwargs):
        from t212ai.capabilities.symbol_reference_models import SymbolReferenceSearchResult

        return SymbolReferenceSearchResult(
            query=query,
            candidates=[
                {
                    "code": "AAPL",
                    "exchange": "US",
                    "provider_symbol": "AAPL.US",
                    "name": "Apple Inc",
                    "isin": "US0378331005",
                }
            ],
            meta={"provider": "eodhd"},
        )

    def map_identifiers(self, **_kwargs):
        from t212ai.capabilities.symbol_reference_models import SymbolIdentifierMappingResult

        return SymbolIdentifierMappingResult(
            records=[
                {
                    "provider_symbol": "AAPL.US",
                    "isin": "US0378331005",
                    "cusip": "037833100",
                    "figi": None,
                    "lei": None,
                    "cik": "320193",
                }
            ],
            total=1,
            limit=100,
            offset=0,
            meta={"provider": "eodhd"},
        )


class _FakeEodhdClient:
    def search(self, query: str, **_kwargs):
        return EodhdSearchResult(
            query=query,
            candidates=[
                EodhdSearchCandidate(
                    code="AAPL",
                    exchange="US",
                    provider_symbol="AAPL.US",
                    name="Apple Inc",
                    isin="US0378331005",
                )
            ],
            request_params={"fmt": "json"},
        )

    def id_mapping(self, **_kwargs):
        return EodhdIdMappingResult(
            records=[
                EodhdIdentifierRecord(
                    provider_symbol="AAPL.US",
                    isin="US0378331005",
                    cusip="037833100",
                )
            ],
            total=1,
            limit=100,
            offset=0,
            request_params={"fmt": "json"},
        )


def test_eodhd_search_builds_query_sanitizes_token_and_normalizes_rows(monkeypatch) -> None:
    import t212ai.data_sources.eodhd.client as client_module

    captured: dict[str, object] = {}

    def _fake_urlopen(url, timeout):
        captured["url"] = url
        captured["timeout"] = timeout
        return _FakeResponse(
            [
                {
                    "Code": "AAPL",
                    "Exchange": "US",
                    "Name": "Apple Inc",
                    "Type": "stock",
                    "Country": "USA",
                    "Currency": "USD",
                    "ISIN": "US0378331005",
                    "previousClose": "195.64",
                    "previousCloseDate": "2026-06-08",
                    "isPrimary": True,
                }
            ]
        )

    monkeypatch.setattr(client_module.urllib.request, "urlopen", _fake_urlopen)
    client = EodhdClient(api_token="secret-token", base_url="https://eodhd.test/api")

    result = client.search(
        "Apple Inc",
        limit=5,
        asset_type="stock",
        exchange="US",
        bonds_only=False,
    )
    parsed = urllib.parse.urlparse(str(captured["url"]))
    query = urllib.parse.parse_qs(parsed.query)

    assert parsed.path == "/api/search/Apple%20Inc"
    assert query["api_token"] == ["secret-token"]
    assert query["fmt"] == ["json"]
    assert query["limit"] == ["5"]
    assert query["type"] == ["stock"]
    assert query["exchange"] == ["US"]
    assert "api_token" not in result.request_params
    assert result.candidates[0].provider_symbol == "AAPL.US"
    assert result.candidates[0].isin == "US0378331005"
    assert result.candidates[0].previous_close == 195.64


def test_eodhd_id_mapping_parses_paginated_identifier_records(monkeypatch) -> None:
    import t212ai.data_sources.eodhd.client as client_module

    captured: dict[str, object] = {}

    def _fake_urlopen(url, timeout):
        del timeout
        captured["url"] = url
        return _FakeResponse(
            {
                "data": [
                    {
                        "symbol": "AAPL.US",
                        "isin": "US0378331005",
                        "cusip": "037833100",
                        "figi": "BBG000B9XRY4",
                        "lei": "HWUPKR0MPOU8FGXBT394",
                        "cik": "320193",
                    }
                ],
                "meta": {"total": 1, "limit": 25, "offset": 0},
                "links": {
                    "next": (
                        "https://eodhd.test/api/id-mapping?"
                        "api_token=secret-token&page[offset]=25"
                    )
                },
            }
        )

    monkeypatch.setattr(client_module.urllib.request, "urlopen", _fake_urlopen)
    client = EodhdClient(api_token="secret-token", base_url="https://eodhd.test/api")

    result = client.id_mapping(isin="US0378331005", limit=25)
    parsed = urllib.parse.urlparse(str(captured["url"]))
    query = urllib.parse.parse_qs(parsed.query)

    assert parsed.path == "/api/id-mapping"
    assert query["filter[isin]"] == ["US0378331005"]
    assert query["page[limit]"] == ["25"]
    assert "api_token" not in result.request_params
    assert result.records[0].provider_symbol == "AAPL.US"
    assert result.records[0].cusip == "037833100"
    assert result.next_url is not None
    assert "api_token" not in result.next_url


def test_eodhd_id_mapping_requires_at_least_one_identifier() -> None:
    client = EodhdClient(api_token="secret-token")

    try:
        client.id_mapping()
    except ValueError as exc:
        assert "At least one identifier filter is required" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected ValueError")


def test_eodhd_http_and_json_errors_are_contextual_and_token_safe(monkeypatch) -> None:
    import t212ai.data_sources.eodhd.client as client_module

    def _fake_http_error(url, timeout):
        del timeout
        raise urllib.error.HTTPError(
            url,
            429,
            "Too Many Requests",
            hdrs={},
            fp=BytesIO(b"token secret-token was rejected"),
        )

    monkeypatch.setattr(client_module.urllib.request, "urlopen", _fake_http_error)
    client = EodhdClient(api_token="secret-token")

    try:
        client.search("AAPL")
    except EodhdApiError as exc:
        assert exc.context.status_code == 429
        assert exc.context.retryable
        assert "secret-token" not in exc.context.details["body_preview"]
    else:  # pragma: no cover
        raise AssertionError("Expected EodhdApiError")

    def _fake_invalid_json(url, timeout):
        del url, timeout
        return _FakeResponse(b"not-json secret-token")

    monkeypatch.setattr(client_module.urllib.request, "urlopen", _fake_invalid_json)
    try:
        client.search("AAPL")
    except EodhdApiError as exc:
        assert "invalid JSON" in (exc.context.message or "")
        assert "secret-token" not in exc.context.details["body_preview"]
    else:  # pragma: no cover
        raise AssertionError("Expected EodhdApiError")


def test_eodhd_malformed_payloads_raise_api_errors(monkeypatch) -> None:
    import t212ai.data_sources.eodhd.client as client_module

    monkeypatch.setattr(
        client_module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _FakeResponse({"not": "a list"}),
    )
    client = EodhdClient(api_token="secret-token")

    try:
        client.search("AAPL")
    except EodhdApiError as exc:
        assert "non-list" in (exc.context.message or "")
    else:  # pragma: no cover
        raise AssertionError("Expected EodhdApiError")

    monkeypatch.setattr(
        client_module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _FakeResponse({"data": {}}),
    )
    try:
        client.id_mapping(symbol="AAPL.US")
    except EodhdApiError as exc:
        assert "data array" in (exc.context.message or "")
    else:  # pragma: no cover
        raise AssertionError("Expected EodhdApiError")


def test_eodhd_symbol_reference_service_satisfies_protocol() -> None:
    service = EodhdSymbolReferenceService(_FakeEodhdClient())  # type: ignore[arg-type]

    search = service.search("apple")
    mapping = service.map_identifiers(isin="US0378331005")

    assert search.meta["provider"] == "eodhd"
    assert search.candidates[0]["provider_symbol"] == "AAPL.US"
    assert mapping.records[0]["cusip"] == "037833100"
    assert mapping.meta["authority"] == "reference_data_only"


def test_symbol_reference_tools_handle_success_missing_service_and_filters() -> None:
    service = _FakeSymbolReferenceService()

    search = symbol_reference_search(query="apple", service=service)
    mapping = symbol_reference_map_identifiers(
        symbol=None,
        exchange=None,
        isin="US0378331005",
        figi=None,
        lei=None,
        cusip=None,
        cik=None,
        service=service,
    )
    missing = symbol_reference_search(query="apple", service=None)
    invalid = symbol_reference_map_identifiers(
        symbol=None,
        exchange=None,
        isin=None,
        figi=None,
        lei=None,
        cusip=None,
        cik=None,
        service=service,
    )

    assert search.status == "ok"
    assert "reference data only" in search.output
    assert search.data["candidates"][0]["isin"] == "US0378331005"
    assert mapping.status == "ok"
    assert mapping.data["records"][0]["cusip"] == "037833100"
    assert missing.status == "error"
    assert missing.error.code == "symbol_reference_not_configured"
    assert invalid.status == "error"
    assert invalid.error.code == "symbol_reference_missing_identifier_filter"
