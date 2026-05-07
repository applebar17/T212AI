"""Deterministic instrument monitor scheduler adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from t212ai.capabilities import MarketDataService

from .models import ScheduledProcess, ScheduledRunStatus
from .worker import ScheduledAdapterResult


PRICE_TRIGGER_TYPES = {"below_price", "above_price"}
PERCENT_TRIGGER_TYPES = {"percent_change_below", "percent_change_above"}
HISTORY_TRIGGER_TYPES = {"period_low_breakdown", "period_high_breakout"}
SUPPORTED_TRIGGER_TYPES = PRICE_TRIGGER_TYPES | PERCENT_TRIGGER_TYPES | HISTORY_TRIGGER_TYPES


@dataclass(slots=True)
class InstrumentMonitorAdapter:
    """Evaluates instrument monitor triggers using the configured market-data service."""

    market_data_service: MarketDataService | None

    def run(self, process: ScheduledProcess) -> ScheduledAdapterResult:
        try:
            trigger = _parse_trigger(process.trigger)
        except ValueError as exc:
            return _failed_invalid_spec(str(exc))
        if self.market_data_service is None:
            return _skipped(
                code="market_data_unavailable",
                message="Instrument monitor requires a configured market-data service.",
                metadata=trigger.base_metadata,
            )
        try:
            quote_result = self.market_data_service.get_quote_snapshot([trigger.symbol])
        except Exception as exc:
            return _skipped(
                code="market_data_error",
                message=f"Market-data quote lookup failed: {exc}.",
                metadata={
                    **trigger.base_metadata,
                    "errorType": exc.__class__.__name__,
                },
            )
        provider = _provider_name(quote_result.meta, self.market_data_service)
        quote_error = quote_result.errors.get(trigger.symbol)
        if quote_error:
            return _skipped(
                code="quote_unavailable",
                message=f"Market-data provider did not return a usable quote for {trigger.symbol}.",
                metadata={
                    **trigger.base_metadata,
                    "provider": provider,
                    "quoteError": quote_error,
                },
            )
        quote = quote_result.quotes.get(trigger.symbol)
        if quote is None:
            return _skipped(
                code="missing_quote",
                message=f"Market-data provider did not return a quote for {trigger.symbol}.",
                metadata={**trigger.base_metadata, "provider": provider},
            )
        price = _number(quote.get("price"))
        if price is None:
            return _skipped(
                code="missing_price",
                message=f"Quote for {trigger.symbol} does not include a numeric price.",
                metadata={
                    **trigger.base_metadata,
                    "provider": provider,
                    "quote": quote,
                },
            )
        if trigger.trigger_type in PRICE_TRIGGER_TYPES:
            return self._evaluate_price_trigger(process, trigger, quote, price, provider)
        if trigger.trigger_type in PERCENT_TRIGGER_TYPES:
            return self._evaluate_percent_trigger(process, trigger, quote, price, provider)
        return self._evaluate_history_trigger(process, trigger, quote, price, provider)

    def _evaluate_price_trigger(
        self,
        process: ScheduledProcess,
        trigger: "_InstrumentTrigger",
        quote: dict[str, Any],
        price: float,
        provider: str,
    ) -> ScheduledAdapterResult:
        assert trigger.threshold_value is not None
        matched = (
            price <= trigger.threshold_value
            if trigger.trigger_type == "below_price"
            else price >= trigger.threshold_value
        )
        comparison = "<=" if trigger.trigger_type == "below_price" else ">="
        evidence = _base_evidence(
            trigger=trigger,
            quote=quote,
            price=price,
            provider=provider,
            matched=matched,
            threshold_value=trigger.threshold_value,
        )
        condition = f"{trigger.symbol} price {price:g} {comparison} {trigger.threshold_value:g}"
        return _completed_result(
            process=process,
            matched=matched,
            condition=condition,
            evidence=evidence,
        )

    def _evaluate_percent_trigger(
        self,
        process: ScheduledProcess,
        trigger: "_InstrumentTrigger",
        quote: dict[str, Any],
        price: float,
        provider: str,
    ) -> ScheduledAdapterResult:
        assert trigger.threshold_value is not None
        change_pct = _number(quote.get("change_pct"))
        if change_pct is None:
            return _skipped(
                code="missing_change_pct",
                message=f"Quote for {trigger.symbol} does not include a numeric change_pct.",
                metadata={
                    **trigger.base_metadata,
                    "provider": provider,
                    "observedPrice": price,
                    "quote": quote,
                },
            )
        matched = (
            change_pct <= trigger.threshold_value
            if trigger.trigger_type == "percent_change_below"
            else change_pct >= trigger.threshold_value
        )
        comparison = "<=" if trigger.trigger_type == "percent_change_below" else ">="
        evidence = _base_evidence(
            trigger=trigger,
            quote=quote,
            price=price,
            provider=provider,
            matched=matched,
            threshold_value=trigger.threshold_value,
        )
        evidence["observedChangePct"] = change_pct
        condition = (
            f"{trigger.symbol} change {change_pct:g}% {comparison} "
            f"{trigger.threshold_value:g}%"
        )
        return _completed_result(
            process=process,
            matched=matched,
            condition=condition,
            evidence=evidence,
        )

    def _evaluate_history_trigger(
        self,
        process: ScheduledProcess,
        trigger: "_InstrumentTrigger",
        quote: dict[str, Any],
        price: float,
        provider: str,
    ) -> ScheduledAdapterResult:
        try:
            history = self.market_data_service.get_price_history(
                [trigger.symbol],
                period=trigger.lookback_period,
                interval=trigger.lookback_interval,
                auto_adjust=trigger.auto_adjust,
            )
        except Exception as exc:
            return _skipped(
                code="market_data_history_error",
                message=f"Market-data history lookup failed: {exc}.",
                metadata={
                    **trigger.base_metadata,
                    "provider": provider,
                    "errorType": exc.__class__.__name__,
                    "lookbackPeriod": trigger.lookback_period,
                    "lookbackInterval": trigger.lookback_interval,
                },
            )
        history_error = history.errors.get(trigger.symbol)
        if history_error:
            return _skipped(
                code="history_unavailable",
                message=f"Market-data provider did not return usable history for {trigger.symbol}.",
                metadata={
                    **trigger.base_metadata,
                    "provider": provider,
                    "historyError": history_error,
                    "lookbackPeriod": trigger.lookback_period,
                    "lookbackInterval": trigger.lookback_interval,
                },
            )
        points = history.series.get(trigger.symbol) or []
        if not points:
            return _skipped(
                code="history_unavailable",
                message=f"Market-data provider returned no history points for {trigger.symbol}.",
                metadata={
                    **trigger.base_metadata,
                    "provider": provider,
                    "lookbackPeriod": trigger.lookback_period,
                    "lookbackInterval": trigger.lookback_interval,
                },
            )
        field = "low" if trigger.trigger_type == "period_low_breakdown" else "high"
        values = [_number(point.get(field)) for point in points]
        numeric_values = [value for value in values if value is not None]
        if not numeric_values:
            return _skipped(
                code="history_reference_unavailable",
                message=f"History for {trigger.symbol} does not include numeric {field} values.",
                metadata={
                    **trigger.base_metadata,
                    "provider": provider,
                    "lookbackPeriod": trigger.lookback_period,
                    "lookbackInterval": trigger.lookback_interval,
                },
            )
        if trigger.trigger_type == "period_low_breakdown":
            reference = min(numeric_values)
            matched = price <= reference
            comparison = "<="
            reference_label = "period low"
            reference_key = "referenceLow"
        else:
            reference = max(numeric_values)
            matched = price >= reference
            comparison = ">="
            reference_label = "period high"
            reference_key = "referenceHigh"
        evidence = _base_evidence(
            trigger=trigger,
            quote=quote,
            price=price,
            provider=provider,
            matched=matched,
        )
        evidence.update(
            {
                "lookbackPeriod": trigger.lookback_period,
                "lookbackInterval": trigger.lookback_interval,
                "autoAdjust": trigger.auto_adjust,
                reference_key: reference,
                "historyPoints": len(points),
            }
        )
        condition = f"{trigger.symbol} price {price:g} {comparison} {reference_label} {reference:g}"
        return _completed_result(
            process=process,
            matched=matched,
            condition=condition,
            evidence=evidence,
        )


@dataclass(frozen=True, slots=True)
class _InstrumentTrigger:
    trigger_type: str
    symbol: str
    threshold_value: float | None = None
    lookback_period: str = "1mo"
    lookback_interval: str = "1d"
    auto_adjust: bool = False

    @property
    def base_metadata(self) -> dict[str, object]:
        metadata: dict[str, object] = {
            "symbol": self.symbol,
            "triggerType": self.trigger_type,
        }
        if self.threshold_value is not None:
            metadata["thresholdValue"] = self.threshold_value
        if self.trigger_type in HISTORY_TRIGGER_TYPES:
            metadata["lookbackPeriod"] = self.lookback_period
            metadata["lookbackInterval"] = self.lookback_interval
            metadata["autoAdjust"] = self.auto_adjust
        return metadata


def _parse_trigger(raw_trigger: dict[str, Any]) -> _InstrumentTrigger:
    if not isinstance(raw_trigger, dict):
        raise ValueError("instrument_monitor trigger must be an object.")
    trigger_type = str(raw_trigger.get("type") or "").strip().lower()
    if trigger_type not in SUPPORTED_TRIGGER_TYPES:
        allowed = ", ".join(sorted(SUPPORTED_TRIGGER_TYPES))
        raise ValueError(f"Unsupported instrument_monitor trigger type '{trigger_type}'. Allowed: {allowed}.")
    symbol = str(raw_trigger.get("symbol") or "").strip().upper()
    if not symbol:
        raise ValueError("instrument_monitor trigger requires symbol.")
    threshold_value = None
    if trigger_type in PRICE_TRIGGER_TYPES or trigger_type in PERCENT_TRIGGER_TYPES:
        threshold_value = _number(raw_trigger.get("value"))
        if threshold_value is None:
            raise ValueError("instrument_monitor price and percent triggers require numeric value.")
    lookback_period = str(raw_trigger.get("lookbackPeriod") or "1mo").strip() or "1mo"
    lookback_interval = str(raw_trigger.get("lookbackInterval") or "1d").strip() or "1d"
    return _InstrumentTrigger(
        trigger_type=trigger_type,
        symbol=symbol,
        threshold_value=threshold_value,
        lookback_period=lookback_period,
        lookback_interval=lookback_interval,
        auto_adjust=_bool(raw_trigger.get("autoAdjust", False)),
    )


def _completed_result(
    *,
    process: ScheduledProcess,
    matched: bool,
    condition: str,
    evidence: dict[str, object],
) -> ScheduledAdapterResult:
    output_summary = (
        f"Instrument monitor matched: {condition}."
        if matched
        else f"Instrument monitor checked: no match for {condition}."
    )
    notification_message = None
    if matched and _notification_enabled(process.notification):
        notification_message = _notification_text(
            title=process.title,
            condition=condition,
            evidence=evidence,
        )
    return ScheduledAdapterResult(
        status=ScheduledRunStatus.COMPLETED,
        matched=matched,
        output_summary=output_summary,
        code="trigger_matched" if matched else "no_match",
        message=output_summary,
        metadata=evidence,
        notification_message=notification_message,
        notification_metadata=evidence if matched else {},
    )


def _skipped(
    *,
    code: str,
    message: str,
    metadata: dict[str, object] | None = None,
) -> ScheduledAdapterResult:
    return ScheduledAdapterResult(
        status=ScheduledRunStatus.SKIPPED,
        matched=False,
        output_summary=message,
        code=code,
        message=message,
        metadata=dict(metadata or {}),
    )


def _failed_invalid_spec(message: str) -> ScheduledAdapterResult:
    return ScheduledAdapterResult(
        status=ScheduledRunStatus.FAILED,
        matched=False,
        output_summary=message,
        code="invalid_instrument_monitor_spec",
        message=message,
        metadata={"errorCode": "invalid_instrument_monitor_spec"},
    )


def _base_evidence(
    *,
    trigger: _InstrumentTrigger,
    quote: dict[str, Any],
    price: float,
    provider: str,
    matched: bool,
    threshold_value: float | None = None,
) -> dict[str, object]:
    evidence: dict[str, object] = {
        "symbol": trigger.symbol,
        "triggerType": trigger.trigger_type,
        "observedPrice": price,
        "matched": matched,
        "provider": provider,
        "quote": quote,
    }
    change_pct = _number(quote.get("change_pct"))
    if change_pct is not None:
        evidence["observedChangePct"] = change_pct
    if threshold_value is not None:
        evidence["thresholdValue"] = threshold_value
    return evidence


def _notification_text(
    *,
    title: str,
    condition: str,
    evidence: dict[str, object],
) -> str:
    parts = [
        f"Scheduler alert: {title}",
        condition,
        f"Provider: {evidence.get('provider')}",
    ]
    quote = evidence.get("quote")
    if isinstance(quote, dict):
        currency = quote.get("currency")
        market_state = quote.get("market_state")
        if currency:
            parts.append(f"Currency: {currency}")
        if market_state:
            parts.append(f"Market state: {market_state}")
    return ". ".join(str(part).rstrip(".") for part in parts if part) + "."


def _notification_enabled(notification: dict[str, Any]) -> bool:
    return bool(notification.get("enabled", True))


def _provider_name(meta: dict[str, Any], service: MarketDataService) -> str:
    provider = meta.get("provider") if isinstance(meta, dict) else None
    if provider:
        return str(provider)
    return str(getattr(service, "provider_name", None) or "market_data")


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    raw = str(value or "").strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off", ""}:
        return False
    return bool(value)
