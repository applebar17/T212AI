"""Read-only portfolio summary workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from t212ai.brokers.trading212.models import PortfolioSnapshot, Position
from t212ai.capabilities.protocols import BrokerReadService
from t212ai.genai.tracing import set_trace_metadata, traceable

from .errors import WorkflowExecutionError


class PortfolioPositionSummary(BaseModel):
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
    pending_order_count: int = 0
    top_positions: list[PortfolioPositionSummary] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)

    def render_text(self) -> str:
        lines = [
            "Trading 212 portfolio summary.",
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
                f"Pending orders: {self.pending_order_count}."
            ),
        ]
        if self.top_positions:
            lines.append("Top positions by current value:")
            for position in self.top_positions:
                lines.append(
                    "- "
                    f"{_format_value(position.ticker)}"
                    f"{f' ({position.name})' if position.name else ''}: "
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


@dataclass(slots=True)
class PortfolioSummaryWorkflow:
    broker: BrokerReadService
    max_positions: int = 5

    @traceable(name="Portfolio Summary Workflow", run_type="chain")
    def run(self) -> PortfolioSummaryResult:
        set_trace_metadata(workflow="portfolio_summary", provider="trading212")
        try:
            snapshot = self.broker.get_portfolio_snapshot()
        except Exception as exc:
            raise WorkflowExecutionError(
                "Unable to retrieve the Trading 212 portfolio snapshot.",
                code="broker_snapshot_failed",
                hint=(
                    "Check Trading 212 credentials, demo/live environment selection, "
                    "portfolio and orders scopes, and broker connectivity."
                ),
                details={
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                },
            ) from exc
        return _build_portfolio_summary(snapshot, max_positions=self.max_positions)


def _build_portfolio_summary(
    snapshot: PortfolioSnapshot,
    *,
    max_positions: int,
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

    top_positions = [
        _summarize_position(position, denominator=denominator)
        for position in positions[:max_positions]
    ]

    highlights: list[str] = []
    if not snapshot.positions:
        highlights.append("Trading 212 returned no open positions.")
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
            f"{len(negative_positions)} of the top {len(top_positions)} position(s) show negative unrealized P/L."
        )

    return PortfolioSummaryResult(
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
        pending_order_count=len(snapshot.pending_orders),
        top_positions=top_positions,
        highlights=highlights,
    )


def _summarize_position(
    position: Position,
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


def _sum_position_values(positions: list[Position]) -> Decimal | None:
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
