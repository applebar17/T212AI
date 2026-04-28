from __future__ import annotations

import json
import urllib.parse

from t212ai.data_sources.alpha_vantage import (
    ALPHA_VANTAGE_INTELLIGENCE_TOOLBOX,
    AlphaVantageClient,
    AlphaVantageResponse,
    AlphaVantageToolRuntime,
    alpha_vantage_most_actively_traded,
    build_alpha_vantage_intelligence_tool_mapping,
)
from t212ai.data_sources.alpha_vantage.client import (
    AlphaVantageApiError,
)
from t212ai.data_sources.alpha_vantage.models import AlphaVantageErrorContext
from t212ai.data_sources.alpha_vantage.tools import (
    alpha_vantage_news_sentiment,
)


class StubAlphaVantageClient(AlphaVantageClient):
    def __init__(self, payload: str) -> None:
        super().__init__(api_key="demo")
        self.payload = payload
        self.last_url: str | None = None
        self.last_function: str | None = None

    def _read_url(self, url: str, *, function: str | None) -> str:
        self.last_url = url
        self.last_function = function
        return self.payload


class FakeIntelligenceClient:
    def news_sentiment(self, **_kwargs: object) -> AlphaVantageResponse:
        return AlphaVantageResponse(
            function="NEWS_SENTIMENT",
            request_params={"function": "NEWS_SENTIMENT", "tickers": "AAPL"},
            data={
                "items": "1",
                "feed": [
                    {
                        "title": "Apple headline",
                        "url": "https://example.com/aapl",
                    }
                ],
            },
        )

    def top_gainers_losers(self, **_kwargs: object) -> AlphaVantageResponse:
        return AlphaVantageResponse(
            function="TOP_GAINERS_LOSERS",
            request_params={"function": "TOP_GAINERS_LOSERS"},
            data={
                "top_gainers": [],
                "top_losers": [],
                "most_actively_traded": [
                    {
                        "ticker": "AAPL",
                        "price": "190.00",
                        "change_percentage": "1.20%",
                        "volume": "1000000",
                    },
                    {
                        "ticker": "TSLA",
                        "price": "170.00",
                        "change_percentage": "4.10%",
                        "volume": "900000",
                    },
                ],
            },
        )


class FailingIntelligenceClient:
    def news_sentiment(self, **_kwargs: object) -> AlphaVantageResponse:
        raise AlphaVantageApiError(
            AlphaVantageErrorContext(
                function="NEWS_SENTIMENT",
                message="Thank you for using Alpha Vantage. Our standard API rate limit is hit.",
                retryable=True,
                details={"response_key": "Note"},
            )
        )


def test_news_sentiment_builds_alpha_vantage_query_and_sanitizes_api_key() -> None:
    client = StubAlphaVantageClient(
        json.dumps({"items": "0", "feed": []}),
    )

    response = client.news_sentiment(
        tickers=["AAPL", "MSFT"],
        topics=["technology"],
        limit=10,
    )
    query = urllib.parse.parse_qs(urllib.parse.urlparse(client.last_url or "").query)

    assert query["function"] == ["NEWS_SENTIMENT"]
    assert query["tickers"] == ["AAPL,MSFT"]
    assert query["topics"] == ["technology"]
    assert query["apikey"] == ["demo"]
    assert response.request_params["tickers"] == "AAPL,MSFT"
    assert "apikey" not in response.request_params


def test_csv_fundamental_endpoints_parse_rows_without_datatype_param() -> None:
    client = StubAlphaVantageClient("symbol,name\nIBM,International Business Machines\n")

    response = client.listing_status()
    query = urllib.parse.parse_qs(urllib.parse.urlparse(client.last_url or "").query)

    assert query["function"] == ["LISTING_STATUS"]
    assert "datatype" not in query
    assert response.datatype == "csv"
    assert response.data == [
        {
            "symbol": "IBM",
            "name": "International Business Machines",
        }
    ]


def test_alpha_vantage_api_messages_raise_contextual_error() -> None:
    client = StubAlphaVantageClient(json.dumps({"Note": "rate limit reached"}))

    try:
        client.global_quote("IBM")
    except AlphaVantageApiError as exc:
        assert exc.context.function == "GLOBAL_QUOTE"
        assert exc.context.retryable
        assert exc.context.details["response_key"] == "Note"
    else:  # pragma: no cover
        raise AssertionError("Expected AlphaVantageApiError")


def test_alpha_vantage_news_sentiment_tool_returns_informative_output() -> None:
    runtime = AlphaVantageToolRuntime(client=FakeIntelligenceClient())  # type: ignore[arg-type]

    result = alpha_vantage_news_sentiment(
        tickers=["AAPL"],
        topics=None,
        time_from=None,
        time_to=None,
        sort="LATEST",
        limit=50,
        runtime=runtime,
    )

    assert result.status == "ok"
    assert result.output is not None
    assert "news_items=1" in result.output
    assert "third-party intelligence context" in result.output
    assert result.data["function"] == "NEWS_SENTIMENT"


def test_alpha_vantage_most_actively_traded_tool_returns_volume_context() -> None:
    runtime = AlphaVantageToolRuntime(client=FakeIntelligenceClient())  # type: ignore[arg-type]

    result = alpha_vantage_most_actively_traded(
        entitlement=None,
        limit=1,
        runtime=runtime,
    )

    assert result.status == "ok"
    assert result.output is not None
    assert "most-active volume context" in result.output
    assert "AAPL: price=190.00" in result.output
    assert len(result.data["most_actively_traded"]) == 1


def test_alpha_vantage_tool_errors_include_pivot_hint() -> None:
    runtime = AlphaVantageToolRuntime(client=FailingIntelligenceClient())  # type: ignore[arg-type]

    result = alpha_vantage_news_sentiment(
        tickers=["AAPL"],
        topics=None,
        time_from=None,
        time_to=None,
        sort="LATEST",
        limit=50,
        runtime=runtime,
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.retryable
    assert "rate-limited" in (result.error.hint or "")


def test_alpha_vantage_intelligence_toolbox_and_mapping() -> None:
    runtime = AlphaVantageToolRuntime(client=FakeIntelligenceClient())  # type: ignore[arg-type]
    mapping = build_alpha_vantage_intelligence_tool_mapping(runtime)

    assert ALPHA_VANTAGE_INTELLIGENCE_TOOLBOX.name == "alpha_vantage_intelligence"
    assert "alpha_vantage_news_sentiment" in ALPHA_VANTAGE_INTELLIGENCE_TOOLBOX.tools_by_name
    assert (
        "alpha_vantage_most_actively_traded"
        in ALPHA_VANTAGE_INTELLIGENCE_TOOLBOX.tools_by_name
    )
    assert "alpha_vantage_news_sentiment" in mapping
    assert "alpha_vantage_most_actively_traded" in mapping
