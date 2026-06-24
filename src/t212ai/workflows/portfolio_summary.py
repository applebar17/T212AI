"""Read-only portfolio summary workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from t212ai.brokers.models import BrokerPortfolioSnapshot, BrokerPosition
from t212ai.capabilities.protocols import BrokerReadService
from t212ai.genai.tracing import set_trace_metadata, traceable

from .errors import WorkflowExecutionError


class PortfolioPositionSummary(BaseModel):
    broker_position_ref: str | None = None
    isin: str | None = None
    ticker: str | None = None
    name: str | None = None
    quantity: Decimal | None = None
    current_price: Decimal | None = None
    average_price_paid: Decimal | None = None
    current_value: Decimal | None = None
    total_cost: Decimal | None = None
    unrealized_profit_loss: Decimal | None = None
    currency: str | None = None
    weight_pct: Decimal | None = None


class PortfolioSummaryResult(BaseModel):
    provider_label: str = "Trading 212"
    as_of: datetime
    account_currency: str | None = None
    total_value: Decimal | None = None
    available_cash: Decimal | None = None
    reserved_cash_for_orders: Decimal | None = None
    cash_in_pies: Decimal | None = None
    investments_current_value: Decimal | None = None
    investments_total_cost: Decimal | None = None
    unrealized_profit_loss: Decimal | None = None
    realized_profit_loss: Decimal | None = None
    position_count: int = 0
    displayed_position_count: int = 0
    top_positions_limit: int | None = None
    pending_order_count: int = 0
    top_positions: list[PortfolioPositionSummary] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)

    def render_text(self) -> str:
        lines = [
            f"{self.provider_label} portfolio summary.",
            f"As of: {_format_value(self.as_of)}.",
            (
                "Account: "
                f"currency={_format_value(self.account_currency)}, "
                f"total_value={_format_money(self.total_value, self.account_currency)}."
            ),
            (
                "Cash: "
                f"available_to_trade={_format_money(self.available_cash, self.account_currency)}, "
                "reserved_for_orders="
                f"{_format_money(self.reserved_cash_for_orders, self.account_currency)}, "
                f"in_pies={_format_money(self.cash_in_pies, self.account_currency)}."
            ),
            (
                "Investments: "
                f"current_value={_format_money(self.investments_current_value, self.account_currency)}, "
                f"total_cost={_format_money(self.investments_total_cost, self.account_currency)}, "
                "unrealized_pnl="
                f"{_format_money(self.unrealized_profit_loss, self.account_currency)}, "
                f"realized_pnl={_format_money(self.realized_profit_loss, self.account_currency)}."
            ),
            (
                f"Open positions: {self.position_count}. "
                f"{self._render_position_scope()}"
                f"Pending orders: {self.pending_order_count}."
            ),
        ]
        if self.top_positions:
            lines.append(self._render_positions_heading())
            for position in self.top_positions:
                lines.append(
                    "- "
                    f"{_format_value(position.ticker)}"
                    f"{f' ({position.name})' if position.name else ''}: "
                    f"identifier={_format_identifier(position)}, "
                    f"quantity={_format_value(position.quantity)}, "
                    f"current_value={_format_money(position.current_value, position.currency)}, "
                    f"weight={_format_pct(position.weight_pct)}, "
                    f"avg_price={_format_money(position.average_price_paid, position.currency)}, "
                    f"current_price={_format_money(position.current_price, position.currency)}, "
                    "unrealized_pnl="
                    f"{_format_money(position.unrealized_profit_loss, position.currency)}."
                )
        if self.highlights:
            lines.append("Attention items:")
            lines.extend(f"- {item}" for item in self.highlights)
        return "\n".join(lines)

    def _render_position_scope(self) -> str:
        if self.position_count == 0:
            return ""
        if (
            self.top_positions_limit is not None
            and self.displayed_position_count < self.position_count
        ):
            return f"Showing top {self.displayed_position_count} by current value. "
        return f"Showing all {self.displayed_position_count} by current value. "

    def _render_positions_heading(self) -> str:
        if (
            self.top_positions_limit is not None
            and self.displayed_position_count < self.position_count
        ):
            return f"Top {self.displayed_position_count} positions by current value:"
        return "Open positions by current value:"


@dataclass(slots=True)
class PortfolioSummaryWorkflow:
    broker: BrokerReadService
    provider_label: str = "Trading 212"
    top_positions_limit: int | None = None

    @traceable(name="Portfolio Summary Workflow", run_type="chain")
    def run(
        self,
        *,
        top_positions_limit: int | None = None,
    ) -> PortfolioSummaryResult:
        set_trace_metadata(workflow="portfolio_summary", provider=self.provider_label.lower())
        try:
            snapshot = self.broker.get_portfolio_snapshot()
        except Exception as exc:
            raise WorkflowExecutionError(
                f"Unable to retrieve the {self.provider_label} portfolio snapshot.",
                code="broker_snapshot_failed",
                hint=(
                    f"Check {self.provider_label} credentials, selected environment, "
                    "portfolio/orders access, and broker connectivity."
                ),
                details={
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                },
            ) from exc
        resolved_top_positions_limit = _normalize_top_positions_limit(
            top_positions_limit
            if top_positions_limit is not None
            else self.top_positions_limit
        )
        return _build_portfolio_summary(
            snapshot,
            top_positions_limit=resolved_top_positions_limit,
            provider_label=self.provider_label,
        )


def _build_portfolio_summary(
    snapshot: BrokerPortfolioSnapshot,
    *,
    top_positions_limit: int | None,
    provider_label: str,
) -> PortfolioSummaryResult:
    account = snapshot.account
    cash = account.cash
    investments = account.investments
    positions = sorted(
        snapshot.positions,
        key=lambda item: _decimal_or_zero(item.wallet_impact.current_value if item.wallet_impact else None),
        reverse=True,
    )
    denominator = (
        _positive_or_none(investments.current_value if investments else None)
        or _sum_position_values(snapshot.positions)
        or _positive_or_none(account.total_value)
    )

    selected_positions = (
        positions
        if top_positions_limit is None
        else positions[:top_positions_limit]
    )
    top_positions = [
        _summarize_position(position, denominator=denominator)
        for position in selected_positions
    ]

    highlights: list[str] = []
    if not snapshot.positions:
        highlights.append(f"{provider_label} returned no open positions.")
    if top_positions and (top_positions[0].weight_pct or Decimal("0")) >= Decimal("50"):
        highlights.append(
            f"Largest position {_format_value(top_positions[0].ticker)} accounts for "
            f"{_format_pct(top_positions[0].weight_pct)} of tracked invested value."
        )
    if snapshot.pending_orders:
        highlights.append(
            f"{len(snapshot.pending_orders)} pending order(s) are already affecting available cash."
        )
    if (
        cash
        and cash.available_to_trade is not None
        and account.total_value
        and account.total_value > 0
        and (cash.available_to_trade / account.total_value) >= Decimal("0.30")
    ):
        highlights.append(
            "Available cash is at least 30% of total account value, so cash drag may be material."
        )
    negative_positions = [
        position
        for position in top_positions
        if (position.unrealized_profit_loss or Decimal("0")) < 0
    ]
    if negative_positions:
        highlights.append(
            f"{len(negative_positions)} of the displayed {len(top_positions)} position(s) show negative unrealized P/L."
        )

    return PortfolioSummaryResult(
        provider_label=provider_label,
        as_of=snapshot.as_of,
        account_currency=account.currency,
        total_value=account.total_value,
        available_cash=cash.available_to_trade if cash else None,
        reserved_cash_for_orders=cash.reserved_for_orders if cash else None,
        cash_in_pies=cash.in_pies if cash else None,
        investments_current_value=investments.current_value if investments else None,
        investments_total_cost=investments.total_cost if investments else None,
        unrealized_profit_loss=investments.unrealized_profit_loss if investments else None,
        realized_profit_loss=investments.realized_profit_loss if investments else None,
        position_count=len(snapshot.positions),
        displayed_position_count=len(top_positions),
        top_positions_limit=top_positions_limit,
        pending_order_count=len(snapshot.pending_orders),
        top_positions=top_positions,
        highlights=highlights,
    )


def _summarize_position(
    position: BrokerPosition,
    *,
    denominator: Decimal | None,
) -> PortfolioPositionSummary:
    instrument = position.instrument
    wallet = position.wallet_impact
    current_value = wallet.current_value if wallet else None
    currency = (wallet.currency if wallet else None) or (instrument.currency if instrument else None)
    weight_pct: Decimal | None = None
    if current_value is not None and denominator and denominator > 0:
        weight_pct = (current_value / denominator) * Decimal("100")
    return PortfolioPositionSummary(
        broker_position_ref=_native_position_ref(position),
        isin=instrument.isin if instrument else None,
        ticker=instrument.ticker if instrument else None,
        name=instrument.name if instrument else None,
        quantity=position.quantity,
        current_price=position.current_price,
        average_price_paid=position.average_price_paid,
        current_value=current_value,
        total_cost=wallet.total_cost if wallet else None,
        unrealized_profit_loss=wallet.unrealized_profit_loss if wallet else None,
        currency=currency,
        weight_pct=weight_pct,
    )


def _normalize_top_positions_limit(value: int | None) -> int | None:
    if value is None:
        return None
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        return None
    return resolved if resolved > 0 else None


def _native_position_ref(position: BrokerPosition) -> str | None:
    for attr in ("id", "position_id", "positionId"):
        resolved = _non_empty_str(getattr(position, attr, None))
        if resolved is not None:
            return resolved
    raw_payload = getattr(position, "raw_provider_payload", None)
    if isinstance(raw_payload, dict):
        for key in ("id", "position_id", "positionId"):
            resolved = _non_empty_str(raw_payload.get(key))
            if resolved is not None:
                return resolved
    return None


def _format_identifier(position: PortfolioPositionSummary) -> str:
    return (
        position.broker_position_ref
        or position.isin
        or position.ticker
        or "unknown"
    )


def _non_empty_str(value: Any) -> str | None:
    raw = str(value or "").strip()
    return raw or None


def _sum_position_values(positions: list[BrokerPosition]) -> Decimal | None:
    total = sum(
        (
            _decimal_or_zero(position.wallet_impact.current_value if position.wallet_impact else None)
            for position in positions
        ),
        start=Decimal("0"),
    )
    return total if total > 0 else None


def _positive_or_none(value: Decimal | None) -> Decimal | None:
    if value is None or value <= 0:
        return None
    return value


def _decimal_or_zero(value: Decimal | None) -> Decimal:
    return value if value is not None else Decimal("0")


def _format_money(value: Decimal | None, currency: str | None) -> str:
    formatted = _format_value(value)
    if formatted == "unknown" or not currency:
        return formatted
    return f"{formatted} {currency}"


def _format_pct(value: Decimal | None) -> str:
    if value is None:
        return "unknown"
    return f"{value.quantize(Decimal('0.1'))}%"


def _format_value(value: object) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        return value.isoformat()
    raw = getattr(value, "value", value)
    return str(raw)
