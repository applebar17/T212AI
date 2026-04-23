"""Yahoo Finance best-effort convenience client."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .models import (
    YahooFinanceError,
    YahooOptionsResult,
    YahooPriceHistoryResult,
    YahooQuoteSnapshotResult,
    YahooQuoteSummaryResult,
    YahooSearchResult,
)


YAHOO_CHART_BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
YAHOO_SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
YAHOO_OPTIONS_BASE_URL = "https://query2.finance.yahoo.com/v7/finance/options"
YAHOO_QUOTE_SUMMARY_BASE_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary"
YAHOO_USER_AGENT = "t212ai-yahoo/1.0"

ANALYST_MODULES = [
    "financialData",
    "recommendationTrend",
    "upgradeDowngradeHistory",
    "earningsTrend",
]


class YahooFinanceClient:
    def __init__(
        self,
        *,
        chart_base_url: str = YAHOO_CHART_BASE_URL,
        quote_url: str = YAHOO_QUOTE_URL,
        search_url: str = YAHOO_SEARCH_URL,
        options_base_url: str = YAHOO_OPTIONS_BASE_URL,
        quote_summary_base_url: str = YAHOO_QUOTE_SUMMARY_BASE_URL,
        user_agent: str = YAHOO_USER_AGENT,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.chart_base_url = chart_base_url.rstrip("/")
        self.quote_url = quote_url
        self.search_url = search_url
        self.options_base_url = options_base_url.rstrip("/")
        self.quote_summary_base_url = quote_summary_base_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout_seconds = float(timeout_seconds)

    def get_price_history(
        self,
        symbols: list[str],
        *,
        period: str = "1mo",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
        auto_adjust: bool = False,
    ) -> YahooPriceHistoryResult:
        series: dict[str, list[dict[str, Any]]] = {}
        errors: dict[str, dict[str, Any]] = {}
        for symbol in _clean_symbols(symbols):
            try:
                series[symbol] = self._fetch_symbol_history(
                    symbol,
                    period=period,
                    interval=interval,
                    start=start,
                    end=end,
                    auto_adjust=auto_adjust,
                )
            except YahooFinanceError as exc:
                errors[symbol] = _error_payload(exc)
        return YahooPriceHistoryResult(
            series=series,
            errors=errors,
            meta={
                "provider": "yahoo_finance_unofficial",
                "period": period,
                "interval": interval,
                "start": start,
                "end": end,
                "auto_adjust": bool(auto_adjust),
            },
        )

    def get_quote_snapshot(self, symbols: list[str]) -> YahooQuoteSnapshotResult:
        cleaned = _clean_symbols(symbols)
        if not cleaned:
            raise ValueError("At least one symbol is required.")
        payload = self._read_json_url(
            self._build_url(self.quote_url, {"symbols": ",".join(cleaned)}),
            operation="quote",
        )
        quote_response = payload.get("quoteResponse") or {}
        result = quote_response.get("result") or []
        error = quote_response.get("error")
        if error:
            raise YahooFinanceError(
                f"Yahoo Finance quote endpoint returned an error: {error}",
                code="provider_error",
                details={"provider_error": error},
                retryable=False,
            )
        quotes = {
            str(item.get("symbol") or "").upper(): item
            for item in result
            if item.get("symbol")
        }
        missing = {
            symbol: {
                "code": "missing_quote",
                "message": "Yahoo Finance did not return this symbol.",
                "retryable": False,
            }
            for symbol in cleaned
            if symbol.upper() not in quotes
        }
        return YahooQuoteSnapshotResult(
            quotes=quotes,
            errors=missing,
            meta={"provider": "yahoo_finance_unofficial", "symbols": cleaned},
        )

    def search_symbols(
        self,
        query: str,
        *,
        quotes_count: int = 8,
        news_count: int = 0,
    ) -> YahooSearchResult:
        resolved_query = _required_text(query, "query")
        payload = self._read_json_url(
            self._build_url(
                self.search_url,
                {
                    "q": resolved_query,
                    "quotesCount": max(0, int(quotes_count)),
                    "newsCount": max(0, int(news_count)),
                },
            ),
            operation="search",
        )
        return YahooSearchResult(
            query=resolved_query,
            quotes=payload.get("quotes") or [],
            news=payload.get("news") or [],
            meta={"provider": "yahoo_finance_unofficial"},
        )

    def get_quote_summary(
        self,
        symbol: str,
        *,
        modules: list[str] | tuple[str, ...],
    ) -> YahooQuoteSummaryResult:
        resolved_symbol = _required_text(symbol, "symbol").upper()
        cleaned_modules = [str(module).strip() for module in modules if str(module).strip()]
        if not cleaned_modules:
            raise ValueError("At least one quote-summary module is required.")
        payload = self._read_json_url(
            self._build_url(
                f"{self.quote_summary_base_url}/{urllib.parse.quote(resolved_symbol)}",
                {"modules": ",".join(cleaned_modules)},
            ),
            operation="quote_summary",
        )
        summary = payload.get("quoteSummary") or {}
        error = summary.get("error")
        if error:
            raise YahooFinanceError(
                f"Yahoo Finance quoteSummary returned an error: {error}",
                code="provider_error",
                details={"provider_error": error, "symbol": resolved_symbol},
                retryable=False,
            )
        result = (summary.get("result") or [{}])[0] or {}
        return YahooQuoteSummaryResult(
            symbol=resolved_symbol,
            modules=cleaned_modules,
            data=result,
            meta={"provider": "yahoo_finance_unofficial"},
        )

    def get_analyst_snapshot(self, symbol: str) -> YahooQuoteSummaryResult:
        return self.get_quote_summary(symbol, modules=ANALYST_MODULES)

    def get_options_chain(
        self,
        symbol: str,
        *,
        expiration: int | None = None,
    ) -> YahooOptionsResult:
        resolved_symbol = _required_text(symbol, "symbol").upper()
        params = {"date": int(expiration)} if expiration is not None else {}
        payload = self._read_json_url(
            self._build_url(
                f"{self.options_base_url}/{urllib.parse.quote(resolved_symbol)}",
                params,
            ),
            operation="options",
        )
        option_chain = payload.get("optionChain") or {}
        error = option_chain.get("error")
        if error:
            raise YahooFinanceError(
                f"Yahoo Finance options endpoint returned an error: {error}",
                code="provider_error",
                details={"provider_error": error, "symbol": resolved_symbol},
                retryable=False,
            )
        result = (option_chain.get("result") or [{}])[0] or {}
        return YahooOptionsResult(
            symbol=resolved_symbol,
            expiration_dates=result.get("expirationDates") or [],
            options=result.get("options") or [],
            quote=result.get("quote"),
            meta={
                "provider": "yahoo_finance_unofficial",
                "requested_expiration": expiration,
            },
        )

    def _fetch_symbol_history(
        self,
        symbol: str,
        *,
        period: str,
        interval: str,
        start: str | None,
        end: str | None,
        auto_adjust: bool,
    ) -> list[dict[str, Any]]:
        params = {
            "interval": interval or "1d",
            "includeAdjustedClose": "true",
            "events": "div,splits",
        }
        if start or end:
            params["period1"] = str(_to_unix_timestamp(start) if start else 0)
            params["period2"] = str(
                _to_unix_timestamp(end, end_of_day=True)
                if end
                else int(datetime.now(tz=timezone.utc).timestamp())
            )
        else:
            params["range"] = period or "1mo"

        payload = self._read_json_url(
            self._build_url(
                f"{self.chart_base_url}/{urllib.parse.quote(symbol)}",
                params,
            ),
            operation="chart",
        )
        result = ((payload.get("chart") or {}).get("result") or [None])[0]
        error = (payload.get("chart") or {}).get("error")
        if error:
            raise YahooFinanceError(
                f"Yahoo Finance chart endpoint returned an error: {error}",
                code="provider_error",
                details={"symbol": symbol, "provider_error": error},
                retryable=False,
            )
        if not result:
            return []

        timestamps = result.get("timestamp") or []
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        adjclose_block = ((result.get("indicators") or {}).get("adjclose") or [{}])[0]
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []
        adjcloses = adjclose_block.get("adjclose") or []

        points: list[dict[str, Any]] = []
        for idx, ts in enumerate(timestamps):
            close = _to_float(_safe_get(closes, idx))
            adj_close = _to_float(_safe_get(adjcloses, idx))
            effective_close = adj_close if auto_adjust and adj_close is not None else close
            points.append(
                {
                    "timestamp": _timestamp_to_iso(ts),
                    "open": _to_float(_safe_get(opens, idx)),
                    "high": _to_float(_safe_get(highs, idx)),
                    "low": _to_float(_safe_get(lows, idx)),
                    "close": effective_close,
                    "adj_close": adj_close,
                    "volume": _to_float(_safe_get(volumes, idx)),
                }
            )
        return points

    def _build_url(self, base_url: str, params: dict[str, Any]) -> str:
        clean = {key: value for key, value in params.items() if value is not None}
        if not clean:
            return base_url
        return f"{base_url}?{urllib.parse.urlencode(clean)}"

    def _read_json_url(self, url: str, *, operation: str) -> dict[str, Any]:
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raw_body = exc.read().decode("utf-8", errors="replace")
            raise YahooFinanceError(
                f"Yahoo Finance {operation} request failed with HTTP {exc.code}.",
                code="http_error",
                details={"status_code": exc.code, "body": raw_body[:600], "url": url},
                retryable=exc.code >= 500 or exc.code == 429,
            ) from exc
        except urllib.error.URLError as exc:
            raise YahooFinanceError(
                f"Network error contacting Yahoo Finance for {operation}: {exc.reason}",
                code="request_failed",
                details={"url": url},
                retryable=True,
            ) from exc

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise YahooFinanceError(
                f"Yahoo Finance {operation} returned invalid JSON.",
                code="invalid_json",
                details={"body": raw[:600], "url": url},
                retryable=False,
            ) from exc
        if not isinstance(payload, dict):
            raise YahooFinanceError(
                f"Yahoo Finance {operation} returned a non-object payload.",
                code="invalid_payload",
                details={"payload_type": type(payload).__name__, "url": url},
                retryable=False,
            )
        return payload


def _clean_symbols(symbols: list[str] | tuple[str, ...]) -> list[str]:
    return [str(symbol).strip().upper() for symbol in symbols or [] if str(symbol).strip()]


def _required_text(value: str, field_name: str) -> str:
    resolved = str(value or "").strip()
    if not resolved:
        raise ValueError(f"{field_name} is required.")
    return resolved


def _safe_get(values: list[Any], index: int) -> Any:
    try:
        return values[index]
    except Exception:
        return None


def _timestamp_to_iso(value: Any) -> str | None:
    numeric = _to_float(value)
    if numeric is None:
        return None
    return datetime.fromtimestamp(int(numeric), tz=timezone.utc).isoformat().replace(
        "+00:00",
        "Z",
    )


def _to_unix_timestamp(date_value: str, *, end_of_day: bool = False) -> int:
    suffix = "T23:59:59+00:00" if end_of_day else "T00:00:00+00:00"
    return int(datetime.fromisoformat(f"{date_value}{suffix}").timestamp())


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if value != value:
            return None
    except Exception:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _error_payload(exc: YahooFinanceError) -> dict[str, Any]:
    return {
        "code": exc.code,
        "message": str(exc),
        "details": exc.details,
        "retryable": exc.retryable,
    }
