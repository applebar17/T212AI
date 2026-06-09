"""Thin capability adapters over existing provider implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from t212ai.alpaca.market_data import AlpacaMarketDataClient
from t212ai.data_sources.alpha_vantage import (
    AlphaVantageClient,
    AlphaVantageToolRuntime,
    alpha_vantage_most_actively_traded,
)
from t212ai.data_sources.eodhd import EodhdClient
from t212ai.data_sources.sec_edgar import EdgarInsiderManager
from t212ai.data_sources.yahoo import (
    YahooFinanceClient,
)
from t212ai.data_sources.yahoo.analytics import PriceSeriesAnalytics
from t212ai.genai.models import ToolResult
from t212ai.genai.tools.scrape_article import scrape_article, scrape_page
from t212ai.genai.tools.search_registry import SearchResultRegistry
from t212ai.genai.tools.searxng import searxng_search

from .market_data_models import (
    MarketPriceHistoryResult,
    MarketQuoteSnapshotResult,
    MarketSymbolSearchResult,
)
from .symbol_reference_models import (
    SymbolIdentifierMappingResult,
    SymbolReferenceSearchResult,
)


@dataclass(slots=True)
class YahooMarketDataService:
    client: YahooFinanceClient
    provider_name: str = "yahoo"

    def get_quote_snapshot(self, symbols: list[str]) -> MarketQuoteSnapshotResult:
        result = self.client.get_quote_snapshot(symbols)
        return MarketQuoteSnapshotResult(
            quotes={
                symbol: _normalize_yahoo_quote(symbol, quote)
                for symbol, quote in result.quotes.items()
            },
            errors=dict(result.errors),
            meta=_provider_meta(result.meta, provider=self.provider_name),
        )

    def get_price_history(
        self,
        symbols: list[str],
        *,
        period: str = "1mo",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
        auto_adjust: bool = False,
    ) -> MarketPriceHistoryResult:
        result = self.client.get_price_history(
            symbols,
            period=period,
            interval=interval,
            start=start,
            end=end,
            auto_adjust=auto_adjust,
        )
        return MarketPriceHistoryResult(
            series=dict(result.series),
            errors=dict(result.errors),
            meta=_provider_meta(result.meta, provider=self.provider_name),
        )

    def get_market_snapshot(
        self,
        symbols: list[str] | tuple[str, ...],
        *,
        period: str = "1mo",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
        auto_adjust: bool = False,
    ) -> ToolResult:
        quotes = self.get_quote_snapshot(list(symbols))
        history = self.get_price_history(
            list(symbols),
            period=period,
            interval=interval,
            start=start,
            end=end,
            auto_adjust=auto_adjust,
        )
        summary = PriceSeriesAnalytics.summarize_series(history.series)
        return ToolResult(
            status="ok",
            output=(
                f"Yahoo market snapshot returned quote and price-summary context for "
                f"{len(set(quotes.quotes) | set(summary))} symbol(s)."
            ),
            data={
                "quotes": quotes.quotes,
                "quote_errors": quotes.errors,
                "price_summary": summary,
                "price_errors": history.errors,
                "meta": {
                    "quote": quotes.meta,
                    "price": history.meta,
                },
            },
        )

    def get_volume_monitor(
        self,
        symbols: list[str] | tuple[str, ...],
        *,
        period: str = "1mo",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
        auto_adjust: bool = False,
    ) -> ToolResult:
        quotes = self.get_quote_snapshot(list(symbols))
        history = self.get_price_history(
            list(symbols),
            period=period,
            interval=interval,
            start=start,
            end=end,
            auto_adjust=auto_adjust,
        )
        summary = PriceSeriesAnalytics.summarize_series(history.series)
        monitor = _build_volume_monitor_payload(quotes.quotes, summary)
        return ToolResult(
            status="ok",
            output=(
                f"Yahoo volume monitor returned relative-volume context for "
                f"{len(monitor)} symbol(s)."
            ),
            data={
                "monitor": monitor,
                "quotes": quotes.quotes,
                "quote_errors": quotes.errors,
                "price_summary": summary,
                "price_errors": history.errors,
                "meta": {
                    "quote": quotes.meta,
                    "price": history.meta,
                },
            },
        )

    def search_symbols(
        self,
        query: str,
        *,
        quotes_count: int = 8,
        news_count: int = 0,
    ) -> MarketSymbolSearchResult:
        result = self.client.search_symbols(
            query,
            quotes_count=quotes_count,
            news_count=news_count,
        )
        return MarketSymbolSearchResult(
            query=result.query,
            candidates=[_normalize_yahoo_candidate(candidate) for candidate in result.quotes],
            meta=_provider_meta(result.meta, provider=self.provider_name),
        )

    def get_chart_context(
        self,
        symbols: list[str] | tuple[str, ...],
        *,
        period: str = "1mo",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
        auto_adjust: bool = False,
    ) -> ToolResult:
        history = self.get_price_history(
            list(symbols),
            period=period,
            interval=interval,
            start=start,
            end=end,
            auto_adjust=auto_adjust,
        )
        summary = PriceSeriesAnalytics.summarize_series(history.series)
        chart_refs = _build_chart_refs(history.series, history.meta)
        placement_guidance = (
            "A price chart can be rendered in the UI by rendering the exact "
            "standalone placeholder token returned in chart_refs."
        )
        total_points = sum(len(points) for points in history.series.values())
        return ToolResult(
            status="ok",
            output=(
                f"Yahoo chart context returned analytics and chart references for "
                f"{len(summary)} symbol(s)."
            ),
            data={
                "summary": summary,
                "series": history.series,
                "chart_refs": chart_refs,
                "placement_guidance": placement_guidance,
                "errors": history.errors,
                "meta": history.meta,
                "total_points": total_points,
            },
        )


@dataclass(slots=True)
class AlpacaMarketDataService:
    client: AlpacaMarketDataClient
    provider_name: str = "alpaca"

    def get_quote_snapshot(self, symbols: list[str]) -> MarketQuoteSnapshotResult:
        return self.client.get_quote_snapshot(symbols)

    def get_price_history(
        self,
        symbols: list[str],
        *,
        period: str = "1mo",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
        auto_adjust: bool = False,
    ) -> MarketPriceHistoryResult:
        return self.client.get_price_history(
            symbols,
            period=period,
            interval=interval,
            start=start,
            end=end,
            auto_adjust=auto_adjust,
        )

    def search_symbols(
        self,
        query: str,
        *,
        quotes_count: int = 8,
        news_count: int = 0,
    ) -> MarketSymbolSearchResult:
        return self.client.search_symbols(
            query,
            quotes_count=quotes_count,
            news_count=news_count,
        )

    def get_market_snapshot(
        self,
        symbols: list[str] | tuple[str, ...],
        *,
        period: str = "1mo",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
        auto_adjust: bool = False,
    ) -> ToolResult:
        quotes = self.get_quote_snapshot(list(symbols))
        history = self.get_price_history(
            list(symbols),
            period=period,
            interval=interval,
            start=start,
            end=end,
            auto_adjust=auto_adjust,
        )
        summary = PriceSeriesAnalytics.summarize_series(history.series)
        return ToolResult(
            status="ok",
            output=(
                f"Alpaca market snapshot returned quote and price-summary context for "
                f"{len(set(quotes.quotes) | set(summary))} symbol(s)."
            ),
            data={
                "quotes": quotes.quotes,
                "quote_errors": quotes.errors,
                "price_summary": summary,
                "price_errors": history.errors,
                "meta": {
                    "quote": quotes.meta,
                    "price": history.meta,
                },
            },
        )

    def get_volume_monitor(
        self,
        symbols: list[str] | tuple[str, ...],
        *,
        period: str = "1mo",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
        auto_adjust: bool = False,
    ) -> ToolResult:
        quotes = self.get_quote_snapshot(list(symbols))
        history = self.get_price_history(
            list(symbols),
            period=period,
            interval=interval,
            start=start,
            end=end,
            auto_adjust=auto_adjust,
        )
        summary = PriceSeriesAnalytics.summarize_series(history.series)
        monitor = _build_volume_monitor_payload(quotes.quotes, summary)
        return ToolResult(
            status="ok",
            output=(
                f"Alpaca volume monitor returned relative-volume context for "
                f"{len(monitor)} symbol(s)."
            ),
            data={
                "monitor": monitor,
                "quotes": quotes.quotes,
                "quote_errors": quotes.errors,
                "price_summary": summary,
                "price_errors": history.errors,
                "meta": {
                    "quote": quotes.meta,
                    "price": history.meta,
                },
            },
        )

    def get_chart_context(
        self,
        symbols: list[str] | tuple[str, ...],
        *,
        period: str = "1mo",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
        auto_adjust: bool = False,
    ) -> ToolResult:
        history = self.get_price_history(
            list(symbols),
            period=period,
            interval=interval,
            start=start,
            end=end,
            auto_adjust=auto_adjust,
        )
        summary = PriceSeriesAnalytics.summarize_series(history.series)
        chart_refs = _build_chart_refs(history.series, history.meta)
        placement_guidance = (
            "A price chart can be rendered in the UI by rendering the exact "
            "standalone placeholder token returned in chart_refs."
        )
        total_points = sum(len(points) for points in history.series.values())
        return ToolResult(
            status="ok",
            output=(
                f"Alpaca chart context returned analytics and chart references for "
                f"{len(summary)} symbol(s)."
            ),
            data={
                "summary": summary,
                "series": history.series,
                "chart_refs": chart_refs,
                "placement_guidance": placement_guidance,
                "errors": history.errors,
                "meta": history.meta,
                "total_points": total_points,
            },
        )


@dataclass(slots=True)
class AlphaVantageMarketIntelligenceService:
    client: AlphaVantageClient

    def get_most_actively_traded(
        self,
        *,
        entitlement: str | None = None,
        limit: int = 20,
    ) -> ToolResult:
        return alpha_vantage_most_actively_traded(
            entitlement=entitlement,
            limit=limit,
            runtime=AlphaVantageToolRuntime(client=self.client),
        )


@dataclass(slots=True)
class EodhdSymbolReferenceService:
    client: EodhdClient
    provider_name: str = "eodhd"

    def search(
        self,
        query: str,
        *,
        limit: int = 15,
        asset_type: str = "all",
        exchange: str | None = None,
        bonds_only: bool = False,
    ) -> SymbolReferenceSearchResult:
        result = self.client.search(
            query,
            limit=limit,
            asset_type=asset_type,
            exchange=exchange,
            bonds_only=bonds_only,
        )
        return SymbolReferenceSearchResult(
            query=result.query,
            candidates=[candidate.to_dict() for candidate in result.candidates],
            meta={
                "provider": self.provider_name,
                "request_params": result.request_params,
                "endpoint": result.endpoint,
                "authority": "reference_data_only",
            },
        )

    def map_identifiers(
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
    ) -> SymbolIdentifierMappingResult:
        result = self.client.id_mapping(
            symbol=symbol,
            exchange=exchange,
            isin=isin,
            figi=figi,
            lei=lei,
            cusip=cusip,
            cik=cik,
            limit=limit,
            offset=offset,
        )
        return SymbolIdentifierMappingResult(
            records=[record.to_dict() for record in result.records],
            total=result.total,
            limit=result.limit,
            offset=result.offset,
            next_url=result.next_url,
            meta={
                "provider": self.provider_name,
                "request_params": result.request_params,
                "endpoint": result.endpoint,
                "authority": "reference_data_only",
            },
        )


@dataclass(slots=True)
class EdgarDisclosureService:
    manager: EdgarInsiderManager

    def get_recent_ownership_activity(
        self,
        symbol: str,
        *,
        since_days: int = 30,
        limit: int = 10,
    ):
        return self.manager.recent_ownership_activity(
            symbol,
            since_days=since_days,
            limit=limit,
        )

    def get_recent_major_stake_activity(
        self,
        symbol: str,
        *,
        since_days: int = 90,
        limit: int = 10,
    ):
        return self.manager.recent_major_stake_activity(
            symbol,
            since_days=since_days,
            limit=limit,
        )

    def get_company_disclosure_snapshot(
        self,
        symbol: str,
        *,
        since_days: int = 30,
        limit: int = 12,
    ):
        return self.manager.company_disclosure_snapshot(
            symbol,
            since_days=since_days,
            limit=limit,
        )


@dataclass(slots=True)
class SearxngSearchService:
    base_url: str

    def search(
        self,
        *,
        query: str,
        categories: str | None = None,
        language: str = "en",
        time_range: str | None = None,
        max_results: int = 8,
        scrape_results: bool = False,
        scrape_top_n: int = 3,
        scrape_timeout_seconds: float = 8.0,
        include_scraped_text: bool = False,
        include_scraped_images: bool = False,
        runtime: SearchResultRegistry | None = None,
        timeout_seconds: float = 20.0,
    ) -> ToolResult:
        return searxng_search(
            query=query,
            categories=categories,
            language=language,
            time_range=time_range,
            max_results=max_results,
            scrape_results=scrape_results,
            scrape_top_n=scrape_top_n,
            scrape_timeout_seconds=scrape_timeout_seconds,
            include_scraped_text=include_scraped_text,
            include_scraped_images=include_scraped_images,
            base_url=self.base_url,
            runtime=runtime,
            timeout_seconds=timeout_seconds,
        )

    def scrape_page(
        self,
        *,
        url: str | None = None,
        url_id: str | None = None,
        include_images: bool = True,
        max_images: int = 5,
        timeout_seconds: float = 20.0,
        runtime: SearchResultRegistry | None = None,
    ) -> ToolResult:
        return scrape_page(
            url=url,
            url_id=url_id,
            include_images=include_images,
            max_images=max_images,
            timeout_seconds=timeout_seconds,
            runtime=runtime,
        )

    def scrape_article(
        self,
        *,
        url: str | None = None,
        url_id: str | None = None,
        include_images: bool = True,
        max_images: int = 5,
        timeout_seconds: float = 20.0,
        runtime: SearchResultRegistry | None = None,
    ) -> ToolResult:
        return scrape_article(
            url=url,
            url_id=url_id,
            include_images=include_images,
            max_images=max_images,
            timeout_seconds=timeout_seconds,
            runtime=runtime,
        )


def _provider_meta(meta: dict[str, Any], *, provider: str) -> dict[str, Any]:
    payload = dict(meta)
    payload["provider"] = provider
    return payload


def _normalize_yahoo_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": str(candidate.get("symbol") or "").strip().upper(),
        "name": candidate.get("shortname") or candidate.get("longname"),
        "exchange": candidate.get("exchDisp") or candidate.get("exchange"),
        "type": candidate.get("quoteType"),
        "raw": candidate,
    }


def _normalize_yahoo_quote(symbol: str, quote: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "name": quote.get("shortName") or quote.get("longName"),
        "price": _round_number(_to_float(quote.get("regularMarketPrice"))),
        "change_pct": _round_number(_to_float(quote.get("regularMarketChangePercent"))),
        "volume": _round_number(_to_float(quote.get("regularMarketVolume"))),
        "market_cap": _round_number(_to_float(quote.get("marketCap"))),
        "currency": quote.get("currency"),
        "exchange": quote.get("fullExchangeName") or quote.get("exchange"),
        "market_state": quote.get("marketState"),
        "raw": quote,
    }


def _build_volume_monitor_payload(
    quotes: dict[str, dict[str, Any]],
    summary_payload: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    payload: dict[str, dict[str, Any]] = {}
    symbols = sorted(set(quotes.keys()) | set(summary_payload.keys()))
    for symbol in symbols:
        quote = quotes.get(symbol) or {}
        summary = summary_payload.get(symbol) or {}
        current_volume = _to_float(quote.get("volume"))
        average_volume = _to_float(summary.get("average_volume"))
        relative_volume = None
        volume_change_pct = None
        if current_volume is not None and average_volume not in {None, 0}:
            relative_volume = current_volume / average_volume
            volume_change_pct = ((current_volume - average_volume) / average_volume) * 100.0
        payload[symbol] = {
            "current_volume": _round_number(current_volume),
            "average_volume": _round_number(average_volume),
            "relative_volume": _round_number(relative_volume),
            "volume_change_pct": _round_number(volume_change_pct),
            "signal": _classify_relative_volume(relative_volume),
            "price_change_pct": _to_float(quote.get("change_pct")),
            "market_state": quote.get("market_state"),
        }
    return payload


def _classify_relative_volume(relative_volume: float | None) -> str:
    if relative_volume is None:
        return "insufficient_data"
    if relative_volume >= 3.0:
        return "anomalous"
    if relative_volume >= 1.5:
        return "elevated"
    if relative_volume <= 0.7:
        return "subdued"
    return "normal"


def _build_chart_refs(
    series_payload: dict[str, list[dict[str, Any]]],
    fetch_meta: dict[str, Any],
) -> dict[str, dict[str, str]]:
    refs: dict[str, dict[str, str]] = {}
    used_ids: set[str] = set()
    period = _normalize_render_slug(str(fetch_meta.get("period") or ""))
    interval = _normalize_render_slug(str(fetch_meta.get("interval") or ""))
    start = _normalize_render_slug(str(fetch_meta.get("start") or ""))
    end = _normalize_render_slug(str(fetch_meta.get("end") or ""))
    range_key = "-".join(part for part in [start, end] if part) or period or "range"
    for symbol, points in series_payload.items():
        if not points:
            continue
        ticker_key = _normalize_render_slug(symbol)
        stable_key = "-".join(
            part for part in [ticker_key, range_key, interval or "interval"] if part
        )
        attachment_id = _build_chart_attachment_id(stable_key)
        suffix = 2
        while attachment_id in used_ids:
            attachment_id = _build_chart_attachment_id(f"{stable_key}-{suffix}")
            suffix += 1
        used_ids.add(attachment_id)
        attachment_slug = attachment_id.removeprefix("chart-")
        refs[symbol] = {
            "chart_id": attachment_id,
            "stable_key": attachment_slug,
            "chart_title": f"{symbol} price history",
            "placeholder": _build_chart_placeholder(attachment_slug),
        }
    return refs


def _normalize_render_slug(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


def _build_chart_attachment_id(stable_key: str) -> str:
    slug = _normalize_render_slug(stable_key) or "chart"
    return f"chart-{slug}"


def _build_chart_placeholder(stable_key: str) -> str:
    return f"{{{{chart:{stable_key}}}}}"


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


def _round_number(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)
