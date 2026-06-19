from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from t212ai.agent.history import ChatHistoryManager
from t212ai.agent.schemas import AgentResponse
from t212ai.alpaca.news import CleanedNewsPacket
from t212ai.app.alpaca_news_stream_supervisor import (
    AlpacaNewsStreamSupervisor,
    _monitor_spec,
    _subscription_symbols,
    _symbol_filter_matches,
)
from t212ai.persistence.database import build_engine, build_session_factory, ensure_schema
from t212ai.scheduler import ScheduledEventType, ScheduledProcessService, SchedulerManagementRuntime
from t212ai.scheduler.management import scheduler_alpaca_news_monitor_create


class _UnusedStreamClient:
    pass


class _UnusedJudge:
    def handle(self, _request):  # pragma: no cover - not used in this unit test
        raise NotImplementedError


def _service(tmp_path: Path) -> ScheduledProcessService:
    engine = build_engine(f"sqlite:///{tmp_path / 'alpaca-news-supervisor.db'}")
    ensure_schema(engine)
    return ScheduledProcessService(build_session_factory(engine))


def test_supervisor_records_relevant_background_news_in_history(tmp_path: Path) -> None:
    service = _service(tmp_path)
    runtime = SchedulerManagementRuntime(
        service=service,
        default_timezone="Europe/Rome",
        clock=lambda: datetime(2026, 5, 12, 9, 0, tzinfo=UTC),
        chat_id="5527868809",
        user_id=5527868809,
    )
    created = scheduler_alpaca_news_monitor_create(
        title="Rare earth monitor",
        description="Track MP and USAR news.",
        symbols=["MP", "USAR"],
        start_at=None,
        end_at=None,
        duration_minutes=60,
        timezone="Europe/Rome",
        task_guidelines="Only surface material developments.",
        order_proposals_enabled=True,
        max_events_per_minute=10,
        notification_enabled=True,
        broker_actions_allowed=False,
        runtime=runtime,
    )
    process = service.get_process(created.data["process"]["processId"])
    assert process is not None
    run = service.record_run_started(process.process_id, metadata={"kind": process.kind.value})
    history_manager = ChatHistoryManager()
    supervisor = AlpacaNewsStreamSupervisor(
        service,
        _UnusedStreamClient(),  # type: ignore[arg-type]
        _UnusedJudge(),  # type: ignore[arg-type]
        history_manager=history_manager,
    )

    supervisor._handle_judge_response(  # noqa: SLF001
        process=process,
        spec=_monitor_spec(process),
        packet=CleanedNewsPacket(
            id=101,
            source="benzinga",
            headline="MP Materials secures new supply agreement",
            summary="Summary",
            content_text="Content",
            symbols=["MP"],
            url="https://example.test/mp",
            created_at="2026-05-12T09:00:00Z",
            updated_at="2026-05-12T09:00:05Z",
            received_at="2026-05-12T09:00:06Z",
            dedupe_key="benzinga:101",
        ),
        response=AgentResponse(
            final_answer="Saved a market signal for MP; no immediate user alert.",
            selected_agent="news_ingestion_judge",
            metadata={"relevant": "True", "user_visible": "False"},
            artifacts={
                "news_judge_result": {
                    "summary": "Saved a market signal for MP.",
                    "actionsTaken": ["market_signal_create"],
                }
            },
        ),
        run_id=run.run_id,
    )

    history = history_manager.get_context_window("5527868809")
    assert len(history.messages) == 1
    assert history.messages[0].role == "assistant"
    assert history.messages[0].metadata["source"] == "scheduler_alpaca_news_monitor"
    assert history.messages[0].metadata["notification_kind"] == "background"

    events = service.list_events(process.process_id)
    matched = [event for event in events if event.event_type == ScheduledEventType.TRIGGER_MATCHED]
    assert len(matched) == 1
    assert matched[0].details["dedupeKey"] == "benzinga:101"
    assert matched[0].details["userVisible"] is False


def test_supervisor_wildcard_monitor_accepts_all_packet_symbols() -> None:
    assert _subscription_symbols(["*"]) == ["*"]
    assert _subscription_symbols([]) == ["*"]
    assert _symbol_filter_matches(["*"], ["AAPL"])
    assert _symbol_filter_matches([], ["AAPL"])
    assert _symbol_filter_matches(["MP", "USAR"], ["MP"])
    assert not _symbol_filter_matches(["MP", "USAR"], ["AAPL"])


def test_monitor_spec_defaults_legacy_empty_symbols_to_wildcard(tmp_path: Path) -> None:
    service = _service(tmp_path)
    process = service.create_process(
        title="Legacy empty-symbol news monitor",
        description="Old records may have stored an empty symbol list.",
        kind="alpaca_news_monitor",
        execution_mode="llm_assisted",
        schedule={"type": "manual"},
        trigger={"type": "alpaca_news_stream", "symbols": []},
        inputs={
            "symbols": [],
            "startAt": "2026-05-12T09:00:00+00:00",
            "endAt": "2026-05-12T09:30:00+00:00",
            "timezone": "UTC",
            "maxEventsPerMinute": 10,
        },
        llm_scope={},
        action={"type": "judge_news"},
        notification={"enabled": True},
        lifecycle={"completionPolicy": "complete_on_first_run"},
        safety={"brokerActionsAllowed": False},
    )

    assert _monitor_spec(process).symbols == ["*"]
