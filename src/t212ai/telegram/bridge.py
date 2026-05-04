"""Telegram-to-agent bridge handlers."""

from __future__ import annotations

import inspect
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeAlias

from t212ai.agent.history import ChatHistoryManager
from t212ai.agent.intents import IntentKind
from t212ai.agent.orchestrator import AgentOrchestrator, MainOrchestratorAgent
from t212ai.agent.schemas import AgentRequest
from t212ai.app.runtime import AppRuntime, build_runtime
from t212ai.genai.tracing import (
    _trace_telegram_update_inputs,
    _trace_telegram_update_outputs,
    set_trace_metadata,
    set_trace_name,
    traceable,
)
from t212ai.pending_actions import (
    PendingActionDecisionResult,
    PendingActionDecisionStatus,
    PendingActionService,
)
from t212ai.proposals import (
    ApprovalDecision,
    ApprovalSource,
    ExecutionAttemptStatus,
    ProposalActionKind,
    ProposalService,
)

from .auth import TelegramAccessPolicy
from .commands import (
    HELP_COMMANDS,
    render_help_text,
    render_proposal_detail_text,
    render_recent_proposals_text,
)
from .messenger import TelegramMessenger
from .models import (
    TelegramApprovalRequest,
    TelegramInboundMessage,
    TelegramOutboundMessage,
    inbound_from_update,
)

TelegramMessageHandler: TypeAlias = Callable[
    [TelegramInboundMessage],
    TelegramApprovalRequest
    | TelegramOutboundMessage
    | str
    | None
    | Awaitable[TelegramApprovalRequest | TelegramOutboundMessage | str | None],
]


@dataclass(slots=True)
class TelegramUpdateRouter:
    access_policy: TelegramAccessPolicy
    message_handler: TelegramMessageHandler
    history_manager: ChatHistoryManager | None = None
    pending_action_service: PendingActionService | None = None
    proposal_service: ProposalService | None = None

    @traceable(
        name="telegram.request",
        run_type="chain",
        process_inputs=_trace_telegram_update_inputs,
        process_outputs=_trace_telegram_update_outputs,
    )
    async def handle_update(self, update: Any, context: Any) -> None:
        await _acknowledge_callback(update)
        inbound = inbound_from_update(update)
        if inbound is None:
            set_trace_name("telegram.request.ignored")
            set_trace_metadata(
                agent_step="telegram_request",
                step_kind="chain",
                route="ignored",
            )
            return
        set_trace_name("telegram.request")
        set_trace_metadata(
            agent_step="telegram_request",
            step_kind="chain",
            route="telegram",
            session_id=f"telegram:{inbound.chat_id}",
            thread_id=f"telegram:{inbound.chat_id}",
            conversation_id=f"telegram:{inbound.chat_id}",
            chat_id=str(inbound.chat_id),
            user_id=str(inbound.user_id) if inbound.user_id is not None else None,
            message_id=str(inbound.message_id) if inbound.message_id is not None else None,
            is_callback=bool(inbound.callback_data),
        )
        messenger = TelegramMessenger(context.bot)
        if not self.access_policy.is_allowed(inbound.chat_id, inbound.user_id):
            if not self.access_policy.silent_unauthorized:
                await messenger.send_error(
                    inbound.chat_id,
                    "This Telegram user or chat is not authorized to use this bot.",
                    hint=(
                        "Check TELEGRAM_ALLOWED_CHAT_ID and, if configured, "
                        "TELEGRAM_ALLOWED_USER_ID."
                    ),
                )
            return
        approval_handled = await self._handle_pending_action_resolution(
            inbound,
            messenger=messenger,
        )
        if approval_handled:
            return

        try:
            response = await _resolve_response(self.message_handler(inbound))
        except Exception as exc:  # pragma: no cover - safety net
            if _is_content_filter_error(exc):
                await messenger.send_error(
                    inbound.chat_id,
                    (
                        "The LLM provider blocked this request while checking the "
                        "prompt. No broker action was taken."
                    ),
                    hint=(
                        "Retry with a shorter market-data request. If it repeats, "
                        "inspect the agent prompt logs for Azure content-filter triggers."
                    ),
                )
                return
            await messenger.send_error(
                inbound.chat_id,
                (
                    "Telegram bridge failed while processing the message: "
                    f"{exc.__class__.__name__}: {exc}"
                ),
                hint="Retry the request. If it keeps failing, inspect application logs.",
            )
            return

        if response is None:
            return
        if isinstance(response, TelegramApprovalRequest):
            sent = await messenger.send_approval_request(response)
            message_id = getattr(sent, "message_id", None)
            if message_id is None and isinstance(sent, dict):
                message_id = sent.get("message_id")
            if self.pending_action_service is not None and response.action_id:
                self.pending_action_service.attach_approval_message_id(
                    response.action_id,
                    _coerce_int(message_id),
                )
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

    async def _handle_pending_action_resolution(
        self,
        inbound: TelegramInboundMessage,
        *,
        messenger: TelegramMessenger,
    ) -> bool:
        if self.pending_action_service is None:
            return False
        callback_resolution = _parse_callback_resolution(inbound.callback_data)
        if callback_resolution is not None:
            verb, action_id = callback_resolution
            result = self._resolve_pending_action(
                verb,
                action_id=action_id,
                chat_id=inbound.chat_id,
                user_id=inbound.user_id,
            )
            await self._finalize_pending_action(
                inbound,
                messenger=messenger,
                result=result,
                projected_user_text=f"telegram button: {verb}",
                send_followup=True,
            )
            return True

        return False

    def _resolve_pending_action(
        self,
        verb: str,
        *,
        action_id: str,
        chat_id: int,
        user_id: int | None,
    ) -> PendingActionDecisionResult:
        if self.pending_action_service is None:
            return PendingActionDecisionResult(
                status=PendingActionDecisionStatus.FAILED,
                message="Pending-action runtime is not configured.",
            )
        if verb == "approve":
            return self.pending_action_service.approve_and_execute(
                action_id,
                chat_id=str(chat_id),
                user_id=user_id,
            )
        return self.pending_action_service.reject(
            action_id,
            chat_id=str(chat_id),
            user_id=user_id,
        )

    async def _finalize_pending_action(
        self,
        inbound: TelegramInboundMessage,
        *,
        messenger: TelegramMessenger,
        result: PendingActionDecisionResult,
        projected_user_text: str,
        send_followup: bool,
    ) -> None:
        self._journal_proposal_outcome(inbound, result=result)
        if self.history_manager is not None:
            self.history_manager.record_user_message(inbound.chat_id, projected_user_text)
            self.history_manager.record_assistant_message(inbound.chat_id, result.message)

        approval_message_id = result.action.approval_message_id if result.action else None
        if approval_message_id is not None and result.edit_text:
            try:
                await messenger.edit_message(
                    chat_id=inbound.chat_id,
                    message_id=approval_message_id,
                    text=result.edit_text,
                )
            except Exception:  # pragma: no cover - editing should not block resolution
                pass

        if send_followup:
            await messenger.send_message(
                inbound.chat_id,
                TelegramOutboundMessage(text=result.message),
            )
            return
        await messenger.send_message(
            inbound.chat_id,
            TelegramOutboundMessage(
                text=result.message,
                reply_to_message_id=inbound.message_id,
            ),
        )

    def _journal_proposal_outcome(
        self,
        inbound: TelegramInboundMessage,
        *,
        result: PendingActionDecisionResult,
    ) -> None:
        if self.proposal_service is None or result.action is None:
            return
        proposal = self.proposal_service.get_by_pending_action_id(result.action.action_id)
        if proposal is None:
            return
        source = ApprovalSource.BUTTON if inbound.callback_data else ApprovalSource.TEXT
        if result.status == PendingActionDecisionStatus.REJECTED:
            self.proposal_service.record_approval_event(
                proposal_id=proposal.proposal_id,
                pending_action_id=result.action.action_id,
                decision=ApprovalDecision.REJECT,
                source=source,
                chat_id=str(inbound.chat_id),
                user_id=inbound.user_id,
            )
            self.proposal_service.mark_rejected(proposal.proposal_id)
            return
        if result.status == PendingActionDecisionStatus.SUBMITTED:
            self.proposal_service.record_approval_event(
                proposal_id=proposal.proposal_id,
                pending_action_id=result.action.action_id,
                decision=ApprovalDecision.APPROVE,
                source=source,
                chat_id=str(inbound.chat_id),
                user_id=inbound.user_id,
            )
            broker_response = result.action.broker_result or None
            broker_order_ref = _extract_broker_order_ref(broker_response)
            self.proposal_service.record_execution_attempt(
                proposal_id=proposal.proposal_id,
                pending_action_id=result.action.action_id,
                broker_provider=result.action.broker_provider,
                action_kind=ProposalActionKind.SUBMIT_ORDER,
                status=ExecutionAttemptStatus.SUBMITTED,
                broker_order_ref=broker_order_ref,
                broker_response=broker_response,
            )
            self.proposal_service.mark_submitted(proposal.proposal_id)
            return
        if result.status == PendingActionDecisionStatus.FAILED:
            self.proposal_service.record_approval_event(
                proposal_id=proposal.proposal_id,
                pending_action_id=result.action.action_id,
                decision=ApprovalDecision.APPROVE,
                source=source,
                chat_id=str(inbound.chat_id),
                user_id=inbound.user_id,
            )
            self.proposal_service.record_execution_attempt(
                proposal_id=proposal.proposal_id,
                pending_action_id=result.action.action_id,
                broker_provider=result.action.broker_provider,
                action_kind=ProposalActionKind.SUBMIT_ORDER,
                status=ExecutionAttemptStatus.FAILED,
                broker_order_ref=_extract_broker_order_ref(result.action.broker_result),
                broker_response=result.action.broker_result or None,
                error_message=result.message,
            )
            self.proposal_service.mark_execution_failed(
                proposal.proposal_id,
                error=result.message,
            )


def build_default_message_handler(
    orchestrator: AgentOrchestrator | None = None,
    *,
    main_agent: MainOrchestratorAgent | None = None,
    history_manager: ChatHistoryManager | None = None,
    proposal_service: ProposalService | None = None,
) -> TelegramMessageHandler:
    resolved_orchestrator = orchestrator or AgentOrchestrator()
    resolved_history = history_manager or ChatHistoryManager()

    if main_agent is not None:

        def _agent_handle(
            message: TelegramInboundMessage,
        ) -> TelegramApprovalRequest | TelegramOutboundMessage:
            if message.text.strip().lower() == "/help":
                resolved_history.record_user_message(message.chat_id, message.text)
                response = TelegramOutboundMessage(text=render_help_text())
                resolved_history.record_assistant_message(message.chat_id, response.text)
                return response
            if proposal_service is not None:
                proposal_response = _handle_proposal_command(
                    message,
                    proposal_service=proposal_service,
                )
                if proposal_response is not None:
                    resolved_history.record_user_message(message.chat_id, message.text)
                    resolved_history.record_assistant_message(
                        message.chat_id,
                        proposal_response.text,
                    )
                    return proposal_response

            history = resolved_history.get_context_window(message.chat_id)
            request = AgentRequest(
                user_message=message.text,
                chat_id=str(message.chat_id),
                trigger_type="telegram_user",
                history=history,
                metadata={
                    "telegram_message_id": str(message.message_id or ""),
                    "telegram_user_id": str(message.user_id or ""),
                },
            )
            resolved_history.record_user_message(message.chat_id, message.text)
            agent_response = main_agent.handle(request)
            approval_payload = agent_response.artifacts.get("telegram_approval_request")
            outbound_text = agent_response.final_answer
            if isinstance(approval_payload, dict) and approval_payload.get("text"):
                outbound_text = str(approval_payload["text"])
            resolved_history.record_assistant_message(
                message.chat_id,
                outbound_text,
                metadata={"selected_agent": agent_response.selected_agent},
            )
            if isinstance(approval_payload, dict):
                return TelegramApprovalRequest(
                    chat_id=message.chat_id,
                    text=outbound_text,
                    action_id=_optional_str(approval_payload.get("actionId")),
                    approve_callback_data=str(approval_payload.get("approveCallbackData", "")),
                    reject_callback_data=str(approval_payload.get("rejectCallbackData", "")),
                    reply_to_message_id=message.message_id,
                )
            return TelegramOutboundMessage(text=agent_response.final_answer)

        return _agent_handle

    def _handle(message: TelegramInboundMessage) -> TelegramOutboundMessage:
        if proposal_service is not None:
            proposal_response = _handle_proposal_command(
                message,
                proposal_service=proposal_service,
            )
            if proposal_response is not None:
                return proposal_response
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
    runtime: AppRuntime | None = None,
) -> TelegramMessageHandler:
    resolved_runtime = runtime or build_runtime()
    if resolved_runtime.main_orchestrator is None:
        return build_default_message_handler(
            history_manager=history_manager,
            proposal_service=resolved_runtime.proposal_service,
        )

    return build_default_message_handler(
        main_agent=resolved_runtime.main_orchestrator,
        history_manager=history_manager or resolved_runtime.history_manager,
        proposal_service=resolved_runtime.proposal_service,
    )


async def _resolve_response(
    value: TelegramApprovalRequest
    | TelegramOutboundMessage
    | str
    | None
    | Awaitable[TelegramApprovalRequest | TelegramOutboundMessage | str | None],
) -> TelegramApprovalRequest | TelegramOutboundMessage | str | None:
    if inspect.isawaitable(value):
        return await value
    return value


def _is_content_filter_error(exc: Exception) -> bool:
    values = [
        getattr(exc, "code", None),
        getattr(exc, "status_code", None),
        getattr(exc, "body", None),
        getattr(exc, "message", None),
        str(exc),
    ]
    text = " ".join(str(value).lower() for value in values if value is not None)
    return "contentfilter" in text or "responsibleaipolicyviolation" in text


async def _acknowledge_callback(update: Any) -> None:
    callback_query = getattr(update, "callback_query", None)
    answer = getattr(callback_query, "answer", None) if callback_query else None
    if answer is None:
        return
    result = answer()
    if inspect.isawaitable(result):
        await result


def _parse_callback_resolution(callback_data: str | None) -> tuple[str, str] | None:
    if not callback_data:
        return None
    match = re.match(r"^pa:(approve|reject):(pa_[A-Za-z0-9]+)$", callback_data.strip())
    if not match:
        return None
    return match.group(1), match.group(2)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    return raw or None


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_broker_order_ref(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("order_id", "orderId"):
        if key in payload:
            return _optional_str(payload.get(key))
    order = payload.get("order")
    if isinstance(order, dict):
        for key in ("id", "order_id", "orderId"):
            if key in order:
                return _optional_str(order.get(key))
    return None


def _handle_proposal_command(
    message: TelegramInboundMessage,
    *,
    proposal_service: ProposalService,
) -> TelegramOutboundMessage | None:
    raw = message.text.strip()
    lowered = raw.lower()
    if lowered == "/proposals":
        proposals = proposal_service.list_recent_proposals(
            chat_id=str(message.chat_id),
            user_id=message.user_id,
        )
        return TelegramOutboundMessage(text=render_recent_proposals_text(proposals))
    match = re.match(r"^/proposal\s+(\S+)\s*$", raw, flags=re.IGNORECASE)
    if match is None:
        if lowered.startswith("/proposal"):
            return TelegramOutboundMessage(
                text="Usage: /proposal <proposal_id>",
            )
        return None
    detail = proposal_service.get_proposal(match.group(1))
    if detail is None:
        return TelegramOutboundMessage(text="Proposal not found.")
    if detail.proposal.chat_id != str(message.chat_id):
        return TelegramOutboundMessage(text="Proposal not found in this Telegram chat.")
    if (
        detail.proposal.user_id is not None
        and message.user_id is not None
        and detail.proposal.user_id != int(message.user_id)
    ):
        return TelegramOutboundMessage(text="Proposal not found for this Telegram user.")
    return TelegramOutboundMessage(text=render_proposal_detail_text(detail))
