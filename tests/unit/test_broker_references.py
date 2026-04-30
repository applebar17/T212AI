from __future__ import annotations

import pytest

from t212ai.brokers.references import (
    BrokerReferenceKind,
    BrokerReferenceMap,
    UnknownBrokerPublicReference,
)


def test_reference_map_reuses_alias_for_same_true_ref() -> None:
    reference_map = BrokerReferenceMap()

    first = reference_map.register(
        BrokerReferenceKind.ORDER,
        provider="trading212",
        true_ref="abc-123",
    )
    second = reference_map.register(
        BrokerReferenceKind.ORDER,
        provider="trading212",
        true_ref="abc-123",
    )

    assert first == "ORDER_000001"
    assert second == first


def test_reference_map_uses_independent_counters_per_kind() -> None:
    reference_map = BrokerReferenceMap()

    order_ref = reference_map.register(
        BrokerReferenceKind.ORDER,
        provider="trading212",
        true_ref="order-1",
    )
    position_ref = reference_map.register(
        BrokerReferenceKind.POSITION,
        provider="trading212",
        true_ref="position-1",
    )

    assert order_ref == "ORDER_000001"
    assert position_ref == "POSITION_000001"


def test_reference_map_separates_providers() -> None:
    reference_map = BrokerReferenceMap()

    t212_ref = reference_map.register(
        BrokerReferenceKind.ORDER,
        provider="trading212",
        true_ref="same-id",
    )
    alpaca_ref = reference_map.register(
        BrokerReferenceKind.ORDER,
        provider="alpaca",
        true_ref="same-id",
    )

    assert t212_ref == "ORDER_000001"
    assert alpaca_ref == "ORDER_000002"
    assert (
        reference_map.resolve(
            BrokerReferenceKind.ORDER,
            t212_ref,
            provider="trading212",
        ).true_ref
        == "same-id"
    )
    with pytest.raises(UnknownBrokerPublicReference):
        reference_map.resolve(BrokerReferenceKind.ORDER, t212_ref, provider="alpaca")


def test_reference_map_rejects_unknown_alias() -> None:
    reference_map = BrokerReferenceMap()

    with pytest.raises(UnknownBrokerPublicReference):
        reference_map.resolve(BrokerReferenceKind.ORDER, "ORDER_000001")


def test_new_reference_map_restarts_numbering() -> None:
    first_map = BrokerReferenceMap()
    second_map = BrokerReferenceMap()

    assert (
        first_map.register(
            BrokerReferenceKind.ORDER,
            provider="trading212",
            true_ref="order-1",
        )
        == "ORDER_000001"
    )
    assert (
        second_map.register(
            BrokerReferenceKind.ORDER,
            provider="trading212",
            true_ref="order-2",
        )
        == "ORDER_000001"
    )
