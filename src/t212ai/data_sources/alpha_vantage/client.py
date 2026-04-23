"""Alpha Vantage API client."""

from __future__ import annotations

import csv
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from typing import Any

from t212ai.app.config import AppSettings, get_app_settings

from .models import AlphaVantageErrorContext, AlphaVantageResponse


ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"
JSON_API_MESSAGES = ("Error Message", "Note", "Information")
COMMODITY_FUNCTIONS = {
    "GOLD_SILVER_SPOT",
    "GOLD_SILVER_HISTORY",
    "WTI",
    "BRENT",
    "NATURAL_GAS",
    "COPPER",
    "ALUMINUM",
    "WHEAT",
    "CORN",
    "COTTON",
    "SUGAR",
    "COFFEE",
    "ALL_COMMODITIES",
}


class AlphaVantageApiError(RuntimeError):
    def __init__(self, context: AlphaVantageErrorContext) -> None:
        super().__init__(context.message or "Alpha Vantage request failed.")
        self.context = context


class AlphaVantageClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = ALPHA_VANTAGE_BASE_URL,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not str(api_key or "").strip():
            raise RuntimeError("Alpha Vantage API key is required.")
        self.api_key = api_key
        self.base_url = base_url
        self.timeout_seconds = float(timeout_seconds)

    @classmethod
    def from_settings(cls, settings: AppSettings | None = None) -> "AlphaVantageClient":
        resolved = settings or get_app_settings()
        if not resolved.alpha_vantage_api_key:
            raise RuntimeError("ALPHA_VANTAGE_API_KEY is required.")
        return cls(
            api_key=resolved.alpha_vantage_api_key,
            base_url=resolved.alpha_vantage_base_url,
        )

    def query(
        self,
        function: str,
        *,
        datatype: str = "json",
        send_datatype: bool | None = None,
        **params: Any,
    ) -> AlphaVantageResponse:
        resolved_function = _required_text(function, "function").upper()
        resolved_datatype = (datatype or "json").lower()
        request_params = {
            "function": resolved_function,
            **_clean_params(params),
            "apikey": self.api_key,
        }
        if send_datatype if send_datatype is not None else resolved_datatype != "json":
            request_params["datatype"] = resolved_datatype
        url = self._build_url(request_params)
        raw = self._read_url(url, function=resolved_function)
        sanitized = _sanitize_params(request_params)

        if resolved_datatype == "csv":
            rows = _parse_csv(raw)
            return AlphaVantageResponse(
                function=resolved_function,
                data=rows,
                request_params=sanitized,
                endpoint=self.base_url,
                datatype="csv",
            )

        data = _parse_json(raw, function=resolved_function)
        _raise_for_api_message(data, function=resolved_function)
        return AlphaVantageResponse(
            function=resolved_function,
            data=data,
            request_params=sanitized,
            endpoint=self.base_url,
            datatype="json",
        )

    # Time Series Stock Data APIs

    def time_series_intraday(
        self,
        symbol: str,
        *,
        interval: str,
        adjusted: bool | None = True,
        extended_hours: bool | None = True,
        month: str | None = None,
        outputsize: str | None = "compact",
        datatype: str = "json",
        entitlement: str | None = None,
    ) -> AlphaVantageResponse:
        return self.query(
            "TIME_SERIES_INTRADAY",
            symbol=_required_text(symbol, "symbol"),
            interval=_required_text(interval, "interval"),
            adjusted=adjusted,
            extended_hours=extended_hours,
            month=month,
            outputsize=outputsize,
            datatype=datatype,
            entitlement=entitlement,
        )

    def time_series_daily(
        self,
        symbol: str,
        *,
        outputsize: str | None = "compact",
        datatype: str = "json",
    ) -> AlphaVantageResponse:
        return self.query(
            "TIME_SERIES_DAILY",
            symbol=_required_text(symbol, "symbol"),
            outputsize=outputsize,
            datatype=datatype,
        )

    def time_series_daily_adjusted(
        self,
        symbol: str,
        *,
        outputsize: str | None = "compact",
        datatype: str = "json",
    ) -> AlphaVantageResponse:
        return self.query(
            "TIME_SERIES_DAILY_ADJUSTED",
            symbol=_required_text(symbol, "symbol"),
            outputsize=outputsize,
            datatype=datatype,
        )

    def time_series_weekly(
        self,
        symbol: str,
        *,
        datatype: str = "json",
    ) -> AlphaVantageResponse:
        return self.query(
            "TIME_SERIES_WEEKLY",
            symbol=_required_text(symbol, "symbol"),
            datatype=datatype,
        )

    def time_series_weekly_adjusted(
        self,
        symbol: str,
        *,
        datatype: str = "json",
    ) -> AlphaVantageResponse:
        return self.query(
            "TIME_SERIES_WEEKLY_ADJUSTED",
            symbol=_required_text(symbol, "symbol"),
            datatype=datatype,
        )

    def time_series_monthly(
        self,
        symbol: str,
        *,
        datatype: str = "json",
    ) -> AlphaVantageResponse:
        return self.query(
            "TIME_SERIES_MONTHLY",
            symbol=_required_text(symbol, "symbol"),
            datatype=datatype,
        )

    def time_series_monthly_adjusted(
        self,
        symbol: str,
        *,
        datatype: str = "json",
    ) -> AlphaVantageResponse:
        return self.query(
            "TIME_SERIES_MONTHLY_ADJUSTED",
            symbol=_required_text(symbol, "symbol"),
            datatype=datatype,
        )

    def global_quote(
        self,
        symbol: str,
        *,
        entitlement: str | None = None,
    ) -> AlphaVantageResponse:
        return self.query(
            "GLOBAL_QUOTE",
            symbol=_required_text(symbol, "symbol"),
            entitlement=entitlement,
        )

    def realtime_bulk_quotes(
        self,
        symbols: str | Iterable[str],
        *,
        entitlement: str | None = None,
    ) -> AlphaVantageResponse:
        return self.query(
            "REALTIME_BULK_QUOTES",
            symbol=_join_symbols(symbols),
            entitlement=entitlement,
        )

    def symbol_search(self, keywords: str) -> AlphaVantageResponse:
        return self.query("SYMBOL_SEARCH", keywords=_required_text(keywords, "keywords"))

    def market_status(self) -> AlphaVantageResponse:
        return self.query("MARKET_STATUS")

    # Alpha Intelligence(TM)

    def news_sentiment(
        self,
        *,
        tickers: str | Iterable[str] | None = None,
        topics: str | Iterable[str] | None = None,
        time_from: str | None = None,
        time_to: str | None = None,
        sort: str | None = "LATEST",
        limit: int | None = 50,
    ) -> AlphaVantageResponse:
        return self.query(
            "NEWS_SENTIMENT",
            tickers=_join_optional(tickers),
            topics=_join_optional(topics),
            time_from=time_from,
            time_to=time_to,
            sort=sort,
            limit=limit,
        )

    def earnings_call_transcript(self, symbol: str, quarter: str) -> AlphaVantageResponse:
        return self.query(
            "EARNINGS_CALL_TRANSCRIPT",
            symbol=_required_text(symbol, "symbol"),
            quarter=_required_text(quarter, "quarter"),
        )

    def top_gainers_losers(self, *, entitlement: str | None = None) -> AlphaVantageResponse:
        return self.query("TOP_GAINERS_LOSERS", entitlement=entitlement)

    def insider_transactions(self, symbol: str) -> AlphaVantageResponse:
        return self.query(
            "INSIDER_TRANSACTIONS",
            symbol=_required_text(symbol, "symbol"),
        )

    def institutional_holdings(self, symbol: str) -> AlphaVantageResponse:
        return self.query(
            "INSTITUTIONAL_HOLDINGS",
            symbol=_required_text(symbol, "symbol"),
        )

    def analytics_fixed_window(
        self,
        *,
        symbols: str | Iterable[str],
        range_: str,
        interval: str,
        calculations: str | Iterable[str],
        ohlc: str | None = "close",
    ) -> AlphaVantageResponse:
        return self.query(
            "ANALYTICS_FIXED_WINDOW",
            SYMBOLS=_join_symbols(symbols),
            RANGE=_required_text(range_, "range_"),
            INTERVAL=_required_text(interval, "interval"),
            OHLC=ohlc,
            CALCULATIONS=_join_symbols(calculations),
        )

    def analytics_sliding_window(
        self,
        *,
        symbols: str | Iterable[str],
        range_: str,
        interval: str,
        window_size: int,
        calculations: str | Iterable[str],
        ohlc: str | None = "close",
    ) -> AlphaVantageResponse:
        return self.query(
            "ANALYTICS_SLIDING_WINDOW",
            SYMBOLS=_join_symbols(symbols),
            RANGE=_required_text(range_, "range_"),
            INTERVAL=_required_text(interval, "interval"),
            OHLC=ohlc,
            WINDOW_SIZE=int(window_size),
            CALCULATIONS=_join_symbols(calculations),
        )

    # Fundamental Data

    def company_overview(self, symbol: str) -> AlphaVantageResponse:
        return self.query("OVERVIEW", symbol=_required_text(symbol, "symbol"))

    def etf_profile(self, symbol: str) -> AlphaVantageResponse:
        return self.query("ETF_PROFILE", symbol=_required_text(symbol, "symbol"))

    def dividends(self, symbol: str) -> AlphaVantageResponse:
        return self.query("DIVIDENDS", symbol=_required_text(symbol, "symbol"))

    def splits(self, symbol: str) -> AlphaVantageResponse:
        return self.query("SPLITS", symbol=_required_text(symbol, "symbol"))

    def income_statement(self, symbol: str) -> AlphaVantageResponse:
        return self.query("INCOME_STATEMENT", symbol=_required_text(symbol, "symbol"))

    def balance_sheet(self, symbol: str) -> AlphaVantageResponse:
        return self.query("BALANCE_SHEET", symbol=_required_text(symbol, "symbol"))

    def cash_flow(self, symbol: str) -> AlphaVantageResponse:
        return self.query("CASH_FLOW", symbol=_required_text(symbol, "symbol"))

    def shares_outstanding(self, symbol: str) -> AlphaVantageResponse:
        return self.query("SHARES_OUTSTANDING", symbol=_required_text(symbol, "symbol"))

    def earnings(self, symbol: str) -> AlphaVantageResponse:
        return self.query("EARNINGS", symbol=_required_text(symbol, "symbol"))

    def earnings_estimates(self, symbol: str) -> AlphaVantageResponse:
        return self.query("EARNINGS_ESTIMATES", symbol=_required_text(symbol, "symbol"))

    def listing_status(
        self,
        *,
        date: str | None = None,
        state: str | None = "active",
    ) -> AlphaVantageResponse:
        return self.query(
            "LISTING_STATUS",
            datatype="csv",
            send_datatype=False,
            date=date,
            state=state,
        )

    def earnings_calendar(
        self,
        *,
        symbol: str | None = None,
        horizon: str | None = "3month",
    ) -> AlphaVantageResponse:
        return self.query(
            "EARNINGS_CALENDAR",
            datatype="csv",
            send_datatype=False,
            symbol=symbol,
            horizon=horizon,
        )

    def ipo_calendar(self) -> AlphaVantageResponse:
        return self.query("IPO_CALENDAR", datatype="csv", send_datatype=False)

    # Commodities

    def gold_silver_spot(self, symbol: str) -> AlphaVantageResponse:
        return self.query("GOLD_SILVER_SPOT", symbol=_required_text(symbol, "symbol"))

    def gold_silver_history(
        self,
        symbol: str,
        *,
        interval: str,
    ) -> AlphaVantageResponse:
        return self.query(
            "GOLD_SILVER_HISTORY",
            symbol=_required_text(symbol, "symbol"),
            interval=_required_text(interval, "interval"),
        )

    def commodity_series(
        self,
        function: str,
        *,
        interval: str | None = "monthly",
        datatype: str = "json",
    ) -> AlphaVantageResponse:
        resolved_function = _required_text(function, "function").upper()
        if resolved_function not in COMMODITY_FUNCTIONS:
            allowed = ", ".join(sorted(COMMODITY_FUNCTIONS))
            raise ValueError(f"Unsupported commodity function. Allowed: {allowed}.")
        return self.query(resolved_function, interval=interval, datatype=datatype)

    def wti(self, *, interval: str | None = "monthly") -> AlphaVantageResponse:
        return self.commodity_series("WTI", interval=interval)

    def brent(self, *, interval: str | None = "monthly") -> AlphaVantageResponse:
        return self.commodity_series("BRENT", interval=interval)

    def natural_gas(self, *, interval: str | None = "monthly") -> AlphaVantageResponse:
        return self.commodity_series("NATURAL_GAS", interval=interval)

    def copper(self, *, interval: str | None = "monthly") -> AlphaVantageResponse:
        return self.commodity_series("COPPER", interval=interval)

    def aluminum(self, *, interval: str | None = "monthly") -> AlphaVantageResponse:
        return self.commodity_series("ALUMINUM", interval=interval)

    def wheat(self, *, interval: str | None = "monthly") -> AlphaVantageResponse:
        return self.commodity_series("WHEAT", interval=interval)

    def corn(self, *, interval: str | None = "monthly") -> AlphaVantageResponse:
        return self.commodity_series("CORN", interval=interval)

    def cotton(self, *, interval: str | None = "monthly") -> AlphaVantageResponse:
        return self.commodity_series("COTTON", interval=interval)

    def sugar(self, *, interval: str | None = "monthly") -> AlphaVantageResponse:
        return self.commodity_series("SUGAR", interval=interval)

    def coffee(self, *, interval: str | None = "monthly") -> AlphaVantageResponse:
        return self.commodity_series("COFFEE", interval=interval)

    def all_commodities(self, *, interval: str | None = "monthly") -> AlphaVantageResponse:
        return self.commodity_series("ALL_COMMODITIES", interval=interval)

    def _build_url(self, params: dict[str, Any]) -> str:
        query = urllib.parse.urlencode(params)
        return f"{self.base_url}?{query}"

    def _read_url(self, url: str, *, function: str | None) -> str:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "t212ai-alpha-vantage/0.1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raw_body = exc.read().decode("utf-8", errors="replace")
            raise AlphaVantageApiError(
                AlphaVantageErrorContext(
                    function=function,
                    status_code=exc.code,
                    message=f"Alpha Vantage HTTP {exc.code}.",
                    retryable=exc.code >= 500 or exc.code == 429,
                    details={"body": raw_body[:600]},
                )
            ) from exc
        except urllib.error.URLError as exc:
            raise AlphaVantageApiError(
                AlphaVantageErrorContext(
                    function=function,
                    message=f"Network error contacting Alpha Vantage: {exc.reason}",
                    retryable=True,
                )
            ) from exc


def _clean_params(params: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _format_param(value)
        for key, value in params.items()
        if value is not None and value != ""
    }


def _format_param(value: Any) -> Any:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, list | tuple | set):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    return value


def _sanitize_params(params: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if key.lower() != "apikey"}


def _required_text(value: str, field_name: str) -> str:
    resolved = str(value or "").strip()
    if not resolved:
        raise ValueError(f"{field_name} is required.")
    return resolved


def _join_symbols(value: str | Iterable[str]) -> str:
    if isinstance(value, str):
        return _required_text(value, "symbols")
    joined = ",".join(str(item).strip() for item in value if str(item).strip())
    return _required_text(joined, "symbols")


def _join_optional(value: str | Iterable[str] | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    joined = ",".join(str(item).strip() for item in value if str(item).strip())
    return joined or None


def _parse_json(raw: str, *, function: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AlphaVantageApiError(
            AlphaVantageErrorContext(
                function=function,
                message="Alpha Vantage returned invalid JSON.",
                retryable=False,
                details={"body": raw[:600]},
            )
        ) from exc
    if not isinstance(data, dict):
        raise AlphaVantageApiError(
            AlphaVantageErrorContext(
                function=function,
                message="Alpha Vantage returned a non-object JSON payload.",
                retryable=False,
                details={"payload_type": type(data).__name__},
            )
        )
    return data


def _parse_csv(raw: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(raw.splitlines())
    return [dict(row) for row in reader]


def _raise_for_api_message(data: dict[str, Any], *, function: str) -> None:
    for key in JSON_API_MESSAGES:
        message = data.get(key)
        if not message:
            continue
        retryable = key in {"Note", "Information"}
        raise AlphaVantageApiError(
            AlphaVantageErrorContext(
                function=function,
                message=str(message),
                retryable=retryable,
                details={"response_key": key},
            )
        )
