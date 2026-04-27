"""Read-only pending-orders review workflow."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

from pydantic import BaseModel, Field

from t212ai.brokers.trading212.models import Order, OrderStatus, OrderType
from t212ai.brokers.trading212.protocols import Trading212AgentBrokerProtocol
from t212ai.genai.tracing import set_trace_metadata, traceable

from .errors import WorkflowExecutionError


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PendingOrderReviewItem(BaseModel):
    order_id: int | None = None
    ticker: str | None = None
    instrument_name: str | None = None
    side: str | None = None
    order_type: str | None = None
    status: str | None = None
    quantity: Decimal | None = None
    filled_quantity: Decimal | None = None
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    currency: str | None = None
    time_in_force: str | None = None
    created_at: datetime | None = None
    age_hours: Decimal | None = None
    attention_flags: list[str] = Field(default_factory=list)


class PendingOrdersReviewResult(BaseModel):
    reviewed_at: datetime
    order_count: int = 0
    attention_order_count: int = 0
    status_breakdown: dict[str, int] = Field(default_factory=dict)
    highlights: list[str] = Field(default_factory=list)
    orders: list[PendingOrderReviewItem] = Field(default_factory=list)

    def render_text(self) -> str:
        lines = [
            "Trading 212 pending orders review.",
            f"Reviewed at: {_format_value(self.reviewed_at)}.",
            f"Pending order count: {self.order_count}.",
        ]
        if self.status_breakdown:
            lines.append(
                "Status breakdown: "
                + ", ".join(
                    f"{status}={count}"
                    for status, count in sorted(self.status_breakdown.items())
                )
                + "."
            )
        if self.highlights:
            lines.append("Attention items:")
            lines.extend(f"- {item}" for item in self.highlights)
        if self.orders:
            lines.append("Order details:")
            for order in self.orders:
                detail = (
                    "- "
                    f"id={_format_value(order.order_id)}, "
                    f"ticker={_format_value(order.ticker)}, "
                    f"side={_format_value(order.side)}, "
                    f"type={_format_value(order.order_type)}, "
                    f"status={_format_value(order.status)}, "
                    f"quantity={_format_value(order.quantity)}, "
                    f"filled_quantity={_format_value(order.filled_quantity)}, "
                    f"limit_price={_format_money(order.limit_price, order.currency)}, "
                    f"stop_price={_format_money(order.stop_price, order.currency)}, "
                    f"time_in_force={_format_value(order.time_in_force)}, "
                    f"age_hours={_format_value(order.age_hours)}."
                )
                lines.append(detail)
                if order.attention_flags:
                    lines.append(
                        "  attention_flags: " + "; ".join(order.attention_flags) + "."
                    )
        else:
            lines.append("Order details: no active/pending orders returned by Trading 212.")
        return "\n".join(lines)


@dataclass(slots=True)
class PendingOrdersReviewWorkflow:
    broker: Trading212AgentBrokerProtocol
    clock: Callable[[], datetime] = field(default=_utcnow)

    @traceable(name="Pending Orders Review Workflow", run_type="chain")
    def run(self) -> PendingOrdersReviewResult:
        set_trace_metadata(workflow="pending_orders_review", provider="trading212")
        try:
            orders = self.broker.list_pending_orders()
        except Exception as exc:
            raise WorkflowExecutionError(
                "Unable to retrieve pending Trading 212 orders.",
                code="pending_orders_failed",
                hint=(
                    "Check Trading 212 credentials, broker connectivity, and whether "
                    "the orders scope is enabled for the selected environment."
                ),
                details={
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                },
            ) from exc
        return _build_pending_orders_review(orders, reviewed_at=self.clock())


def _build_pending_orders_review(
    orders: list[Order],
    *,
    reviewed_at: datetime,
) -> PendingOrdersReviewResult:
    normalized_orders = [
        _summarize_order(order, reviewed_at=reviewed_at)
        for order in sorted(
            orders,
            key=lambda item: item.created_at or datetime.max.replace(tzinfo=timezone.utc),
        )
    ]
    status_breakdown = Counter(
        item.status or "UNKNOWN"
        for item in normalized_orders
    )
    attention_count = sum(1 for item in normalized_orders if item.attention_flags)
    highlights: list[str] = []
    if not normalized_orders:
        highlights.append("Trading 212 returned no active or pending orders.")
    else:
        oldest = max(
            (item.age_hours for item in normalized_orders if item.age_hours is not None),
            default=None,
        )
        if oldest is not None:
            highlights.append(f"The oldest pending order has been open for {_format_value(oldest)} hour(s).")
        partial_fills = [
            item
            for item in normalized_orders
            if item.status == OrderStatus.PARTIALLY_FILLED.value
        ]
        if partial_fills:
            highlights.append(
                f"{len(partial_fills)} order(s) are partially filled and may need active monitoring."
            )
        if attention_count:
            highlights.append(
                f"{attention_count} pending order(s) have attention flags from the review."
            )

    return PendingOrdersReviewResult(
        reviewed_at=reviewed_at,
        order_count=len(normalized_orders),
        attention_order_count=attention_count,
        status_breakdown=dict(status_breakdown),
        highlights=highlights,
        orders=normalized_orders,
    )


def _summarize_order(
    order: Order,
    *,
    reviewed_at: datetime,
) -> PendingOrderReviewItem:
    created_at = _ensure_aware(order.created_at)
    age_hours: Decimal | None = None
    if created_at is not None:
        age_hours = Decimal(str(round((reviewed_at - created_at).total_seconds() / 3600, 1)))

    flags: list[str] = []
    if order.status == OrderStatus.PARTIALLY_FILLED:
        flags.append("Order is partially filled.")
    if age_hours is not None and age_hours >= Decimal("24"):
        flags.append("Order has been open for more than 24 hours.")
    if order.type == OrderType.MARKET and age_hours is not None and age_hours >= Decimal("1"):
        flags.append("Market order is still pending more than 1 hour after creation.")
    if order.type in {OrderType.LIMIT, OrderType.STOP_LIMIT} and order.limit_price is None:
        flags.append("Limit-style order is missing limit_price in broker response.")
    if order.type in {OrderType.STOP, OrderType.STOP_LIMIT} and order.stop_price is None:
        flags.append("Stop-style order is missing stop_price in broker response.")
    if (
        order.filled_quantity is not None
        and order.quantity is not None
        and abs(order.filled_quantity) > 0
        and abs(order.filled_quantity) < abs(order.quantity)
    ):
        flags.append("Filled quantity is below requested quantity.")

    return PendingOrderReviewItem(
        order_id=order.id,
        ticker=order.ticker,
        instrument_name=order.instrument.name if order.instrument else None,
        side=_enum_value(order.side),
        order_type=_enum_value(order.type),
        status=_enum_value(order.status),
        quantity=order.quantity,
        filled_quantity=order.filled_quantity,
        limit_price=order.limit_price,
        stop_price=order.stop_price,
        currency=order.currency,
        time_in_force=_enum_value(order.time_in_force),
        created_at=created_at,
        age_hours=age_hours,
        attention_flags=flags,
    )

def _ensure_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _enum_value(value: object) -> str | None:
    raw = getattr(value, "value", value)
    text = str(raw).strip() if raw is not None else ""
    return text or None


def _format_money(value: Decimal | None, currency: str | None) -> str:
    formatted = _format_value(value)
    if formatted == "unknown" or not currency:
        return formatted
    return f"{formatted} {currency}"


def _format_value(value: object) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        return value.isoformat()
    raw = getattr(value, "value", value)
    return str(raw)
