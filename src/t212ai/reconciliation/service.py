"""Backend order reconciliation service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from t212ai.brokers.models import (
    BrokerHistoricalOrder,
    BrokerOrder,
    BrokerOrderStatus,
    BrokerOrderType,
)
from t212ai.capabilities.protocols import BrokerReadService
from t212ai.genai.tracing import set_trace_metadata, traceable
from t212ai.pending_actions import (
    PendingAction,
    PendingActionKind,
    PendingActionService,
    PendingActionState,
)
from t212ai.proposals import (
    ExecutionAttemptStatus,
    ProposalActionKind,
    ProposalService,
)

from .models import (
    ReconciledActionResult,
    ReconciliationOutcome,
    ReconciliationRunResult,
)

_ACTIVE_REMOTE_STATUSES = {
    BrokerOrderStatus.LOCAL,
    BrokerOrderStatus.UNCONFIRMED,
    BrokerOrderStatus.CONFIRMED,
    BrokerOrderStatus.NEW,
    BrokerOrderStatus.CANCELLING,
    BrokerOrderStatus.PENDING_CANCEL,
    BrokerOrderStatus.REPLACING,
    BrokerOrderStatus.PENDING_REPLACE,
    BrokerOrderStatus.PARTIALLY_FILLED,
    BrokerOrderStatus.DONE_FOR_DAY,
    BrokerOrderStatus.ACCEPTED,
    BrokerOrderStatus.ACCEPTED_FOR_BIDDING,
    BrokerOrderStatus.PENDING_NEW,
}


@dataclass(slots=True)
class _Resolution:
    outcome: ReconciliationOutcome
    new_state: PendingActionState
    note: str
    remote_order_ref: str | None = None
    remote_status: dict[str, Any] | None = None
    error_message: str | None = None


@dataclass(slots=True)
class ReconciliationService:
    broker_service: BrokerReadService
    broker_provider: str
    pending_action_service: PendingActionService
    proposal_service: ProposalService | None = None
    history_limit: int = 50

    @traceable(name="Reconciliation Service Run", run_type="chain")
    def reconcile_once(self, *, limit: int = 100) -> ReconciliationRunResult:
        started_at = _utc_now()
        set_trace_metadata(
            service="reconciliation",
            provider=self.broker_provider,
            history_limit=self.history_limit,
            limit=limit,
        )
        actions = self.pending_action_service.list_actions_for_reconciliation(
            limit=limit,
            broker_provider=self.broker_provider,
        )
        pending_orders = self.broker_service.list_pending_orders()
        historical_page = self.broker_service.list_historical_orders(limit=self.history_limit)
        historical_orders = list(historical_page.items)

        pending_index = {
            str(order.id): order
            for order in pending_orders
            if order.id is not None
        }
        history_index = {
            str(item.order.id): item
            for item in historical_orders
            if item.order is not None and item.order.id is not None
        }

        action_results: list[ReconciledActionResult] = []
        updated = 0
        finalized = 0
        pending = 0
        failed = 0
        unresolved = 0

        for action in actions:
            resolution = self._resolve_action(
                action,
                pending_index=pending_index,
                history_index=history_index,
                pending_orders=pending_orders,
                historical_orders=historical_orders,
            )
            previous_state = action.state
            updated_action = self.pending_action_service.apply_reconciliation(
                action.action_id,
                state=resolution.new_state,
                remote_status=resolution.remote_status,
                error_message=resolution.error_message,
            )
            if updated_action is not None:
                updated += 1
            self._sync_proposal(action, resolution)
            action_results.append(
                ReconciledActionResult(
                    action_id=action.action_id,
                    kind=action.kind,
                    previous_state=previous_state,
                    current_state=resolution.new_state,
                    outcome=resolution.outcome,
                    remote_order_ref=resolution.remote_order_ref,
                    remote_status=resolution.remote_status,
                    note=resolution.note,
                )
            )
            if resolution.outcome == ReconciliationOutcome.UNRESOLVED:
                unresolved += 1
            elif resolution.outcome == ReconciliationOutcome.PENDING:
                pending += 1
            elif resolution.outcome in {
                ReconciliationOutcome.FAILED,
                ReconciliationOutcome.REJECTED,
            }:
                failed += 1
                finalized += 1
            else:
                finalized += 1

        finished_at = _utc_now()
        return ReconciliationRunResult(
            started_at=started_at,
            finished_at=finished_at,
            scanned_actions=len(actions),
            updated_actions=updated,
            finalized_actions=finalized,
            pending_actions=pending,
            failed_actions=failed,
            unresolved_actions=unresolved,
            actions=action_results,
        )

    def _resolve_action(
        self,
        action: PendingAction,
        *,
        pending_index: dict[str, BrokerOrder],
        history_index: dict[str, BrokerHistoricalOrder],
        pending_orders: list[BrokerOrder],
        historical_orders: list[BrokerHistoricalOrder],
    ) -> _Resolution:
        if action.kind == PendingActionKind.CANCEL_ORDER:
            return self._resolve_cancel_action(
                action,
                pending_index=pending_index,
                history_index=history_index,
            )
        return self._resolve_submit_action(
            action,
            pending_index=pending_index,
            history_index=history_index,
            pending_orders=pending_orders,
            historical_orders=historical_orders,
        )

    def _resolve_submit_action(
        self,
        action: PendingAction,
        *,
        pending_index: dict[str, BrokerOrder],
        history_index: dict[str, BrokerHistoricalOrder],
        pending_orders: list[BrokerOrder],
        historical_orders: list[BrokerHistoricalOrder],
    ) -> _Resolution:
        broker_order_ref = _extract_submit_order_ref(action)
        if broker_order_ref is not None:
            if broker_order_ref in pending_index:
                order = pending_index[broker_order_ref]
                return _Resolution(
                    outcome=ReconciliationOutcome.PENDING,
                    new_state=PendingActionState.SUBMITTED,
                    remote_order_ref=broker_order_ref,
                    remote_status=_order_snapshot(order, source="pending_orders"),
                    note=f"Remote order is still active in {_display_broker_name(self.broker_provider)} pending orders.",
                )
            if broker_order_ref in history_index:
                return self._resolution_from_historical_order(
                    action,
                    history_index[broker_order_ref],
                )

        matched_order, matched_history = _match_submit_order_by_metadata(
            action,
            pending_orders=pending_orders,
            historical_orders=historical_orders,
        )
        if matched_order is not None:
            return _Resolution(
                outcome=ReconciliationOutcome.PENDING,
                new_state=PendingActionState.SUBMITTED,
                remote_order_ref=str(matched_order.id) if matched_order.id is not None else None,
                remote_status=_order_snapshot(matched_order, source="pending_orders"),
                note="Matched the remote active order by local payload metadata.",
            )
        if matched_history is not None:
            return self._resolution_from_historical_order(action, matched_history)
        return _Resolution(
            outcome=ReconciliationOutcome.UNRESOLVED,
            new_state=PendingActionState.SUBMITTED,
            note=(
                "The submitted order was not found in current pending orders or the recent "
                f"{_display_broker_name(self.broker_provider)} historical-order page. "
                "It will be checked again on the next reconciliation run."
            ),
        )

    def _resolve_cancel_action(
        self,
        action: PendingAction,
        *,
        pending_index: dict[str, BrokerOrder],
        history_index: dict[str, BrokerHistoricalOrder],
    ) -> _Resolution:
        target_order_ref = action.target_order_ref
        if target_order_ref is None:
            return _Resolution(
                outcome=ReconciliationOutcome.UNRESOLVED,
                new_state=PendingActionState.SUBMITTED,
                note="The cancel action is missing its target order reference locally.",
                error_message="Cancel action missing target order reference.",
            )
        if target_order_ref in pending_index:
            order = pending_index[target_order_ref]
            return _Resolution(
                outcome=ReconciliationOutcome.PENDING,
                new_state=PendingActionState.SUBMITTED,
                remote_order_ref=target_order_ref,
                remote_status=_order_snapshot(order, source="pending_orders"),
                note=f"The target order is still visible in {_display_broker_name(self.broker_provider)} pending orders.",
            )
        historical = history_index.get(target_order_ref)
        if historical is None or historical.order is None:
            return _Resolution(
                outcome=ReconciliationOutcome.UNRESOLVED,
                new_state=PendingActionState.SUBMITTED,
                note=(
                    "The target order is no longer pending, but a matching historical order "
                    f"was not found in recent {_display_broker_name(self.broker_provider)} history."
                ),
            )
        status = historical.order.status
        snapshot = _historical_snapshot(historical)
        remote_order_ref = str(historical.order.id) if historical.order.id is not None else None
        if status in {BrokerOrderStatus.CANCELLED, BrokerOrderStatus.REPLACED}:
            return _Resolution(
                outcome=ReconciliationOutcome.CANCELLED,
                new_state=PendingActionState.RECONCILED,
                remote_order_ref=remote_order_ref,
                remote_status=snapshot,
                note=f"The target order is finalized in {_display_broker_name(self.broker_provider)} history as cancelled/replaced.",
            )
        if status in {BrokerOrderStatus.FILLED, BrokerOrderStatus.PARTIALLY_FILLED}:
            return _Resolution(
                outcome=ReconciliationOutcome.FAILED,
                new_state=PendingActionState.FAILED,
                remote_order_ref=remote_order_ref,
                remote_status=snapshot,
                note="The order was filled before the cancellation could complete.",
                error_message="Remote order filled before cancellation completed.",
            )
        if status == BrokerOrderStatus.REJECTED:
            return _Resolution(
                outcome=ReconciliationOutcome.REJECTED,
                new_state=PendingActionState.FAILED,
                remote_order_ref=remote_order_ref,
                remote_status=snapshot,
                note=f"{_display_broker_name(self.broker_provider)} historical orders show the target order as rejected.",
                error_message=f"Remote order is rejected in {_display_broker_name(self.broker_provider)} history.",
            )
        return _Resolution(
            outcome=ReconciliationOutcome.PENDING,
            new_state=PendingActionState.SUBMITTED,
            remote_order_ref=remote_order_ref,
            remote_status=snapshot,
            note="The target order appears in historical orders but is not yet in a final terminal status.",
        )

    def _resolution_from_historical_order(
        self,
        action: PendingAction,
        historical_order: BrokerHistoricalOrder,
    ) -> _Resolution:
        order = historical_order.order
        if order is None:
            return _Resolution(
                outcome=ReconciliationOutcome.UNRESOLVED,
                new_state=PendingActionState.SUBMITTED,
                note="Historical-order payload was missing the embedded order details.",
            )
        remote_order_ref = str(order.id) if order.id is not None else None
        snapshot = _historical_snapshot(historical_order)
        status = order.status
        if status == BrokerOrderStatus.FILLED:
            return _Resolution(
                outcome=ReconciliationOutcome.FILLED,
                new_state=PendingActionState.RECONCILED,
                remote_order_ref=remote_order_ref,
                remote_status=snapshot,
                note=f"{_display_broker_name(self.broker_provider)} historical orders show the order as filled.",
            )
        if status == BrokerOrderStatus.PARTIALLY_FILLED:
            return _Resolution(
                outcome=ReconciliationOutcome.PARTIALLY_FILLED,
                new_state=PendingActionState.RECONCILED,
                remote_order_ref=remote_order_ref,
                remote_status=snapshot,
                note=f"{_display_broker_name(self.broker_provider)} historical orders show the order as partially filled.",
            )
        if status in {BrokerOrderStatus.CANCELLED, BrokerOrderStatus.REPLACED}:
            return _Resolution(
                outcome=ReconciliationOutcome.CANCELLED,
                new_state=PendingActionState.CANCELLED,
                remote_order_ref=remote_order_ref,
                remote_status=snapshot,
                note=f"{_display_broker_name(self.broker_provider)} historical orders show the order as cancelled/replaced.",
            )
        if status == BrokerOrderStatus.REJECTED:
            return _Resolution(
                outcome=ReconciliationOutcome.REJECTED,
                new_state=PendingActionState.FAILED,
                remote_order_ref=remote_order_ref,
                remote_status=snapshot,
                note=f"{_display_broker_name(self.broker_provider)} historical orders show the order as rejected.",
                error_message=f"Remote order is rejected in {_display_broker_name(self.broker_provider)} history.",
            )
        if status in _ACTIVE_REMOTE_STATUSES:
            return _Resolution(
                outcome=ReconciliationOutcome.PENDING,
                new_state=PendingActionState.SUBMITTED,
                remote_order_ref=remote_order_ref,
                remote_status=snapshot,
                note=f"{_display_broker_name(self.broker_provider)} historical orders still show the order as active.",
            )
        return _Resolution(
            outcome=ReconciliationOutcome.UNRESOLVED,
            new_state=PendingActionState.SUBMITTED,
            remote_order_ref=remote_order_ref,
            remote_status=snapshot,
            note="Remote order status could not be mapped during reconciliation.",
        )

    def _sync_proposal(self, action: PendingAction, resolution: _Resolution) -> None:
        if self.proposal_service is None or action.kind != PendingActionKind.SUBMIT_ORDER:
            return
        proposal = self.proposal_service.get_by_pending_action_id(action.action_id)
        if proposal is None:
            return
        current_broker_order_ref = resolution.remote_order_ref or _extract_submit_order_ref(action)
        remote_status = resolution.remote_status
        if resolution.outcome == ReconciliationOutcome.UNRESOLVED:
            return
        if resolution.outcome == ReconciliationOutcome.PENDING:
            self.proposal_service.sync_execution_attempt(
                proposal_id=proposal.proposal_id,
                pending_action_id=action.action_id,
                broker_provider=action.broker_provider,
                action_kind=ProposalActionKind.SUBMIT_ORDER,
                status=ExecutionAttemptStatus.PENDING,
                broker_order_ref=current_broker_order_ref,
                remote_status=remote_status,
            )
            self.proposal_service.mark_submitted(proposal.proposal_id)
            return
        if resolution.outcome in {
            ReconciliationOutcome.FILLED,
            ReconciliationOutcome.PARTIALLY_FILLED,
        }:
            target_status = (
                ExecutionAttemptStatus.FILLED
                if resolution.outcome == ReconciliationOutcome.FILLED
                else ExecutionAttemptStatus.PARTIALLY_FILLED
            )
            self.proposal_service.sync_execution_attempt(
                proposal_id=proposal.proposal_id,
                pending_action_id=action.action_id,
                broker_provider=action.broker_provider,
                action_kind=ProposalActionKind.SUBMIT_ORDER,
                status=target_status,
                broker_order_ref=current_broker_order_ref,
                remote_status=remote_status,
            )
            self.proposal_service.mark_reconciled(proposal.proposal_id)
            return
        if resolution.outcome == ReconciliationOutcome.CANCELLED:
            self.proposal_service.sync_execution_attempt(
                proposal_id=proposal.proposal_id,
                pending_action_id=action.action_id,
                broker_provider=action.broker_provider,
                action_kind=ProposalActionKind.SUBMIT_ORDER,
                status=ExecutionAttemptStatus.CANCELLED,
                broker_order_ref=current_broker_order_ref,
                remote_status=remote_status,
                error_message=resolution.note,
            )
            self.proposal_service.mark_cancelled(
                proposal.proposal_id,
                reason=resolution.note,
            )
            return
        if resolution.outcome in {ReconciliationOutcome.REJECTED, ReconciliationOutcome.FAILED}:
            target_status = (
                ExecutionAttemptStatus.REJECTED
                if resolution.outcome == ReconciliationOutcome.REJECTED
                else ExecutionAttemptStatus.FAILED
            )
            self.proposal_service.sync_execution_attempt(
                proposal_id=proposal.proposal_id,
                pending_action_id=action.action_id,
                broker_provider=action.broker_provider,
                action_kind=ProposalActionKind.SUBMIT_ORDER,
                status=target_status,
                broker_order_ref=current_broker_order_ref,
                remote_status=remote_status,
                error_message=resolution.error_message or resolution.note,
            )
            self.proposal_service.mark_execution_failed(
                proposal.proposal_id,
                error=resolution.error_message or resolution.note,
            )


def _match_submit_order_by_metadata(
    action: PendingAction,
    *,
    pending_orders: list[BrokerOrder],
    historical_orders: list[BrokerHistoricalOrder],
) -> tuple[BrokerOrder | None, BrokerHistoricalOrder | None]:
    pending_matches = [
        order
        for order in pending_orders
        if _order_matches_action(action, order)
    ]
    if len(pending_matches) == 1:
        return pending_matches[0], None
    historical_matches = [
        item
        for item in historical_orders
        if item.order is not None and _order_matches_action(action, item.order)
    ]
    if len(historical_matches) == 1:
        return None, historical_matches[0]
    return None, None


def _order_matches_action(action: PendingAction, order: BrokerOrder) -> bool:
    if order.id is None:
        return False
    payload = action.prepared_order_payload or {}
    request_payload = payload.get("requestPayload") if isinstance(payload, dict) else None
    order_ticker = _payload_value(payload, "ticker")
    order_type = _payload_value(payload, "orderType")
    side = _payload_value(payload, "side")
    signed_quantity = _payload_value(payload, "signedQuantity")

    if order_ticker and str(order.ticker or "").upper() != str(order_ticker).upper():
        return False
    if order_type and getattr(order.type, "value", order.type) != str(order_type).upper():
        return False
    if side and getattr(order.side, "value", order.side) != str(side).upper():
        return False
    if signed_quantity is not None and order.quantity is not None:
        if not _decimal_equal(abs(order.quantity), abs(_to_decimal(signed_quantity) or Decimal("0"))):
            return False
    if isinstance(request_payload, dict):
        client_order_id = _payload_value(request_payload, "client_order_id")
        if client_order_id is not None:
            remote_client_order_id = None
            if isinstance(order.raw_provider_payload, dict):
                remote_client_order_id = _payload_value(order.raw_provider_payload, "client_order_id")
            if remote_client_order_id is not None and str(remote_client_order_id).strip() != str(client_order_id).strip():
                return False
        limit_price = _payload_value(request_payload, "limitPrice")
        stop_price = _payload_value(request_payload, "stopPrice")
        if limit_price is not None and order.limit_price is not None:
            if not _decimal_equal(order.limit_price, _to_decimal(limit_price)):
                return False
        if stop_price is not None and order.stop_price is not None:
            if not _decimal_equal(order.stop_price, _to_decimal(stop_price)):
                return False
    if action.created_at and order.created_at:
        if abs(order.created_at - action.created_at) > timedelta(hours=6):
            return False
    return True


def _extract_submit_order_ref(action: PendingAction) -> str | None:
    payload = action.broker_result or {}
    if not isinstance(payload, dict):
        return None
    for key in ("order_id", "orderId"):
        if key in payload and payload.get(key) is not None:
            return str(payload.get(key)).strip() or None
    order = payload.get("order")
    if isinstance(order, dict):
        for key in ("id", "order_id", "orderId"):
            if key in order and order.get(key) is not None:
                return str(order.get(key)).strip() or None
    return None


def _historical_snapshot(item: BrokerHistoricalOrder) -> dict[str, Any]:
    payload: dict[str, Any] = {"source": "history_orders"}
    if item.order is not None:
        payload["order"] = item.order.model_dump(mode="json", by_alias=True, exclude_none=True)
    if item.fill is not None:
        payload["fill"] = item.fill.model_dump(mode="json", by_alias=True, exclude_none=True)
    return payload


def _order_snapshot(order: BrokerOrder, *, source: str) -> dict[str, Any]:
    payload = order.model_dump(mode="json", by_alias=True, exclude_none=True)
    payload["source"] = source
    return payload


def _payload_value(payload: dict[str, Any] | None, key: str) -> Any:
    if not isinstance(payload, dict):
        return None
    candidates = {
        key,
        key[:1].lower() + key[1:],
        key[:1].upper() + key[1:],
        _camel_to_snake(key),
    }
    for candidate in candidates:
        if candidate in payload:
            return payload.get(candidate)
    return None


def _camel_to_snake(value: str) -> str:
    chars: list[str] = []
    for index, char in enumerate(value):
        if char.isupper() and index > 0:
            chars.append("_")
        chars.append(char.lower())
    return "".join(chars)


def _decimal_equal(left: Decimal | None, right: Decimal | None) -> bool:
    if left is None or right is None:
        return left == right
    return left == right


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _display_broker_name(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized == "trading212":
        return "Trading 212"
    if normalized == "alpaca":
        return "Alpaca"
    return str(provider or "broker").replace("_", " ").strip().title() or "Broker"
