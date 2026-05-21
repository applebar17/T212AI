"""Runtime context for Trading 212 tools."""

from __future__ import annotations

from dataclasses import dataclass

from t212ai.pending_actions import PendingActionService

from ..protocols import Trading212AgentBrokerProtocol


@dataclass(slots=True)
class Trading212ToolRuntime:
    service: Trading212AgentBrokerProtocol
    allow_state_changes: bool = False
    pending_action_service: PendingActionService | None = None
    chat_id: str | None = None
    user_id: int | None = None
    user_message: str | None = None
