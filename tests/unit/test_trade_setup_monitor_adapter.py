from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from t212ai.agent.schemas import AgentResponse
from t212ai.brokers.models import (
    BrokerAccountSummary,
    BrokerOrderSide,
    BrokerOrderType,
    BrokerPortfolioSnapshot,
    BrokerTimeInForce,
    PreparedBrokerOrder,
)
from t212ai.capabilities.market_data_models import MarketQuoteSnapshotResult
from t212ai.pending_actions import PendingActionService
from t212ai.persistence.database import build_engine, build_session_factory, ensure_schema
from t212ai.proposals import ProposalService
from t212ai.scheduler import (
    ScheduledProcess,
    ScheduledProcessService,
    ScheduledRunStatus,
    TradeSetupAnalysis,
    TradeSetupMonitorAdapter,
)


class FakeGenAI:
    def __init__(self, analysis: TradeSetupAnalysis) -> None:
        self.analysis = analysis
        self.calls: list[dict[str, object]] = []

    def chat_model_for(self, purpose: str | None = None) -> str:
        return f"{purpose or 'default'}-model"

    def generate_structured(
        self,
        schema,
        system_prompt,
        chat_message,
        *,
        model=None,
        temperature=0.0,
        max_tokens=None,
    ):
        self.calls.append(
            {
                "schema": schema.__name__,
                "system_prompt": system_prompt,
                "chat_message": chat_message,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        assert schema is TradeSetupAnalysis
        return self.analysis


class FakeMarketAgent:
    name = "market_analyst"

    def __init__(self, genai: FakeGenAI) -> None:
        self.reasoner = SimpleNamespace(genai=genai)
        self.calls: list[dict[str, object]] = []

    def handle(self, request, *, intent=None, task_complexity=None):
        self.calls.append(
            {
                "request": request,
                "intent": intent,
                "task_complexity": task_complexity,
            }
        )
        return AgentResponse(
            final_answer="Trade setup evaluated.",
            selected_agent=self.name,
            metadata={"workflow": "market_analysis"},
            artifacts={"summary": "setup artifact"},
        )


class FakeMarketDataService:
    provider_name = "fake_market"

    def __init__(self, *, price: float = 181.0, change_pct: float = 1.0) -> None:
        self.price = price
        self.change_pct = change_pct
        self.quote_calls = 0

    def get_quote_snapshot(self, symbols):
        self.quote_calls += 1
        symbol = symbols[0]
        return MarketQuoteSnapshotResult(
            quotes={
                symbol: {
                    "symbol": symbol,
                    "price": self.price,
                    "change_pct": self.change_pct,
                    "currency": "USD",
                    "market_state": "REGULAR",
                }
            },
            errors={},
            meta={"provider": self.provider_name},
        )

    def get_price_history(self, symbols, **kwargs):
        raise AssertionError("history should not be called by these tests")


class FakeBrokerReadService:
    def get_portfolio_snapshot(self):
        return BrokerPortfolioSnapshot(
            account=BrokerAccountSummary(currency="USD"),
            positions=[],
            pending_orders=[],
        )


class FakeBrokerExecutionService:
    def __init__(self) -> None:
        self.prepare_calls: list[dict[str, object]] = []
        self.submit_calls = 0

    def prepare_order(self, **kwargs):
        self.prepare_calls.append(dict(kwargs))
        quantity = kwargs.get("quantity") or Decimal("1")
        side = BrokerOrderSide(str(kwargs["side"]).upper())
        order_type = BrokerOrderType(str(kwargs["order_type"]).upper())
        return PreparedBrokerOrder(
            brokerProvider="fake_broker",
            orderType=order_type,
            side=side,
            ticker=str(kwargs["ticker"]).upper(),
            requestedTicker=str(kwargs["ticker"]).upper(),
            quantity=Decimal(str(quantity)),
            signedQuantity=Decimal(str(quantity)) if side == BrokerOrderSide.BUY else -Decimal(str(quantity)),
            requestedNotionalAmount=kwargs.get("notional_amount"),
            requestedNotionalCurrency=kwargs.get("notional_currency"),
            limitPrice=kwargs.get("limit_price"),
            stopPrice=kwargs.get("stop_price"),
            timeInForce=BrokerTimeInForce(str(kwargs["time_in_force"]).upper()),
            extendedHours=bool(kwargs.get("extended_hours", False)),
            requestPayload=dict(kwargs),
            orderFingerprint="fingerprint-tsla-buy",
        )

    def submit_prepared_order(self, prepared_order):
        del prepared_order
        self.submit_calls += 1
        raise AssertionError("scheduler adapter must not submit broker orders")


def _session_factory(tmp_path: Path):
    engine = build_engine(f"sqlite:///{tmp_path / 'trade-setup.db'}")
    ensure_schema(engine)
    return build_session_factory(engine)


def _service(tmp_path: Path) -> ScheduledProcessService:
    return ScheduledProcessService(_session_factory(tmp_path))


def _process(
    tmp_path: Path,
    *,
    trigger_value: float = 180.0,
    proposal_allowed: bool = True,
    max_notional: str | None = "1000",
    max_quantity: str | None = None,
    allowed_sides: list[str] | None = None,
    safety: dict[str, object] | None = None,
    action: dict[str, object] | None = None,
) -> ScheduledProcess:
    service = _service(tmp_path)
    resolved_action = action or {
        "type": "notify_or_propose",
        "proposalCreationAllowed": proposal_allowed,
    }
    if proposal_allowed and action is None:
        resolved_action = {
            **resolved_action,
            "orderPolicy": {
                "allowedSymbols": ["TSLA"],
                "allowedSides": allowed_sides or ["BUY"],
                "allowedOrderTypes": ["MARKET", "LIMIT"],
                "maxNotionalAmount": max_notional,
                "notionalCurrency": "USD" if max_notional is not None else None,
                "maxQuantity": max_quantity,
                "allowExtendedHours": False,
            },
            "approval": {"chatId": 12345, "userId": 678},
        }
    return service.create_process(
        title="TSLA trade setup",
        description="Watch for a trigger and evaluate a setup.",
        kind="trade_setup_monitor",
        execution_mode="llm_assisted",
        schedule={"type": "polling", "pollEverySeconds": 300},
        trigger={"type": "below_price", "symbol": "TSLA", "value": trigger_value},
        inputs={"symbol": "TSLA"},
        llm_scope={"taskGuidelines": "Only propose a trade if the setup is clear."},
        action=resolved_action,
        notification={"enabled": True},
        lifecycle={
            "completionPolicy": "complete_on_first_match",
            "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
        },
        safety=safety or {"brokerActionsAllowed": False},
    )


def _raw_process(
    *,
    safety: dict[str, object] | None = None,
    action: dict[str, object] | None = None,
) -> ScheduledProcess:
    now = datetime(2026, 5, 7, 9, 0, tzinfo=timezone.utc)
    return ScheduledProcess(
        process_id="sched_raw_trade_setup",
        title="TSLA trade setup",
        description="",
        kind="trade_setup_monitor",
        execution_mode="llm_assisted",
        status="active",
        schedule={"type": "polling", "pollEverySeconds": 300},
        trigger={"type": "below_price", "symbol": "TSLA", "value": 180},
        inputs={"symbol": "TSLA"},
        llm_scope={},
        action=action or {"type": "notify_or_propose", "proposalCreationAllowed": False},
        notification={"enabled": True},
        lifecycle={"completionPolicy": "complete_on_first_match"},
        safety=safety or {"brokerActionsAllowed": False},
        created_at=now,
        updated_at=now,
        next_run_at=now,
        last_run_at=None,
        last_status=None,
        failure_count=0,
    )


def _analysis(
    *,
    should_propose: bool = True,
    notional: str = "500",
    side: str = "BUY",
    ticker: str = "TSLA",
) -> TradeSetupAnalysis:
    proposed_order = None
    if should_propose:
        proposed_order = {
            "ticker": ticker,
            "side": side,
            "orderType": "MARKET",
            "notionalAmount": notional,
            "notionalCurrency": "USD",
            "timeInForce": "DAY",
            "extendedHours": False,
            "rationale": "Momentum reversal after threshold match.",
        }
    return TradeSetupAnalysis(
        symbol="TSLA",
        setupSummary="TSLA reached the monitored setup area.",
        thesis="The trigger matched and the setup has bounded downside.",
        risks=["Volatility can expand.", "News may invalidate the setup."],
        setupQuality="moderate" if should_propose else "reject",
        shouldProposeOrder=should_propose,
        proposedOrder=proposed_order,
        caveats=[],
        sourceRefs=[],
        dataFreshness="scheduled run evidence",
        telegramBrief="TSLA setup matched; review before any action.",
        confidence=0.72,
        noBrokerActionConfigured=True,
    )


def _adapter(
    *,
    analysis: TradeSetupAnalysis,
    market_data: FakeMarketDataService | None = None,
    broker_read: FakeBrokerReadService | None = None,
    broker_execution: FakeBrokerExecutionService | None = None,
    pending_action_service: PendingActionService | None = None,
    proposal_service: ProposalService | None = None,
) -> tuple[TradeSetupMonitorAdapter, FakeMarketAgent, FakeBrokerExecutionService | None]:
    genai = FakeGenAI(analysis)
    market_agent = FakeMarketAgent(genai)
    execution = broker_execution
    adapter = TradeSetupMonitorAdapter(
        market_agent=market_agent,
        market_data_service=market_data,
        broker_read_service=broker_read,
        broker_execution_service=execution,
        pending_action_service=pending_action_service,
        proposal_service=proposal_service,
        broker_provider="fake_broker",
    )
    return adapter, market_agent, execution


def test_trade_setup_no_trigger_match_avoids_llm_and_proposals(tmp_path: Path) -> None:
    pending = PendingActionService(_session_factory(tmp_path))
    proposals = ProposalService(_session_factory(tmp_path))
    execution = FakeBrokerExecutionService()
    adapter, market_agent, _ = _adapter(
        analysis=_analysis(),
        market_data=FakeMarketDataService(price=181.0),
        broker_read=FakeBrokerReadService(),
        broker_execution=execution,
        pending_action_service=pending,
        proposal_service=proposals,
    )

    result = adapter.run(_process(tmp_path, trigger_value=180.0))

    assert result.status == ScheduledRunStatus.COMPLETED
    assert result.matched is False
    assert result.code == "no_match"
    assert market_agent.calls == []
    assert execution.prepare_calls == []
    assert proposals.list_recent_proposals(chat_id="12345") == []


def test_trade_setup_matched_llm_rejection_creates_no_proposal(tmp_path: Path) -> None:
    pending = PendingActionService(_session_factory(tmp_path))
    proposals = ProposalService(_session_factory(tmp_path))
    execution = FakeBrokerExecutionService()
    adapter, market_agent, _ = _adapter(
        analysis=_analysis(should_propose=False),
        market_data=FakeMarketDataService(price=179.0),
        broker_read=FakeBrokerReadService(),
        broker_execution=execution,
        pending_action_service=pending,
        proposal_service=proposals,
    )

    result = adapter.run(_process(tmp_path, trigger_value=180.0))

    assert result.status == ScheduledRunStatus.COMPLETED
    assert result.matched is False
    assert result.code == "setup_rejected"
    assert market_agent.calls
    assert execution.prepare_calls == []
    assert proposals.list_recent_proposals(chat_id="12345") == []


def test_trade_setup_safe_order_creates_pending_approval_payload(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    pending = PendingActionService(session_factory)
    proposals = ProposalService(session_factory)
    execution = FakeBrokerExecutionService()
    adapter, market_agent, _ = _adapter(
        analysis=_analysis(notional="500"),
        market_data=FakeMarketDataService(price=179.0),
        broker_read=FakeBrokerReadService(),
        broker_execution=execution,
        pending_action_service=pending,
        proposal_service=proposals,
    )

    result = adapter.run(_process(tmp_path, trigger_value=180.0))

    assert result.status == ScheduledRunStatus.COMPLETED
    assert result.matched is True
    assert result.code == "pending_proposal_created"
    assert result.notification_approval_payload is not None
    assert result.notification_target_chat_ids == (12345,)
    assert result.metadata["proposalId"].startswith("pr_")
    assert result.metadata["pendingActionId"].startswith("pa_")
    assert result.metadata["preparedOrder"]["ticker"] == "TSLA"
    assert result.notification_approval_payload["approveCallbackData"] == (
        f"pa:approve:{result.metadata['pendingActionId']}"
    )
    assert "Nothing has been executed yet" in result.notification_message
    assert market_agent.calls
    assert execution.prepare_calls
    assert execution.submit_calls == 0
    assert proposals.get_by_pending_action_id(result.metadata["pendingActionId"]) is not None
    assert pending.get_action(result.metadata["pendingActionId"]) is not None


def test_trade_setup_rejects_unsafe_llm_order_terms_before_pending_action(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    pending = PendingActionService(session_factory)
    proposals = ProposalService(session_factory)
    execution = FakeBrokerExecutionService()
    adapter, _market_agent, _ = _adapter(
        analysis=_analysis(notional="1500"),
        market_data=FakeMarketDataService(price=179.0),
        broker_read=FakeBrokerReadService(),
        broker_execution=execution,
        pending_action_service=pending,
        proposal_service=proposals,
    )

    result = adapter.run(_process(tmp_path, trigger_value=180.0, max_notional="1000"))

    assert result.status == ScheduledRunStatus.COMPLETED
    assert result.matched is False
    assert result.code == "proposed_order_rejected"
    assert "exceeds maxNotionalAmount" in result.message
    assert execution.prepare_calls == []
    assert proposals.list_recent_proposals(chat_id="12345") == []


def test_trade_setup_skips_missing_runtime_services_after_match(tmp_path: Path) -> None:
    adapter, _market_agent, _ = _adapter(
        analysis=_analysis(),
        market_data=FakeMarketDataService(price=179.0),
        broker_read=None,
        broker_execution=FakeBrokerExecutionService(),
        pending_action_service=PendingActionService(_session_factory(tmp_path)),
        proposal_service=ProposalService(_session_factory(tmp_path)),
    )

    result = adapter.run(_process(tmp_path, trigger_value=180.0))

    assert result.status == ScheduledRunStatus.SKIPPED
    assert result.code == "broker_read_unavailable"


def test_trade_setup_skips_missing_market_data_or_llm(tmp_path: Path) -> None:
    process = _process(tmp_path, trigger_value=180.0)
    no_market_data, _market_agent, _execution = _adapter(
        analysis=_analysis(),
        market_data=None,
        broker_read=FakeBrokerReadService(),
        broker_execution=FakeBrokerExecutionService(),
        pending_action_service=PendingActionService(_session_factory(tmp_path)),
        proposal_service=ProposalService(_session_factory(tmp_path)),
    )
    missing_market = no_market_data.run(process)
    assert missing_market.status == ScheduledRunStatus.SKIPPED
    assert missing_market.code == "market_data_unavailable"

    missing_llm = TradeSetupMonitorAdapter(
        market_agent=None,
        market_data_service=FakeMarketDataService(price=179.0),
        broker_read_service=FakeBrokerReadService(),
        broker_execution_service=FakeBrokerExecutionService(),
        pending_action_service=PendingActionService(_session_factory(tmp_path)),
        proposal_service=ProposalService(_session_factory(tmp_path)),
    ).run(process)
    assert missing_llm.status == ScheduledRunStatus.SKIPPED
    assert missing_llm.code == "llm_unavailable"


def test_trade_setup_invalid_safety_or_action_spec_fails(tmp_path: Path) -> None:
    adapter, _market_agent, _execution = _adapter(
        analysis=_analysis(),
        market_data=FakeMarketDataService(price=179.0),
        broker_read=FakeBrokerReadService(),
        broker_execution=FakeBrokerExecutionService(),
        pending_action_service=PendingActionService(_session_factory(tmp_path)),
        proposal_service=ProposalService(_session_factory(tmp_path)),
    )

    unsafe = adapter.run(
        _raw_process(safety={"brokerActionsAllowed": True})
    )
    assert unsafe.status == ScheduledRunStatus.FAILED
    assert unsafe.code == "invalid_trade_setup_monitor_spec"

    invalid_action = adapter.run(
        _raw_process(action={"type": "execute_order", "proposalCreationAllowed": False})
    )
    assert invalid_action.status == ScheduledRunStatus.FAILED
    assert invalid_action.code == "invalid_trade_setup_monitor_spec"
