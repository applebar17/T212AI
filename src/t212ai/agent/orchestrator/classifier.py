"""Compatibility fallback intent classification for pre-runtime paths."""

from __future__ import annotations

import re

from ..intents import AgentIntent, IntentKind


class AgentOrchestrator:
    """Compatibility fallback classifier used before the full agent runtime is wired."""

    def classify_fallback(self, message: str) -> AgentIntent:
        return classify_message(message)

def classify_message(message: str) -> AgentIntent:
    text = message.strip().lower()
    if text in {"/help", "help"}:
        return AgentIntent(kind=IntentKind.HELP, confidence=1.0)
    guideline_intent = _classify_guideline_message(text)
    if guideline_intent is not None:
        return guideline_intent
    scheduler_lifecycle_intent = _classify_scheduler_message(text)
    if scheduler_lifecycle_intent is not None and any(
        word in text for word in ("alert", "monitor", "schedule", "scheduler")
    ):
        return scheduler_lifecycle_intent
    if any(word in text for word in ("cancel", "order status")):
        return AgentIntent(kind=IntentKind.CANCEL_ORDER, confidence=0.85)
    if any(word in text for word in ("pending order", "orders", "open order")):
        return AgentIntent(kind=IntentKind.REVIEW_PENDING_ORDERS, confidence=0.8)
    if _is_explicit_order_execution_request(text):
        return AgentIntent(
            kind=IntentKind.PLACE_ORDER,
            entities={"action": "liquidate" if "liquidate" in text or "close" in text or "exit" in text else "submit_order"},
            confidence=0.9,
        )
    if any(word in text for word in ("buy", "sell", "place order", "trade")):
        return AgentIntent(kind=IntentKind.PROPOSE_TRADE, confidence=0.8)
    scheduler_intent = scheduler_lifecycle_intent or _classify_scheduler_message(text)
    if scheduler_intent is not None:
        return scheduler_intent
    has_digit = any(char.isdigit() for char in text)
    has_operator = any(symbol in text for symbol in ("+", "-", "*", "/", "^", "%"))
    if "calculate" in text or (has_digit and has_operator) or ("what is" in text and has_digit):
        return AgentIntent(kind=IntentKind.CALCULATE, confidence=0.7)
    if any(word in text for word in ("portfolio", "position", "holding", "allocation")):
        return AgentIntent(kind=IntentKind.PORTFOLIO_SUMMARY, confidence=0.8)
    if any(word in text for word in ("attention", "risk", "exposure", "rebalance")):
        return AgentIntent(kind=IntentKind.PORTFOLIO_ATTENTION_SCAN, confidence=0.82)
    if any(
        phrase in text
        for phrase in (
            "reddit",
            "social sentiment",
            "community sentiment",
            "social analysis",
            "wallstreetbets",
        )
    ):
        return AgentIntent(kind=IntentKind.SOCIAL_RESEARCH, confidence=0.82)
    if any(word in text for word in ("market", "macro", "commodity", "gainers", "losers")):
        return AgentIntent(kind=IntentKind.UNKNOWN, entities={"domain": "market"}, confidence=0.55)
    if any(word in text for word in ("analyze", "company", "ticker", "earnings", "analyst")):
        return AgentIntent(kind=IntentKind.ANALYZE_INSTRUMENT, confidence=0.75)
    return AgentIntent(kind=IntentKind.UNKNOWN, entities={"message": message}, confidence=0.0)


def _classify_scheduler_message(text: str) -> AgentIntent | None:
    has_scheduler_action = any(
        phrase in text
        for phrase in (
            "alert me",
            "notify me",
            "monitor",
            "watch ",
            "schedule",
            "scheduled process",
            "scheduler",
            "pause alert",
            "resume alert",
            "archive alert",
            "stop alert",
            "pause monitor",
            "resume monitor",
            "archive monitor",
            "stop monitor",
        )
    )
    has_trigger_language = any(
        phrase in text
        for phrase in (
            "goes below",
            "goes above",
            "drops below",
            "rises above",
            "breaks below",
            "breaks above",
            "reaches",
            "hits",
            "all time low",
            "monthly low",
            "monthly high",
            "period low",
            "period high",
        )
    )
    has_lifecycle_word = any(
        phrase in text
        for phrase in (
            "pause alert",
            "resume alert",
            "archive alert",
            "cancel alert",
            "pause monitor",
            "resume monitor",
            "archive monitor",
            "cancel monitor",
            "pause sched_",
            "resume sched_",
            "archive sched_",
        )
    )
    if has_scheduler_action or has_lifecycle_word or (
        has_trigger_language
        and any(word in text for word in ("alert", "notify", "monitor", "watch", "schedule"))
    ):
        return AgentIntent(
            kind=IntentKind.MANAGE_SCHEDULED_PROCESSES,
            entities={"domain": "scheduler"},
            confidence=0.82,
        )
    return None


def _entities_to_items(intent: AgentIntent) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for key, value in intent.entities.items():
        normalized_key = str(key).strip()
        normalized_value = str(value).strip()
        if normalized_key and normalized_value:
            items.append({"key": normalized_key, "value": normalized_value})
    return items


def _classify_guideline_message(text: str) -> AgentIntent | None:
    if any(
        phrase in text
        for phrase in (
            "remember that",
            "remember this",
            "save this preference",
            "save this rule",
            "add a rule",
            "add guideline",
            "create guideline",
        )
    ):
        return AgentIntent(
            kind=IntentKind.MANAGE_GUIDELINES,
            entities={"operation": "create"},
            confidence=0.9,
        )
    if any(
        phrase in text
        for phrase in (
            "update my preference",
            "update guideline",
            "update rule",
            "change my preference",
        )
    ):
        return AgentIntent(
            kind=IntentKind.MANAGE_GUIDELINES,
            entities={"operation": "update"},
            confidence=0.88,
        )
    if any(
        phrase in text
        for phrase in (
            "forget that",
            "forget this",
            "archive guideline",
            "archive rule",
            "remove this rule",
        )
    ):
        return AgentIntent(
            kind=IntentKind.MANAGE_GUIDELINES,
            entities={"operation": "archive"},
            confidence=0.88,
        )
    if any(
        phrase in text
        for phrase in (
            "delete guideline",
            "delete rule permanently",
            "permanently delete",
        )
    ):
        return AgentIntent(
            kind=IntentKind.MANAGE_GUIDELINES,
            entities={"operation": "delete"},
            confidence=0.92,
        )
    if any(
        phrase in text
        for phrase in (
            "list saved rules",
            "list guidelines",
            "show saved guidelines",
            "show my saved rules",
        )
    ):
        return AgentIntent(
            kind=IntentKind.MANAGE_GUIDELINES,
            entities={"operation": "list"},
            confidence=0.85,
        )
    if any(
        phrase in text
        for phrase in (
            "render guidelines",
            "show guideline markdown",
            "preview guideline render",
        )
    ):
        return AgentIntent(
            kind=IntentKind.MANAGE_GUIDELINES,
            entities={"operation": "render"},
            confidence=0.85,
        )
    return None


def _is_explicit_order_execution_request(text: str) -> bool:
    patterns = (
        r"^\s*(buy|sell)\b",
        r"^\s*can you\s+(buy|sell|liquidate|close|exit)\b",
        r"\b(i want to|please|go ahead and)\s+(buy|sell|liquidate|close|exit)\b",
        r"\b(liquidate|fully liquidate|close my position|close the position|close position)\b",
        r"\b(exit my position|exit the position|exit position|sell all|fully close)\b",
        r"\b(place order|market order|limit order)\b",
        r"\b(at market|at mkt|market price)\b",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def _metadata_user_id(metadata: dict[str, str]) -> int | None:
    raw = str(metadata.get("user_id") or metadata.get("userId") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None
