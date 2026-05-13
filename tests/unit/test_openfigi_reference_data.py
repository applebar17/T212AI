from __future__ import annotations

from typing import Any

from t212ai.reference_data import (
    OpenFigiApiError,
    OpenFigiClient,
    OpenFigiReferenceDataService,
    reference_identifier_map,
    reference_security_search,
)


class RecordingOpenFigiClient(OpenFigiClient):
    def __init__(self, payload: Any) -> None:
        super().__init__(api_key=None)
        self.payload = payload
        self.requests: list[dict[str, Any]] = []

    def _request_json(self, *, path: str, body: Any) -> Any:
        self.requests.append({"path": path, "body": body})
        return self.payload


class FailingOpenFigiClient(OpenFigiClient):
    def __init__(self, exc: Exception) -> None:
        super().__init__(api_key=None)
        self.exc = exc

    def _request_json(self, *, path: str, body: Any) -> Any:
        del path, body
        raise self.exc


def test_openfigi_headers_include_api_key_only_when_configured() -> None:
    assert "X-OPENFIGI-APIKEY" not in OpenFigiClient()._headers()
    assert OpenFigiClient(api_key="figi-key")._headers()["X-OPENFIGI-APIKEY"] == "figi-key"


def test_reference_security_search_builds_payload_and_normalizes_candidates() -> None:
    client = RecordingOpenFigiClient(
        {
            "data": [
                {
                    "figi": "BBG000BLNNH6",
                    "name": "INTL BUSINESS MACHINES CORP",
                    "ticker": "IBM",
                    "exchCode": "US",
                    "compositeFIGI": "BBG000BLNNH6",
                    "shareClassFIGI": "BBG001S5S399",
                    "securityType": "Common Stock",
                    "marketSector": "Equity",
                    "securityType2": "Common Stock",
                    "securityDescription": "IBM",
                }
            ],
            "next": "cursor",
        }
    )
    service = OpenFigiReferenceDataService(client)

    result = service.search_security(
        query="ibm",
        exch_code="US",
        market_sector="Equity",
        security_type2="Common Stock",
        limit=5,
    )

    assert result.status == "ok"
    assert client.requests == [
        {
            "path": "/v3/search",
            "body": {
                "query": "ibm",
                "exchCode": "US",
                "marketSecDes": "Equity",
                "securityType2": "Common Stock",
            },
        }
    ]
    candidate = result.data["candidates"][0]
    assert candidate["source"] == "openfigi"
    assert candidate["ticker"] == "IBM"
    assert candidate["figi"] == "BBG000BLNNH6"
    assert candidate["compositeFigi"] == "BBG000BLNNH6"
    assert result.data["referenceOnly"] is True


def test_reference_identifier_map_builds_payload_and_preserves_input_isin() -> None:
    client = RecordingOpenFigiClient(
        [
            {
                "data": [
                    {
                        "figi": "BBG000B9XRY4",
                        "name": "APPLE INC",
                        "ticker": "AAPL",
                        "exchCode": "US",
                        "securityType2": "Common Stock",
                    }
                ]
            }
        ]
    )
    service = OpenFigiReferenceDataService(client)

    result = service.map_identifier(
        id_type="ID_ISIN",
        id_value="us0378331005",
        exch_code="US",
        currency="USD",
        limit=3,
    )

    assert result.status == "ok"
    assert client.requests == [
        {
            "path": "/v3/mapping",
            "body": [
                {
                    "idType": "ID_ISIN",
                    "idValue": "us0378331005",
                    "exchCode": "US",
                    "currency": "USD",
                }
            ],
        }
    ]
    candidate = result.data["candidates"][0]
    assert candidate["ticker"] == "AAPL"
    assert candidate["isin"] == "US0378331005"


def test_openfigi_warning_no_match_returns_empty_candidates() -> None:
    service = OpenFigiReferenceDataService(
        RecordingOpenFigiClient([{"warning": "No identifier found."}])
    )

    result = service.map_identifier(id_type="ID_ISIN", id_value="US0000000000")

    assert result.status == "ok"
    assert result.data["candidates"] == []
    assert result.data["warning"] == "No identifier found."


def test_openfigi_errors_return_structured_tool_errors() -> None:
    service = OpenFigiReferenceDataService(
        FailingOpenFigiClient(
            OpenFigiApiError(
                "OpenFIGI request failed with HTTP 429.",
                status_code=429,
                code="rate_limited",
            )
        )
    )

    result = service.search_security(query="apple")

    assert result.status == "error"
    assert result.error.code == "rate_limited"
    assert result.error.retryable is True


def test_reference_tools_report_unavailable_service() -> None:
    search = reference_security_search(query="apple", service=None)
    mapping = reference_identifier_map(
        id_type="ID_ISIN",
        id_value="US0378331005",
        service=None,
    )

    assert search.status == "error"
    assert search.error.code == "reference_data_not_configured"
    assert mapping.status == "error"
    assert mapping.error.code == "reference_data_not_configured"
