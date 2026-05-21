"""Notional sizing helpers for broker order tools."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any

from t212ai.genai.models import ToolResult

from ..exceptions import BrokerInstrumentResolutionError
from ..models import PreparedBrokerOrder
from .errors import _instrument_resolution_tool_error, _tool_error, _tool_exception
from .formatting import _format_value
from .runtime import BrokerToolRuntime, _SizingContext


def _prepare_order_or_error(
    *,
    runtime: BrokerToolRuntime,
    order_type: str,
    side: str,
    ticker: str,
    quantity: str | int | float | None,
    notional_amount: str | int | float | None,
    notional_currency: str | None,
    limit_price: str | int | float | None,
    stop_price: str | int | float | None,
    time_in_force: str,
    extended_hours: bool,
) -> PreparedBrokerOrder | ToolResult:
    if runtime.broker_execution_service is None:
        return _tool_error(
            "Broker execution service is not configured.",
            code="broker_not_configured",
        )
    sizing_context: _SizingContext | None = None
    try:
        resolved_quantity: str | int | float | None = quantity
        if not _missing_value(resolved_quantity) and not _missing_value(notional_amount):
            raise ValueError(
                "Provide either quantity or notional_amount, not both. "
                "Use quantity for explicit share counts and notional_amount for cash-sized orders."
            )
        if _missing_value(resolved_quantity):
            sizing_context = _resolve_notional_quantity(
                runtime=runtime,
                order_type=order_type,
                side=side,
                ticker=ticker,
                notional_amount=notional_amount,
                notional_currency=notional_currency,
                limit_price=limit_price,
                stop_price=stop_price,
            )
            resolved_quantity = str(sizing_context.quantity)
        return runtime.broker_execution_service.prepare_order(
            order_type=order_type,
            side=side,
            ticker=ticker,
            quantity=resolved_quantity,
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force=time_in_force,
            extended_hours=extended_hours,
        ).model_copy(
            update=(
                {
                    "requested_notional_amount": sizing_context.notional_amount,
                    "requested_notional_currency": sizing_context.notional_currency,
                    "sizing_price": sizing_context.price,
                    "sizing_price_source": sizing_context.source,
                }
                if sizing_context is not None
                else {}
            )
        )
    except BrokerInstrumentResolutionError as exc:
        return _instrument_resolution_tool_error(exc)
    except ValueError as exc:
        error_text = str(exc)
        return _tool_error(
            error_text,
            code="invalid_order_request",
            hint=(
                "Provide either a share quantity or a notional_amount. For cash-sized "
                "market buy orders, ensure market data is configured; for sell market "
                "orders, ensure broker portfolio read access is available."
                if "notional" in error_text or "quantity" in error_text
                else (
                    "Resolve the instrument with broker_resolve_instrument and prepare "
                    "the order again using the broker-native ticker."
                )
            ),
        )
    except Exception as exc:
        return _tool_exception(
            exc,
            runtime=runtime,
            operation="prepare_order",
            message="Unable to prepare broker order.",
        )


def _resolve_notional_quantity(
    *,
    runtime: BrokerToolRuntime,
    order_type: str,
    side: str,
    ticker: str,
    notional_amount: str | int | float | None,
    notional_currency: str | None,
    limit_price: str | int | float | None,
    stop_price: str | int | float | None,
) -> _SizingContext:
    if _missing_value(notional_amount):
        raise ValueError(
            "quantity is required unless notional_amount is provided. "
            "For cash-sized orders, provide notional_amount and notional_currency."
        )
    amount = _positive_decimal(notional_amount, "notional_amount")
    currency = _normalize_currency(notional_currency)
    explicit_price = _explicit_sizing_price(
        order_type=order_type,
        limit_price=limit_price,
        stop_price=stop_price,
    )
    if explicit_price is not None:
        price, source = explicit_price
        return _sizing_context(amount=amount, currency=currency, price=price, source=source)

    if str(side or "").strip().upper() == "SELL":
        price, price_currency, source = _portfolio_sizing_price(runtime=runtime, ticker=ticker)
        _validate_sizing_currency(currency, price_currency, source=source)
        return _sizing_context(
            amount=amount,
            currency=currency or price_currency,
            price=price,
            source=source,
        )

    price, price_currency, source = _market_sizing_price(runtime=runtime, ticker=ticker)
    _validate_sizing_currency(currency, price_currency, source=source)
    return _sizing_context(
        amount=amount,
        currency=currency or price_currency,
        price=price,
        source=source,
    )


def _explicit_sizing_price(
    *,
    order_type: str,
    limit_price: str | int | float | None,
    stop_price: str | int | float | None,
) -> tuple[Decimal, str] | None:
    resolved_type = str(order_type or "").strip().upper()
    if resolved_type in {"LIMIT", "STOP_LIMIT"} and not _missing_value(limit_price):
        return _positive_decimal(limit_price, "limit_price"), "explicit_limit_price"
    if resolved_type == "STOP" and not _missing_value(stop_price):
        return _positive_decimal(stop_price, "stop_price"), "explicit_stop_price"
    return None


def _portfolio_sizing_price(
    *,
    runtime: BrokerToolRuntime,
    ticker: str,
) -> tuple[Decimal, str | None, str]:
    if runtime.broker_read_service is None:
        raise ValueError(
            "Cannot size sell order from notional_amount because broker portfolio "
            "read access is unavailable and no explicit limit/stop price was provided."
        )
    snapshot = runtime.broker_read_service.get_portfolio_snapshot()
    requested = str(ticker or "").strip()
    matched = None
    for position in snapshot.positions:
        instrument = position.instrument
        position_ticker = str(instrument.ticker or "").strip() if instrument else ""
        if position_ticker == requested:
            matched = position
            break
    if matched is None:
        for position in snapshot.positions:
            instrument = position.instrument
            position_ticker = str(instrument.ticker or "").strip() if instrument else ""
            if position_ticker.upper() == requested.upper():
                matched = position
                break
    if matched is None:
        holdings = _portfolio_holdings_for_sizing_error(snapshot.positions)
        raise ValueError(
            "Cannot size sell order from notional_amount because the prepared ticker "
            f"{requested!r} did not match a current portfolio holding. Current holdings: {holdings}"
        )
    price = _positive_decimal(matched.current_price, "currentPrice")
    instrument = matched.instrument
    wallet = matched.wallet_impact
    currency = (
        str(instrument.currency or "").strip().upper()
        if instrument and instrument.currency
        else None
    ) or (
        str(wallet.currency or "").strip().upper()
        if wallet and wallet.currency
        else None
    )
    return price, currency, "portfolio_current_price"


def _market_sizing_price(
    *,
    runtime: BrokerToolRuntime,
    ticker: str,
) -> tuple[Decimal, str | None, str]:
    if runtime.market_data_service is None:
        raise ValueError(
            "Cannot size buy market order from notional_amount because no explicit "
            "limit/stop price was provided and market data is unavailable."
        )
    symbols = _market_data_symbols(runtime=runtime, ticker=ticker)
    if not symbols:
        raise ValueError(
            "Cannot size buy market order from notional_amount because no market-data "
            "symbol could be derived from the requested broker ticker."
        )
    quotes = runtime.market_data_service.get_quote_snapshot(symbols)
    for symbol in symbols:
        quote = quotes.quotes.get(symbol) or quotes.quotes.get(symbol.upper())
        if not quote:
            continue
        try:
            price = _positive_decimal(quote.get("price"), "market price")
        except ValueError:
            continue
        currency = _normalize_currency(quote.get("currency"))
        return price, currency, f"market_data_quote:{symbol}"
    raise ValueError(
        "Cannot size buy market order from notional_amount because market data did "
        f"not return a usable price for {', '.join(symbols)}."
    )


def _market_data_symbols(*, runtime: BrokerToolRuntime, ticker: str) -> list[str]:
    symbols: list[str] = []

    def add(value: Any) -> None:
        raw = str(value or "").strip()
        if raw and raw not in symbols:
            symbols.append(raw)

    add(ticker)
    add(str(ticker or "").split("_", 1)[0])
    resolver = runtime.broker_read_service or runtime.broker_execution_service
    try:
        resolution = resolver.resolve_instrument(ticker, limit=3) if resolver is not None else None
    except Exception:
        resolution = None
    if resolution is not None:
        add(resolution.resolved_ticker)
        if resolution.resolved_ticker:
            add(str(resolution.resolved_ticker).split("_", 1)[0])
        for candidate in resolution.candidates:
            add(candidate.ticker)
            add(str(candidate.ticker).split("_", 1)[0])
        search = getattr(runtime.market_data_service, "search_symbols", None)
        if callable(search):
            for candidate in resolution.candidates[:2]:
                for query in (candidate.name, candidate.short_name):
                    if not query:
                        continue
                    try:
                        result = search(str(query), quotes_count=5, news_count=0)
                    except Exception:
                        continue
                    for market_candidate in result.candidates:
                        add(market_candidate.get("symbol"))
    return symbols


def _sizing_context(
    *,
    amount: Decimal,
    currency: str | None,
    price: Decimal,
    source: str,
) -> _SizingContext:
    quantity = (amount / price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    if quantity <= 0:
        raise ValueError(
            "notional_amount is too small to produce a positive share quantity "
            f"at sizing price {price}."
        )
    return _SizingContext(
        notional_amount=amount,
        notional_currency=currency,
        price=price,
        source=source,
        quantity=quantity,
    )


def _validate_sizing_currency(
    requested_currency: str | None,
    price_currency: str | None,
    *,
    source: str,
) -> None:
    if not requested_currency or not price_currency:
        return
    if requested_currency != price_currency:
        raise ValueError(
            "Cannot size order from notional_amount because the requested currency "
            f"{requested_currency} does not match the sizing price currency "
            f"{price_currency} from {source}."
        )


def _portfolio_holdings_for_sizing_error(positions) -> str:
    if not positions:
        return "none"
    parts = []
    for position in positions:
        instrument = position.instrument
        parts.append(
            "{"
            f"name={_format_value(instrument.name if instrument else None)}, "
            f"ticker={_format_value(instrument.ticker if instrument else None)}, "
            f"quantityAvailableForTrading={_format_value(position.quantity_available_for_trading)}, "
            f"currentPrice={_format_value(position.current_price)}"
            "}"
        )
    return "; ".join(parts)


def _missing_value(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _positive_decimal(value: Any, field_name: str) -> Decimal:
    if _missing_value(value):
        raise ValueError(f"{field_name} is required.")
    try:
        resolved = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} must be a valid decimal number.") from exc
    if resolved <= 0:
        raise ValueError(f"{field_name} must be greater than zero.")
    return resolved


def _normalize_currency(value: Any) -> str | None:
    raw = str(value or "").strip().upper()
    return raw or None
