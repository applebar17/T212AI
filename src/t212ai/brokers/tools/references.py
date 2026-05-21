"""Public-reference mapping helpers for broker tool outputs."""

from __future__ import annotations

from typing import Any

from t212ai.genai.models import ToolResult

from ..models import BrokerOrder
from ..references import (
    BrokerReferenceKind,
    BrokerReferenceMap,
    UnknownBrokerPublicReference,
)
from .errors import _tool_error
from .runtime import BrokerToolRuntime


def _reference_map(runtime: BrokerToolRuntime) -> BrokerReferenceMap:
    if runtime.reference_map is None:
        runtime.reference_map = BrokerReferenceMap()
    return runtime.reference_map


def _resolve_order_ref(
    order_ref: str | None,
    *,
    runtime: BrokerToolRuntime,
) -> str | None | ToolResult:
    if order_ref is None:
        return None
    raw = str(order_ref).strip()
    if not raw:
        return None
    if _looks_like_public_ref(raw, BrokerReferenceKind.ORDER):
        try:
            return _reference_map(runtime).resolve(
                BrokerReferenceKind.ORDER,
                raw,
                provider=runtime.broker_provider,
            ).true_ref
        except UnknownBrokerPublicReference:
            return _unknown_public_reference_error(
                raw,
                kind=BrokerReferenceKind.ORDER,
            )
    return raw


def _looks_like_public_ref(value: str | None, kind: BrokerReferenceKind) -> bool:
    raw = str(value or "").strip().upper()
    return raw.startswith(f"{kind.value}_")


def _unknown_public_reference_error(
    public_ref: str,
    *,
    kind: BrokerReferenceKind,
) -> ToolResult:
    return _tool_error(
        f"Unknown {kind.value.lower()} public reference {public_ref!r}.",
        code="unknown_public_reference",
        hint=(
            "Call broker_list_pending_orders again for order references, or "
            "broker_get_portfolio_snapshot again for position references. "
            "Public references are scoped to one agent interaction and are not durable."
        ),
        details={"kind": kind.value, "public_ref": public_ref},
    )


def _register_order_public_ref(
    order: BrokerOrder,
    *,
    runtime: BrokerToolRuntime,
    fallback_true_ref: str | None = None,
) -> str | None:
    true_ref = _order_true_ref(order) or _non_empty_str(fallback_true_ref)
    if true_ref is None:
        return None
    return _reference_map(runtime).register(
        BrokerReferenceKind.ORDER,
        provider=runtime.broker_provider,
        true_ref=true_ref,
    )


def _dump_order_with_public_ref(
    order: BrokerOrder,
    *,
    runtime: BrokerToolRuntime,
    fallback_true_ref: str | None = None,
) -> dict[str, Any]:
    payload = order.model_dump(by_alias=True, exclude_none=True, mode="json")
    true_ref = _order_true_ref(order) or _non_empty_str(fallback_true_ref)
    if true_ref is not None:
        payload["brokerOrderRef"] = true_ref
        public_ref = _register_order_public_ref(
            order,
            runtime=runtime,
            fallback_true_ref=true_ref,
        )
        if public_ref is not None:
            payload["publicOrderRef"] = public_ref
    return payload


def _dump_snapshot_with_public_refs(snapshot, *, runtime: BrokerToolRuntime) -> dict[str, Any]:
    payload = snapshot.model_dump(by_alias=True, exclude_none=True, mode="json")
    positions_payload = payload.get("positions")
    if isinstance(positions_payload, list):
        for index, position in enumerate(snapshot.positions):
            public_ref = _register_position_public_ref(
                position,
                index=index,
                runtime=runtime,
            )
            if public_ref is not None and index < len(positions_payload):
                positions_payload[index]["publicPositionRef"] = public_ref
            broker_position_ref = _native_position_ref(position)
            if broker_position_ref is not None and index < len(positions_payload):
                positions_payload[index]["brokerPositionRef"] = broker_position_ref

    pending_orders_payload = payload.get("pendingOrders")
    if isinstance(pending_orders_payload, list):
        for index, order in enumerate(snapshot.pending_orders):
            if index >= len(pending_orders_payload):
                continue
            pending_orders_payload[index].update(
                _dump_order_with_public_ref(order, runtime=runtime)
            )
    return payload


def _register_position_public_ref(
    position,
    *,
    index: int,
    runtime: BrokerToolRuntime,
) -> str | None:
    true_ref = _position_true_ref(position, index=index, provider=runtime.broker_provider)
    if true_ref is None:
        return None
    return _reference_map(runtime).register(
        BrokerReferenceKind.POSITION,
        provider=runtime.broker_provider,
        true_ref=true_ref,
    )


def _order_true_ref(order: BrokerOrder) -> str | None:
    return _non_empty_str(order.id)


def _position_true_ref(position, *, index: int, provider: str) -> str | None:
    native_ref = _native_position_ref(position)
    if native_ref is not None:
        return native_ref
    instrument = getattr(position, "instrument", None)
    ticker = _non_empty_str(getattr(instrument, "ticker", None)) if instrument else None
    isin = _non_empty_str(getattr(instrument, "isin", None)) if instrument else None
    name = _non_empty_str(getattr(instrument, "name", None)) if instrument else None
    currency = _non_empty_str(getattr(instrument, "currency", None)) if instrument else None
    if any((ticker, isin, name, currency)):
        return (
            f"derived-position:{provider}:"
            f"ticker={ticker or ''}:isin={isin or ''}:name={name or ''}:currency={currency or ''}"
        )
    return f"derived-position:{provider}:index={index}"


def _native_position_ref(position) -> str | None:
    for attr in ("id", "position_id", "positionId"):
        value = getattr(position, attr, None)
        if value is not None:
            resolved = _non_empty_str(value)
            if resolved is not None:
                return resolved
    raw_payload = getattr(position, "raw_provider_payload", None)
    if isinstance(raw_payload, dict):
        for key in ("id", "position_id", "positionId"):
            resolved = _non_empty_str(raw_payload.get(key))
            if resolved is not None:
                return resolved
    return None


def _non_empty_str(value: Any) -> str | None:
    raw = str(value or "").strip()
    return raw or None
