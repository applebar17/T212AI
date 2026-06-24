from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from t212ai.brokers.trading212.models import (
    AccountSummary,
    Cash,
    Instrument,
    Investments,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    PortfolioSnapshot,
    Position,
    PositionWalletImpact,
    TimeValidity,
)
from t212ai.workflows import PendingOrdersReviewWorkflow, PortfolioSummaryWorkflow


class FakeWorkflowBroker:
    def __init__(self) -> None:
        self.reviewed_at = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)

    def get_portfolio_snapshot(self) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            as_of=self.reviewed_at,
            account=AccountSummary(
                id=1,
                currency="EUR",
                cash=Cash(
                    available_to_trade=Decimal("1000"),
                    reserved_for_orders=Decimal("100"),
                    in_pies=Decimal("50"),
                ),
                investments=Investments(
                    current_value=Decimal("2400"),
                    total_cost=Decimal("2000"),
                    unrealized_profit_loss=Decimal("400"),
                    realized_profit_loss=Decimal("50"),
                ),
                total_value=Decimal("3500"),
            ),
            positions=[
                Position(
                    instrument=Instrument(
                        ticker="AAPL_US_EQ",
                        name="Apple",
                        currency="EUR",
                        isin="US0378331005",
                    ),
                    quantity=Decimal("6"),
                    average_price_paid=Decimal("150"),
                    current_price=Decimal("200"),
                    wallet_impact=PositionWalletImpact(
                        currency="EUR",
                        current_value=Decimal("1200"),
                        total_cost=Decimal("900"),
                        unrealized_profit_loss=Decimal("300"),
                    ),
                ),
                Position(
                    instrument=Instrument(
                        ticker="NVDA_US_EQ",
                        name="NVIDIA",
                        currency="EUR",
                        isin="US67066G1040",
                    ),
                    quantity=Decimal("2"),
                    average_price_paid=Decimal("400"),
                    current_price=Decimal("350"),
                    wallet_impact=PositionWalletImpact(
                        currency="EUR",
                        current_value=Decimal("700"),
                        total_cost=Decimal("800"),
                        unrealized_profit_loss=Decimal("-100"),
                    ),
                ),
                Position(
                    instrument=Instrument(
                        ticker="TSM_US_EQ",
                        name="TSMC",
                        currency="EUR",
                        isin="US8740391003",
                    ),
                    quantity=Decimal("5"),
                    average_price_paid=Decimal("90"),
                    current_price=Decimal("100"),
                    wallet_impact=PositionWalletImpact(
                        currency="EUR",
                        current_value=Decimal("500"),
                        total_cost=Decimal("450"),
                        unrealized_profit_loss=Decimal("50"),
                    ),
                ),
            ],
            pending_orders=[
                Order(
                    id=10,
                    ticker="MSFT_US_EQ",
                    currency="EUR",
                    quantity=Decimal("1"),
                    side=OrderSide.BUY,
                    status=OrderStatus.NEW,
                    type=OrderType.LIMIT,
                    limit_price=Decimal("300"),
                    time_in_force=TimeValidity.DAY,
                    created_at=self.reviewed_at - timedelta(hours=2),
                )
            ],
        )

    def list_pending_orders(self) -> list[Order]:
        return [
            Order(
                id=101,
                ticker="TSLA_US_EQ",
                currency="USD",
                quantity=Decimal("10"),
                filled_quantity=Decimal("2"),
                side=OrderSide.BUY,
                status=OrderStatus.PARTIALLY_FILLED,
                type=OrderType.LIMIT,
                limit_price=Decimal("170"),
                time_in_force=TimeValidity.DAY,
                created_at=self.reviewed_at - timedelta(hours=30),
            ),
            Order(
                id=102,
                ticker="META_US_EQ",
                currency="USD",
                quantity=Decimal("3"),
                side=OrderSide.SELL,
                status=OrderStatus.NEW,
                type=OrderType.MARKET,
                created_at=self.reviewed_at - timedelta(hours=2),
            ),
        ]


def test_portfolio_summary_workflow_returns_all_ranked_positions_by_default() -> None:
    workflow = PortfolioSummaryWorkflow(FakeWorkflowBroker())

    result = workflow.run()

    assert result.position_count == 3
    assert result.displayed_position_count == 3
    assert result.top_positions_limit is None
    assert result.pending_order_count == 1
    assert result.top_positions[0].ticker == "AAPL_US_EQ"
    assert result.top_positions[0].isin == "US0378331005"
    assert any("Largest position AAPL_US_EQ" in item for item in result.highlights)
    rendered = result.render_text()
    assert "Trading 212 portfolio summary." in rendered
    assert "Open positions: 3. Showing all 3 by current value." in rendered
    assert "Open positions by current value:" in rendered
    assert "identifier=US0378331005" in rendered


def test_portfolio_summary_workflow_limits_to_top_positions_when_requested() -> None:
    workflow = PortfolioSummaryWorkflow(FakeWorkflowBroker())

    result = workflow.run(top_positions_limit=2)

    assert result.position_count == 3
    assert result.displayed_position_count == 2
    assert result.top_positions_limit == 2
    assert [position.ticker for position in result.top_positions] == [
        "AAPL_US_EQ",
        "NVDA_US_EQ",
    ]
    rendered = result.render_text()
    assert "Open positions: 3. Showing top 2 by current value." in rendered
    assert "Top 2 positions by current value:" in rendered
    assert "TSM_US_EQ" not in rendered


def test_pending_orders_review_workflow_flags_old_and_partial_orders() -> None:
    broker = FakeWorkflowBroker()
    workflow = PendingOrdersReviewWorkflow(
        broker,
        clock=lambda: broker.reviewed_at,
    )

    result = workflow.run()

    assert result.order_count == 2
    assert result.attention_order_count == 2
    assert result.status_breakdown == {"NEW": 1, "PARTIALLY_FILLED": 1}
    assert result.orders[0].order_id == "101"
    assert "Order is partially filled." in result.orders[0].attention_flags
    assert "Order has been open for more than 24 hours." in result.orders[0].attention_flags
    assert "Market order is still pending more than 1 hour after creation." in result.orders[1].attention_flags
    assert "Trading 212 pending orders review." in result.render_text()
