"""Scheduler notification services and notifier adapters."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
import threading
from typing import Any, Callable, Protocol

from t212ai.app.config import AppSettings
from t212ai.genai.tracing import set_trace_metadata, traceable
from t212ai.pending_actions import PendingActionService

from .models import ScheduledEventType
from .service import ScheduledProcessService


class SchedulerNotificationStatus(StrEnum):
    SENT = "sent"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SchedulerNotificationRequest:
    process_id: str
    message: str
    run_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    target_chat_ids: tuple[int, ...] = ()
    approval_payload: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class SchedulerNotificationResult:
    status: SchedulerNotificationStatus
    message: str
    sent_count: int = 0
    failed_count: int = 0
    target_chat_ids: tuple[int, ...] = ()
    sent_chat_ids: tuple[int, ...] = ()
    failed_chat_ids: tuple[int, ...] = ()
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == SchedulerNotificationStatus.SENT

    def event_details(self) -> dict[str, Any]:
        details: dict[str, Any] = {
            "status": self.status.value,
            "sentCount": self.sent_count,
            "failedCount": self.failed_count,
            "targetChatIds": list(self.target_chat_ids),
            "sentChatIds": list(self.sent_chat_ids),
            "failedChatIds": list(self.failed_chat_ids),
        }
        if self.error_code:
            details["errorCode"] = self.error_code
        if self.error_message:
            details["errorMessage"] = self.error_message
        if self.metadata:
            details["metadata"] = self.metadata
        return details


class SchedulerNotifier(Protocol):
    def send(self, request: SchedulerNotificationRequest) -> SchedulerNotificationResult:
        """Send a scheduler notification through an outbound channel."""


class SchedulerNotificationService:
    """Persists scheduler notification attempts and delegates outbound sends."""

    def __init__(
        self,
        scheduler_service: ScheduledProcessService,
        *,
        notifier: SchedulerNotifier | None = None,
        pending_action_service: PendingActionService | None = None,
    ) -> None:
        self.scheduler_service = scheduler_service
        self.notifier = notifier
        self.pending_action_service = pending_action_service

    @traceable(name="scheduler.notification.send", run_type="chain")
    def send_process_notification(
        self,
        *,
        process_id: str,
        message: str,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        target_chat_ids: tuple[int, ...] | list[int] | None = None,
        approval_payload: dict[str, Any] | None = None,
    ) -> SchedulerNotificationResult:
        set_trace_metadata(
            agent_step="scheduler_notification_send",
            step_kind="chain",
            process_id=str(process_id),
            has_run_id=run_id is not None,
            has_notifier=self.notifier is not None,
        )
        request = SchedulerNotificationRequest(
            process_id=_required_text(process_id, "process_id"),
            run_id=str(run_id) if run_id is not None else None,
            message=_required_text(message, "message"),
            metadata=dict(metadata or {}),
            target_chat_ids=tuple(int(chat_id) for chat_id in (target_chat_ids or ())),
            approval_payload=dict(approval_payload) if approval_payload else None,
        )
        self.scheduler_service.record_event(
            request.process_id,
            run_id=request.run_id,
            event_type=ScheduledEventType.NOTIFICATION_QUEUED,
            message="Scheduler notification queued.",
            details={
                "message": request.message,
                "messagePreview": _preview(request.message),
                "metadata": request.metadata,
                "targetChatIds": list(request.target_chat_ids),
                "approvalActionId": (
                    request.approval_payload.get("actionId")
                    if request.approval_payload
                    else None
                ),
            },
        )
        if self.notifier is None:
            result = SchedulerNotificationResult(
                status=SchedulerNotificationStatus.FAILED,
                message="Scheduler notification failed: no notifier is configured.",
                failed_count=1,
                error_code="notifier_unavailable",
                error_message="No scheduler notifier is configured.",
            )
            self._record_result(request, result)
            return result
        try:
            result = self.notifier.send(request)
        except Exception as exc:  # pragma: no cover - defensive path covered by tests
            result = SchedulerNotificationResult(
                status=SchedulerNotificationStatus.FAILED,
                message=f"Scheduler notification failed: {exc}.",
                failed_count=1,
                error_code="notifier_error",
                error_message=f"{exc.__class__.__name__}: {exc}",
            )
        self._record_result(request, result)
        self._attach_approval_message_id(request, result)
        return result

    def _record_result(
        self,
        request: SchedulerNotificationRequest,
        result: SchedulerNotificationResult,
    ) -> None:
        self.scheduler_service.record_event(
            request.process_id,
            run_id=request.run_id,
            event_type=(
                ScheduledEventType.NOTIFICATION_SENT
                if result.ok
                else ScheduledEventType.NOTIFICATION_FAILED
            ),
            message=result.message,
            details={
                "request": {
                    "messagePreview": _preview(request.message),
                    "metadata": request.metadata,
                    "targetChatIds": list(request.target_chat_ids),
                },
                "result": result.event_details(),
            },
        )

    def _attach_approval_message_id(
        self,
        request: SchedulerNotificationRequest,
        result: SchedulerNotificationResult,
    ) -> None:
        if self.pending_action_service is None or request.approval_payload is None:
            return
        action_id = str(request.approval_payload.get("actionId") or "").strip()
        if not action_id:
            return
        responses = result.metadata.get("responses") if isinstance(result.metadata, dict) else None
        if not isinstance(responses, list):
            return
        for response in responses:
            if not isinstance(response, dict):
                continue
            message_id = response.get("messageId")
            if message_id is None:
                continue
            try:
                self.pending_action_service.attach_approval_message_id(
                    action_id,
                    int(message_id),
                )
            except Exception:
                return
            return


class TelegramSchedulerNotifier:
    """Sends scheduler notifications to configured Telegram chat ids."""

    def __init__(
        self,
        *,
        token: str,
        chat_ids: tuple[int, ...],
        bot_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self.token = _required_text(token, "token")
        self.chat_ids = tuple(int(chat_id) for chat_id in chat_ids)
        if not self.chat_ids:
            raise RuntimeError("At least one Telegram chat id is required.")
        self._bot_factory = bot_factory
        self._bot: Any | None = None

    @classmethod
    def from_settings(cls, settings: AppSettings) -> "TelegramSchedulerNotifier":
        if not settings.telegram_bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required for scheduler notifications.")
        from t212ai.telegram.auth import TelegramAccessPolicy

        policy = TelegramAccessPolicy.from_settings(settings)
        return cls(
            token=settings.telegram_bot_token,
            chat_ids=tuple(sorted(policy.allowed_chat_ids)),
        )

    def send(self, request: SchedulerNotificationRequest) -> SchedulerNotificationResult:
        chat_ids = tuple(request.target_chat_ids or self.chat_ids)
        if not chat_ids:
            return SchedulerNotificationResult(
                status=SchedulerNotificationStatus.FAILED,
                message="Telegram scheduler notification failed: no chat ids configured.",
                error_code="telegram_chat_ids_missing",
                error_message="No Telegram chat ids were configured for the notification.",
            )
        try:
            if request.approval_payload:
                return _run_coroutine(
                    self._send_approval_async(request.approval_payload, chat_ids)
                )
            return _run_coroutine(self._send_async(request.message, chat_ids))
        except Exception as exc:
            return SchedulerNotificationResult(
                status=SchedulerNotificationStatus.FAILED,
                message=f"Telegram scheduler notification failed: {exc}.",
                target_chat_ids=chat_ids,
                failed_chat_ids=chat_ids,
                failed_count=len(chat_ids),
                error_code="telegram_send_failed",
                error_message=f"{exc.__class__.__name__}: {exc}",
            )

    async def _send_async(
        self,
        message: str,
        chat_ids: tuple[int, ...],
    ) -> SchedulerNotificationResult:
        from t212ai.telegram.messenger import TelegramMessenger
        from t212ai.telegram.models import TelegramOutboundMessage

        messenger = TelegramMessenger(self._get_bot())
        sent: list[int] = []
        failed: list[int] = []
        errors: list[str] = []
        response_metadata: list[dict[str, Any]] = []
        for chat_id in chat_ids:
            try:
                response = await messenger.send_message(
                    chat_id,
                    TelegramOutboundMessage(text=message),
                )
            except Exception as exc:  # pragma: no cover - exercised through fake bot
                failed.append(chat_id)
                errors.append(f"{chat_id}: {exc.__class__.__name__}: {exc}")
                continue
            sent.append(chat_id)
            response_metadata.append(
                {
                    "chatId": chat_id,
                    "messageId": getattr(response, "message_id", None),
                }
            )
        status = (
            SchedulerNotificationStatus.SENT
            if not failed
            else SchedulerNotificationStatus.PARTIAL
            if sent
            else SchedulerNotificationStatus.FAILED
        )
        return SchedulerNotificationResult(
            status=status,
            message=_telegram_result_message(status, sent_count=len(sent), failed_count=len(failed)),
            sent_count=len(sent),
            failed_count=len(failed),
            target_chat_ids=chat_ids,
            sent_chat_ids=tuple(sent),
            failed_chat_ids=tuple(failed),
            error_code="telegram_partial_failure" if failed else None,
            error_message="; ".join(errors) if errors else None,
            metadata={"responses": response_metadata},
        )

    async def _send_approval_async(
        self,
        approval_payload: dict[str, Any],
        chat_ids: tuple[int, ...],
    ) -> SchedulerNotificationResult:
        from t212ai.telegram.messenger import TelegramMessenger
        from t212ai.telegram.models import TelegramApprovalRequest

        messenger = TelegramMessenger(self._get_bot())
        sent: list[int] = []
        failed: list[int] = []
        errors: list[str] = []
        response_metadata: list[dict[str, Any]] = []
        text = _required_text(str(approval_payload.get("text") or ""), "approval text")
        action_id = str(approval_payload.get("actionId") or "").strip() or None
        approve = _required_text(
            str(approval_payload.get("approveCallbackData") or ""),
            "approveCallbackData",
        )
        reject = _required_text(
            str(approval_payload.get("rejectCallbackData") or ""),
            "rejectCallbackData",
        )
        for chat_id in chat_ids:
            try:
                response = await messenger.send_approval_request(
                    TelegramApprovalRequest(
                        chat_id=chat_id,
                        text=text,
                        action_id=action_id,
                        approve_callback_data=approve,
                        reject_callback_data=reject,
                    )
                )
            except Exception as exc:  # pragma: no cover - exercised through fake bot
                failed.append(chat_id)
                errors.append(f"{chat_id}: {exc.__class__.__name__}: {exc}")
                continue
            sent.append(chat_id)
            response_metadata.append(
                {
                    "chatId": chat_id,
                    "messageId": getattr(response, "message_id", None),
                    "actionId": action_id,
                }
            )
        status = (
            SchedulerNotificationStatus.SENT
            if not failed
            else SchedulerNotificationStatus.PARTIAL
            if sent
            else SchedulerNotificationStatus.FAILED
        )
        return SchedulerNotificationResult(
            status=status,
            message=_telegram_result_message(status, sent_count=len(sent), failed_count=len(failed)),
            sent_count=len(sent),
            failed_count=len(failed),
            target_chat_ids=chat_ids,
            sent_chat_ids=tuple(sent),
            failed_chat_ids=tuple(failed),
            error_code="telegram_partial_failure" if failed else None,
            error_message="; ".join(errors) if errors else None,
            metadata={"responses": response_metadata, "approvalActionId": action_id},
        )

    def _get_bot(self) -> Any:
        if self._bot is not None:
            return self._bot
        if self._bot_factory is not None:
            self._bot = self._bot_factory(self.token)
            return self._bot
        try:
            from telegram import Bot
        except ImportError as exc:  # pragma: no cover - optional dependency path
            raise RuntimeError(
                "python-telegram-bot is required to send scheduler notifications."
            ) from exc
        self._bot = Bot(self.token)
        return self._bot


def _telegram_result_message(
    status: SchedulerNotificationStatus,
    *,
    sent_count: int,
    failed_count: int,
) -> str:
    if status == SchedulerNotificationStatus.SENT:
        return f"Telegram scheduler notification sent to {sent_count} chat(s)."
    if status == SchedulerNotificationStatus.PARTIAL:
        return (
            "Telegram scheduler notification partially sent: "
            f"sent={sent_count} failed={failed_count}."
        )
    return f"Telegram scheduler notification failed for {failed_count} chat(s)."


def _run_coroutine(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - defensive
            error["value"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error["value"]
    return result.get("value")


def _required_text(value: str, field_name: str) -> str:
    resolved = str(value or "").strip()
    if not resolved:
        raise ValueError(f"{field_name} is required.")
    return resolved


def _preview(value: str, *, limit: int = 180) -> str:
    compact = " ".join(str(value or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."
