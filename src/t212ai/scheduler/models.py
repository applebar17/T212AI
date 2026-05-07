"""Scheduler domain models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SchedulerModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class ScheduledProcessKind(StrEnum):
    INSTRUMENT_MONITOR = "instrument_monitor"
    COMPANY_EVENT_ANALYST = "company_event_analyst"
    MARKET_REGIME_MONITOR = "market_regime_monitor"
    TRADE_SETUP_MONITOR = "trade_setup_monitor"
    MARKET_SIGNAL_CAPTURE = "market_signal_capture"
    WATCHLIST_BRIEFING = "watchlist_briefing"
    FILING_OR_INSIDER_MONITOR = "filing_or_insider_monitor"
    PORTFOLIO_ATTENTION_MONITOR = "portfolio_attention_monitor"


class ScheduledExecutionMode(StrEnum):
    DETERMINISTIC = "deterministic"
    LLM_ASSISTED = "llm_assisted"
    LLM_PLANNED = "llm_planned"


class ScheduledProcessStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    EXPIRED = "expired"
    ARCHIVED = "archived"
    FAILED = "failed"


class ScheduleType(StrEnum):
    ONE_SHOT = "one_shot"
    RECURRING = "recurring"
    POLLING = "polling"
    MANUAL = "manual"


class LifecycleCompletionPolicy(StrEnum):
    COMPLETE_ON_FIRST_RUN = "complete_on_first_run"
    COMPLETE_ON_FIRST_MATCH = "complete_on_first_match"
    KEEP_RUNNING = "keep_running"
    COMPLETE_AFTER_N_MATCHES = "complete_after_n_matches"


class ScheduledRunStatus(StrEnum):
    STARTED = "started"
    SKIPPED = "skipped"
    COMPLETED = "completed"
    FAILED = "failed"


class ScheduledEventType(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    PAUSED = "paused"
    RESUMED = "resumed"
    ARCHIVED = "archived"
    COMPLETED = "completed"
    EXPIRED = "expired"
    FAILED = "failed"
    RUN_STARTED = "run_started"
    RUN_SKIPPED = "run_skipped"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    TRIGGER_MATCHED = "trigger_matched"
    NOTIFICATION_QUEUED = "notification_queued"
    NOTIFICATION_SENT = "notification_sent"
    NOTIFICATION_FAILED = "notification_failed"


class ScheduleSpec(SchedulerModel):
    type: ScheduleType
    run_at: datetime | None = Field(default=None, alias="runAt")
    frequency: str | None = None
    time: str | None = None
    timezone: str | None = None
    days: list[str] = Field(default_factory=list)
    poll_every_seconds: int | None = Field(default=None, alias="pollEverySeconds")


class LifecycleSpec(SchedulerModel):
    completion_policy: LifecycleCompletionPolicy = Field(alias="completionPolicy")
    expires_at: datetime | None = Field(default=None, alias="expiresAt")
    max_runs: int | None = Field(default=None, alias="maxRuns")
    max_matches: int | None = Field(default=None, alias="maxMatches")
    cooldown_seconds: int = Field(default=0, alias="cooldownSeconds")


class SafetySpec(SchedulerModel):
    broker_actions_allowed: bool = Field(default=False, alias="brokerActionsAllowed")


class ScheduledProcessSpec(SchedulerModel):
    title: str
    description: str = ""
    kind: ScheduledProcessKind
    execution_mode: ScheduledExecutionMode = Field(alias="executionMode")
    schedule: ScheduleSpec
    trigger: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, Any] = Field(default_factory=dict)
    llm_scope: dict[str, Any] = Field(default_factory=dict, alias="llmScope")
    action: dict[str, Any] = Field(default_factory=dict)
    notification: dict[str, Any] = Field(default_factory=dict)
    lifecycle: LifecycleSpec
    safety: SafetySpec = Field(default_factory=SafetySpec)


class ScheduledProcess(ScheduledProcessSpec):
    process_id: str = Field(alias="processId")
    status: ScheduledProcessStatus
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    next_run_at: datetime | None = Field(default=None, alias="nextRunAt")
    last_run_at: datetime | None = Field(default=None, alias="lastRunAt")
    last_status: ScheduledRunStatus | None = Field(default=None, alias="lastStatus")
    failure_count: int = Field(default=0, alias="failureCount")


class ScheduledProcessRun(SchedulerModel):
    run_id: str = Field(alias="runId")
    process_id: str = Field(alias="processId")
    status: ScheduledRunStatus
    started_at: datetime = Field(alias="startedAt")
    finished_at: datetime | None = Field(default=None, alias="finishedAt")
    due_at: datetime | None = Field(default=None, alias="dueAt")
    matched: bool = False
    output_summary: str | None = Field(default=None, alias="outputSummary")
    error_code: str | None = Field(default=None, alias="errorCode")
    error_message: str | None = Field(default=None, alias="errorMessage")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScheduledProcessEvent(SchedulerModel):
    event_id: str = Field(alias="eventId")
    process_id: str = Field(alias="processId")
    run_id: str | None = Field(default=None, alias="runId")
    event_type: ScheduledEventType = Field(alias="eventType")
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(alias="createdAt")
