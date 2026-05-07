from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import sys

from t212ai.persistence.database import build_engine, build_session_factory, ensure_schema
from t212ai.scheduler import (
    ScheduledEventType,
    ScheduledProcessService,
    SchedulerNotificationRequest,
    SchedulerNotificationResult,
    SchedulerNotificationService,
    SchedulerNotificationStatus,
    TelegramSchedulerNotifier,
)


BASE_NOW = datetime(2026, 5, 7, 9, 0, tzinfo=UTC)


class SendingNotifier:
    def __init__(self) -> None:
        self.requests: list[SchedulerNotificationRequest] = []

    def send(self, request: SchedulerNotificationRequest) -> SchedulerNotificationResult:
        self.requests.append(request)
        return SchedulerNotificationResult(
            status=SchedulerNotificationStatus.SENT,
            message="Notification sent.",
            sent_count=1,
            target_chat_ids=(123,),
            sent_chat_ids=(123,),
        )


class RaisingNotifier:
    def send(self, request: SchedulerNotificationRequest) -> SchedulerNotificationResult:
        del request
        raise RuntimeError("telegram unavailable")


class FakeTelegramBot:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send_message(
        self,
        *,
        chat_id,
        text,
        parse_mode=None,
        reply_markup=None,
        reply_to_message_id=None,
        disable_web_page_preview=True,
    ):
        self.sent.append(
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
                "reply_to_message_id": reply_to_message_id,
                "disable_web_page_preview": disable_web_page_preview,
            }
        )
        return SimpleNamespace(message_id=len(self.sent))


def _install_fake_telegram_module(monkeypatch) -> None:
    class InlineKeyboardButton:
        def __init__(self, text, *, callback_data):
            self.text = text
            self.callback_data = callback_data

    class InlineKeyboardMarkup:
        def __init__(self, inline_keyboard):
            self.inline_keyboard = inline_keyboard

    monkeypatch.setitem(
        sys.modules,
        "telegram",
        SimpleNamespace(
            InlineKeyboardButton=InlineKeyboardButton,
            InlineKeyboardMarkup=InlineKeyboardMarkup,
        ),
    )


def _service(tmp_path: Path) -> ScheduledProcessService:
    engine = build_engine(f"sqlite:///{tmp_path / 'scheduler-notifications.db'}")
    ensure_schema(engine)
    return ScheduledProcessService(build_session_factory(engine))


def _create_process(service: ScheduledProcessService):
    return service.create_process(
        title="TSLA watch",
        kind="instrument_monitor",
        execution_mode="deterministic",
        schedule={"type": "polling", "pollEverySeconds": 60},
        trigger={"type": "below_price", "symbol": "TSLA", "value": 180},
        lifecycle={"completionPolicy": "keep_running"},
        now=BASE_NOW,
    )


def test_scheduler_notification_service_records_queued_and_sent_events(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    process = _create_process(service)
    run = service.record_run_started(process.process_id, now=BASE_NOW)
    service.record_run_completed(run.run_id, now=BASE_NOW + timedelta(seconds=1))
    notifier = SendingNotifier()
    notification_service = SchedulerNotificationService(service, notifier=notifier)

    result = notification_service.send_process_notification(
        process_id=process.process_id,
        run_id=run.run_id,
        message="TSLA crossed the configured threshold.",
        metadata={"symbol": "TSLA"},
    )

    assert result.ok
    assert notifier.requests[0].message == "TSLA crossed the configured threshold."
    events = service.list_events(process.process_id)
    assert [event.event_type for event in events][-2:] == [
        ScheduledEventType.NOTIFICATION_QUEUED,
        ScheduledEventType.NOTIFICATION_SENT,
    ]
    assert events[-2].details["messagePreview"] == "TSLA crossed the configured threshold."
    assert events[-1].details["result"]["sentCount"] == 1


def test_scheduler_notification_service_records_send_failure(tmp_path: Path) -> None:
    service = _service(tmp_path)
    process = _create_process(service)
    run = service.record_run_started(process.process_id, now=BASE_NOW)
    notification_service = SchedulerNotificationService(service, notifier=RaisingNotifier())

    result = notification_service.send_process_notification(
        process_id=process.process_id,
        run_id=run.run_id,
        message="Alert text.",
    )

    assert result.status == SchedulerNotificationStatus.FAILED
    assert result.error_code == "notifier_error"
    events = service.list_events(process.process_id)
    assert [event.event_type for event in events][-2:] == [
        ScheduledEventType.NOTIFICATION_QUEUED,
        ScheduledEventType.NOTIFICATION_FAILED,
    ]
    assert "RuntimeError: telegram unavailable" in events[-1].details["result"]["errorMessage"]


def test_scheduler_notification_service_records_missing_notifier(tmp_path: Path) -> None:
    service = _service(tmp_path)
    process = _create_process(service)
    notification_service = SchedulerNotificationService(service)

    result = notification_service.send_process_notification(
        process_id=process.process_id,
        message="Alert text.",
    )

    assert result.status == SchedulerNotificationStatus.FAILED
    assert result.error_code == "notifier_unavailable"
    events = service.list_events(process.process_id)
    assert [event.event_type for event in events][-2:] == [
        ScheduledEventType.NOTIFICATION_QUEUED,
        ScheduledEventType.NOTIFICATION_FAILED,
    ]


def test_telegram_scheduler_notifier_sends_to_configured_chats() -> None:
    bot = FakeTelegramBot()
    notifier = TelegramSchedulerNotifier(
        token="telegram-token",
        chat_ids=(123, 456),
        bot_factory=lambda _token: bot,
    )

    result = notifier.send(
        SchedulerNotificationRequest(
            process_id="sched_test",
            message="Scheduler alert.",
        )
    )

    assert result.status == SchedulerNotificationStatus.SENT
    assert result.sent_count == 2
    assert [item["chat_id"] for item in bot.sent] == [123, 456]
    assert bot.sent[0]["text"] == "Scheduler alert."


def test_telegram_scheduler_notifier_sends_approval_buttons(monkeypatch) -> None:
    _install_fake_telegram_module(monkeypatch)
    bot = FakeTelegramBot()
    notifier = TelegramSchedulerNotifier(
        token="telegram-token",
        chat_ids=(123,),
        bot_factory=lambda _token: bot,
    )

    result = notifier.send(
        SchedulerNotificationRequest(
            process_id="sched_trade",
            message="Fallback message.",
            approval_payload={
                "actionId": "pa_test",
                "text": "Approve this guarded proposal.",
                "approveCallbackData": "pa:approve:pa_test",
                "rejectCallbackData": "pa:reject:pa_test",
            },
        )
    )

    assert result.status == SchedulerNotificationStatus.SENT
    assert result.metadata["approvalActionId"] == "pa_test"
    assert result.metadata["responses"][0]["messageId"] == 1
    assert bot.sent[0]["text"] == "Approve this guarded proposal."
    assert bot.sent[0]["reply_markup"] is not None


class CapturingPendingActionService:
    def __init__(self) -> None:
        self.attached: list[tuple[str, int]] = []

    def attach_approval_message_id(self, action_id: str, message_id: int | None):
        assert message_id is not None
        self.attached.append((action_id, message_id))
        return None


def test_scheduler_notification_service_attaches_approval_message_id(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _install_fake_telegram_module(monkeypatch)
    service = _service(tmp_path)
    process = _create_process(service)
    pending = CapturingPendingActionService()
    notifier = SendingNotifier()
    notification_service = SchedulerNotificationService(
        service,
        notifier=notifier,
        pending_action_service=pending,
    )

    result = notification_service.send_process_notification(
        process_id=process.process_id,
        message="Approval text.",
        approval_payload={
            "actionId": "pa_test",
            "text": "Approval text.",
            "approveCallbackData": "pa:approve:pa_test",
            "rejectCallbackData": "pa:reject:pa_test",
        },
    )

    assert result.status == SchedulerNotificationStatus.SENT
    assert notifier.requests[0].approval_payload["actionId"] == "pa_test"
    assert pending.attached == []

    notification_service = SchedulerNotificationService(
        service,
        notifier=TelegramSchedulerNotifier(
            token="telegram-token",
            chat_ids=(123,),
            bot_factory=lambda _token: FakeTelegramBot(),
        ),
        pending_action_service=pending,
    )
    result = notification_service.send_process_notification(
        process_id=process.process_id,
        message="Approval text.",
        approval_payload={
            "actionId": "pa_test",
            "text": "Approval text.",
            "approveCallbackData": "pa:approve:pa_test",
            "rejectCallbackData": "pa:reject:pa_test",
        },
    )

    assert result.status == SchedulerNotificationStatus.SENT
    assert pending.attached == [("pa_test", 1)]
