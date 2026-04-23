"""Top-level agent orchestration placeholder."""

from __future__ import annotations

from .intents import AgentIntent, IntentKind


class AgentOrchestrator:
    """Coordinates intent routing, tool planning, policy checks, and responses."""

    def classify_fallback(self, message: str) -> AgentIntent:
        text = message.strip().lower()
        if text in {"/help", "help"}:
            return AgentIntent(kind=IntentKind.HELP, confidence=1.0)
        return AgentIntent(kind=IntentKind.UNKNOWN, entities={"message": message}, confidence=0.0)

