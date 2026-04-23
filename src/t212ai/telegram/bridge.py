"""Telegram-to-agent bridge handlers."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeAlias

from t212ai.agent.history import ChatHistoryManager
from t212ai.agent.intents import IntentKind
from t212ai.agent.orchestrator import AgentOrchestrator, MainOrchestratorAgent
from t212ai.agent.reasoning import AgentReasoner
from t212ai.agent.schemas import AgentRequest

from .auth import TelegramAccessPolicy
from .commands import HELP_COMMANDS, render_help_text
from .messenger import TelegramMessenger
from .models import (
    TelegramInboundMessage,
    TelegramOutboundMessage,
    inbound_from_update,
)

TelegramMessageHandler: TypeAlias = Callable[
    [TelegramInboundMessage],
    TelegramOutboundMessage | str | None | Awaitable[TelegramOutboundMessage | str | None],
]


@dataclass(slots=True)
class TelegramUpdateRouter:
    access_policy: TelegramAccessPolicy
    message_handler: TelegramMessageHandler

    async def handle_update(self, update: Any, context: Any) -> None:
        await _acknowledge_callback(update)
        inbound = inbound_from_update(update)
        if inbound is None:
            return
        messenger = TelegramMessenger(context.bot)
        if not self.access_policy.is_allowed(inbound.chat_id):
            if not self.access_policy.silent_unauthorized:
                await messenger.send_error(
                    inbound.chat_id,
                    "This chat is not authorized to use this bot.",
                    hint="Set TELEGRAM_ALLOWED_CHAT_ID to this chat id if this is expected.",
                )
            return

        try:
            response = await _resolve_response(self.message_handler(inbound))
        except Exception as exc:  # pragma: no cover - safety net
            await messenger.send_error(
                inbound.chat_id,
                f"Telegram bridge failed while processing the message: {exc}",
                hint="Retry the request. If it keeps failing, inspect application logs.",
            )
            return

        if response is None:
            return
        outbound = (
            response
            if isinstance(response, TelegramOutboundMessage)
            else TelegramOutboundMessage(text=str(response))
        )
        if outbound.reply_to_message_id is None:
            outbound = TelegramOutboundMessage(
                text=outbound.text,
                parse_mode=outbound.parse_mode,
                reply_to_message_id=inbound.message_id,
                disable_web_page_preview=outbound.disable_web_page_preview,
            )
        await messenger.send_message(inbound.chat_id, outbound)


def build_default_message_handler(
    orchestrator: AgentOrchestrator | None = None,
    *,
    main_agent: MainOrchestratorAgent | None = None,
    history_manager: ChatHistoryManager | None = None,
) -> TelegramMessageHandler:
    resolved_orchestrator = orchestrator or AgentOrchestrator()
    resolved_history = history_manager or ChatHistoryManager()

    if main_agent is not None:

        def _agent_handle(message: TelegramInboundMessage) -> TelegramOutboundMessage:
            if message.text.strip().lower() in {"/help", "help"}:
                resolved_history.record_user_message(message.chat_id, message.text)
                response = TelegramOutboundMessage(text=render_help_text())
                resolved_history.record_assistant_message(message.chat_id, response.text)
                return response

            history = resolved_history.get_context_window(message.chat_id)
            request = AgentRequest(
                user_message=message.text,
                chat_id=str(message.chat_id),
                trigger_type="telegram_user",
                history=history,
                metadata={"telegram_message_id": str(message.message_id or "")},
            )
            resolved_history.record_user_message(message.chat_id, message.text)
            agent_response = main_agent.handle(request)
            resolved_history.record_assistant_message(
                message.chat_id,
                agent_response.final_answer,
                metadata={"selected_agent": agent_response.selected_agent},
            )
            return TelegramOutboundMessage(text=agent_response.final_answer)

        return _agent_handle

    def _handle(message: TelegramInboundMessage) -> TelegramOutboundMessage:
        intent = resolved_orchestrator.classify_fallback(message.text)
        if intent.kind == IntentKind.HELP:
            return TelegramOutboundMessage(text=render_help_text())
        return TelegramOutboundMessage(
            text=(
                "I received your message, but the agent runtime is not wired yet.\n\n"
                f"Detected intent: {intent.kind.value}.\n"
                "Available baseline commands:\n"
                f"{', '.join(HELP_COMMANDS)}"
            )
        )

    return _handle


def build_agent_message_handler_if_configured(
    *,
    history_manager: ChatHistoryManager | None = None,
) -> TelegramMessageHandler:
    try:
        from t212ai.genai.client import GenAIClient

        reasoner = AgentReasoner(GenAIClient())
    except RuntimeError:
        return build_default_message_handler(history_manager=history_manager)

    return build_default_message_handler(
        main_agent=MainOrchestratorAgent(reasoner),
        history_manager=history_manager,
    )


async def _resolve_response(
    value: TelegramOutboundMessage | str | None | Awaitable[TelegramOutboundMessage | str | None],
) -> TelegramOutboundMessage | str | None:
    if inspect.isawaitable(value):
        return await value
    return value


async def _acknowledge_callback(update: Any) -> None:
    callback_query = getattr(update, "callback_query", None)
    answer = getattr(callback_query, "answer", None) if callback_query else None
    if answer is None:
        return
    result = answer()
    if inspect.isawaitable(result):
        await result
