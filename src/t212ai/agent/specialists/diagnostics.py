"""Log diagnostic specialist agent."""

from __future__ import annotations

from t212ai.diagnostics import (
    DIAGNOSTIC_LOGS_TOOLBOX,
    LogFileNavigator,
    build_diagnostic_logs_tool_mapping,
)
from t212ai.genai.tools.base import render_tool_descriptions
from t212ai.genai.tracing import set_trace_metadata, set_trace_name, traceable
from t212ai.guidelines.service import GuidelineMemoryService

from ..base import AgentProfile, BaseAgent
from ..intents import AgentIntent, IntentKind
from ..planner import TaskComplexity
from ..schemas import AgentRequest, AgentResponse


class LogDiagnosticAgent(BaseAgent):
    def __init__(
        self,
        reasoner,
        guideline_service: GuidelineMemoryService | None = None,
        *,
        navigator: LogFileNavigator | None = None,
        max_tool_calls: int = 10,
    ) -> None:
        super().__init__(
            reasoner,
            AgentProfile(
                name="log_diagnostic_agent",
                purpose=(
                    "Investigate application and runtime failures using read-only "
                    "structured operational logs."
                ),
                guidelines=(
                    "Use only read-only diagnostic log tools. Correlate records by "
                    "chat_id, message_id, request_id, event names, error codes, "
                    "agent names, tool names, statuses, and timestamps. Use multiple "
                    "targeted queries when useful: tail for recency, query for known "
                    "time windows or ids, context for nearby records, and counts for "
                    "patterns. Return a concise finding, evidence bullets with "
                    "timestamps/events/error codes, likely root cause, and the next "
                    "diagnostic step if inconclusive. Do not expose raw log dumps, "
                    "secrets, prompts, raw chat content, account data, or broker payloads."
                ),
                toolbox_summary=(
                    "Read-only diagnostic log tools: tail recent sanitized records, "
                    "query by time and structured fields, inspect bounded context, "
                    "and count event/error frequencies. "
                    + render_tool_descriptions(DIAGNOSTIC_LOGS_TOOLBOX)
                ),
                task_complexity=TaskComplexity.COMPLEX,
                guideline_scopes=("global", "agent:log_diagnostic"),
                guideline_include_categories=(),
                toolbox=DIAGNOSTIC_LOGS_TOOLBOX,
            ),
            guideline_service=guideline_service,
        )
        self.navigator = navigator
        self.max_tool_calls = max(0, int(max_tool_calls))

    @traceable(name="Log Diagnostic Agent Handle", run_type="chain")
    def handle(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent | None = None,
        task_complexity: TaskComplexity | None = None,
    ) -> AgentResponse:
        resolved_intent = intent or AgentIntent(kind=IntentKind.DEBUG_LOGS)
        complexity = task_complexity or TaskComplexity.COMPLEX
        set_trace_name(f"{self.__class__.__name__}.handle")
        set_trace_metadata(
            agent_name=self.name,
            agent_kind="specialist",
            intent_kind=resolved_intent.kind.value,
            task_complexity=complexity.value,
            workflow="log_diagnostics",
        )
        if self.navigator is None or not self.navigator.available():
            return AgentResponse(
                final_answer=(
                    "Diagnostic logs are not configured or the current log file is "
                    "unavailable. Check APP_LOG_FILE_PATH and whether app logging has "
                    "written a file for this runtime."
                ),
                selected_agent=self.name,
                metadata={
                    "workflow": "log_diagnostics",
                    "workflow_status": "unavailable",
                },
                artifacts={"workflow": "log_diagnostics"},
            )

        final_answer = self.reasoner.orchestrate_with_tools(
            agent_name=self.profile.name,
            purpose=self.profile.purpose,
            guidelines=self.profile.guidelines,
            toolbox_summary=self.profile.toolbox_summary,
            user_request=request.user_message,
            toolbox=DIAGNOSTIC_LOGS_TOOLBOX,
            tools_mapping=build_diagnostic_logs_tool_mapping(self.navigator),
            chat_history=self._history_for_prompt(request.history),
            persistent_guidance=self._persistent_guidance(),
            max_tool_calls=self.max_tool_calls,
        )
        if not final_answer.strip():
            final_answer = (
                "I could not determine the failure from the available diagnostic logs. "
                "Try again with a timestamp, chat_id, message_id, request_id, or error code."
            )
        return AgentResponse(
            final_answer=final_answer,
            selected_agent=self.name,
            metadata={
                "workflow": "log_diagnostics",
                "workflow_status": "ok",
                "execution_mode": "tool_orchestration",
            },
            artifacts={"workflow": "log_diagnostics"},
        )

