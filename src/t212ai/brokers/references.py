"""Broker public references for LLM-facing order and position handles."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re


MAX_PUBLIC_REFERENCE_NUMBER = 999_999
PUBLIC_REFERENCE_RE = re.compile(r"^(ORDER|POSITION)_(\d{6})$")


class BrokerReferenceKind(StrEnum):
    ORDER = "ORDER"
    POSITION = "POSITION"


@dataclass(frozen=True, slots=True)
class ResolvedBrokerReference:
    kind: BrokerReferenceKind
    provider: str
    true_ref: str
    public_ref: str


class UnknownBrokerPublicReference(ValueError):
    def __init__(self, public_ref: str, *, kind: BrokerReferenceKind | None = None) -> None:
        self.public_ref = str(public_ref or "").strip()
        self.kind = kind
        label = kind.value if kind is not None else "broker"
        super().__init__(f"Unknown {label.lower()} public reference {self.public_ref!r}.")


@dataclass(slots=True)
class BrokerReferenceMap:
    """In-memory alias map scoped to one agent/tool interaction."""

    _true_to_public: dict[tuple[BrokerReferenceKind, str, str], str] = field(
        default_factory=dict
    )
    _public_to_true: dict[tuple[BrokerReferenceKind, str], tuple[str, str]] = field(
        default_factory=dict
    )
    _counters: dict[BrokerReferenceKind, int] = field(default_factory=dict)

    def register(
        self,
        kind: BrokerReferenceKind,
        *,
        provider: str,
        true_ref: str,
    ) -> str:
        resolved_kind = BrokerReferenceKind(kind)
        resolved_provider = _normalize_provider(provider)
        resolved_true_ref = _normalize_ref(true_ref)
        key = (resolved_kind, resolved_provider, resolved_true_ref)
        existing = self._true_to_public.get(key)
        if existing is not None:
            return existing
        public_ref = self._next_public_ref(resolved_kind)
        self._true_to_public[key] = public_ref
        self._public_to_true[(resolved_kind, public_ref)] = (
            resolved_provider,
            resolved_true_ref,
        )
        return public_ref

    def resolve(
        self,
        kind: BrokerReferenceKind,
        public_ref: str,
        *,
        provider: str | None = None,
    ) -> ResolvedBrokerReference:
        resolved_kind = BrokerReferenceKind(kind)
        normalized_public_ref = normalize_public_reference(public_ref)
        value = self._public_to_true.get((resolved_kind, normalized_public_ref))
        if value is None:
            raise UnknownBrokerPublicReference(normalized_public_ref, kind=resolved_kind)
        resolved_provider, true_ref = value
        if provider is not None and resolved_provider != _normalize_provider(provider):
            raise UnknownBrokerPublicReference(normalized_public_ref, kind=resolved_kind)
        return ResolvedBrokerReference(
            kind=resolved_kind,
            provider=resolved_provider,
            true_ref=true_ref,
            public_ref=normalized_public_ref,
        )

    def _next_public_ref(self, kind: BrokerReferenceKind) -> str:
        next_value = self._counters.get(kind, 0) + 1
        if next_value > MAX_PUBLIC_REFERENCE_NUMBER:
            raise OverflowError(
                f"{kind.value} public reference limit exceeded "
                f"({MAX_PUBLIC_REFERENCE_NUMBER})."
            )
        self._counters[kind] = next_value
        return f"{kind.value}_{next_value:06d}"


def is_public_reference(value: str | None, *, kind: BrokerReferenceKind | None = None) -> bool:
    raw = str(value or "").strip().upper()
    match = PUBLIC_REFERENCE_RE.match(raw)
    if match is None:
        return False
    if kind is None:
        return True
    return match.group(1) == BrokerReferenceKind(kind).value


def normalize_public_reference(value: str) -> str:
    raw = str(value or "").strip().upper()
    if not PUBLIC_REFERENCE_RE.match(raw):
        raise UnknownBrokerPublicReference(raw or str(value))
    return raw


def _normalize_provider(value: str | None) -> str:
    return str(value or "broker").strip().lower() or "broker"


def _normalize_ref(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("true_ref is required.")
    return raw
