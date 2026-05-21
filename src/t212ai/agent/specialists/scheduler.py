"""Scheduler specialist agent."""

from __future__ import annotations

from t212ai.genai.tools.base import render_tool_descriptions
from t212ai.genai.tracing import set_trace_metadata, set_trace_name, traceable
from t212ai.guidelines.service import GuidelineMemoryService
from t212ai.scheduler.management import SCHEDULER_AGENT_TOOLBOX, build_scheduler_agent_tool_mapping
from t212ai.scheduler.service import ScheduledProcessService

from ..base import AgentProfile, BaseAgent
from ..intents import AgentIntent, IntentKind
from ..planner import TaskComplexity
from ..schemas import AgentRequest, AgentResponse
from ..time_context import render_timezone_context


class SchedulerAgent(BaseAgent):
    def __init__(
        self,
        reasoner,
        guideline_service: GuidelineMemoryService | None = None,
        *,
        scheduled_process_service: ScheduledProcessService | None = None,
        default_timezone: str = "UTC",
        default_poll_every_seconds: int = 300,
    ) -> None:
        timezone_context = render_timezone_context(default_timezone)
        super().__init__(
            reasoner,
            AgentProfile(
                name="scheduler_agent",
                purpose=(
                    "Create and manage bounded scheduled trading-related processes "
                    "from natural language."
                ),
                guidelines=(
                    f"{timezone_context} "
                    "Use the private scheduler tools for scheduler changes. Create supported "
                    "instrument_monitor, company_event_analyst, "
                    "market_regime_monitor, market_signal_capture, and "
                    "trade_setup_monitor jobs, plus bounded Alpaca real-time news "
                    "monitors when the user asks to stream/monitor live company news. "
                    "For Alpaca news monitors, if the user does not name ticker symbols, "
                    "use symbols=['*'] to cover all news instead of asking for a ticker "
                    "clarification. "
                    "Instrument monitors use deterministic "
                    "polling schedules. Company-event analyst jobs use llm_assisted "
                    "one-shot or recurring schedules and notify-only action. "
                    "Market-regime monitors use llm_assisted polling schedules, "
                    "notify-only action, ETF proxies for broad labels, and default vague stress "
                    "requests to SPY, percent_change_below=-3, and "
                    "drawdown_from_high_pct=5 unless a clearer market label maps to "
                    "QQQ, DIA, or IWM. Market-signal capture jobs use "
                    "llm_assisted recurring or polling schedules, notify-only action, "
                    "and a bounded scan scope from query, symbols, sectors, or tags; "
                    "captured signals are advisory memory, not fresh market data "
                    "or broker-authoritative state. Trade-setup monitors evaluate "
                    "a deterministic instrument trigger first; proposal creation is "
                    "available only when explicitly requested, requires allowed symbols, "
                    "sides, order types, max notional or quantity caps, and one "
                    "approval chat target, and still never submits an order. Ask one "
                    "concise clarification question if symbol, schedule, market/proxy "
                    "target, setup trigger, proposal permission, risk caps, trigger "
                    "direction, required threshold value, or market-signal capture "
                    "scope is missing or ambiguous. Set "
                    "includeMarketAnalyst only when the user asks for broader market "
                    "impact, reaction, or context. Pause, resume, and archive require "
                    "an exact process_id; if the user refers by symbol or title, list "
                    "candidates and ask the user to choose. Scheduler v1 is notify/proposal "
                    "oriented and does not configure broker actions, autonomous execution, "
                    "direct broker submission, or deletion. "
                    "Responses must state the action result, process_id when created or "
                    "changed, schedule/lifecycle summary, and broker-action status. "
                    "For trade-setup monitors, also state whether pending "
                    "proposal creation is enabled and that future execution requires "
                    "Telegram button approval."
                ),
                toolbox_summary=(
                    "Private scheduler tools: create deterministic instrument monitors, "
                    "create LLM-assisted company-event analyst jobs, create "
                    "conditional market-regime stress monitors, create market-signal "
                    "capture scans, create bounded Alpaca news stream monitors, "
                    "create guarded trade setup monitors, list scheduled "
                    "processes, pause/resume/archive exact process ids. "
                    + render_tool_descriptions(SCHEDULER_AGENT_TOOLBOX)
                ),
                task_complexity=TaskComplexity.COMPLEX,
                guideline_scopes=("global", "agent:scheduler"),
                guideline_include_categories=("investment_preference",),
                toolbox=SCHEDULER_AGENT_TOOLBOX,
            ),
            guideline_service=guideline_service,
        )
        self.scheduled_process_service = scheduled_process_service
        self.default_timezone = default_timezone
        self.default_poll_every_seconds = default_poll_every_seconds

    @traceable(name="Scheduler Agent Handle", run_type="chain")
    def handle(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent | None = None,
        task_complexity: TaskComplexity | None = None,
    ) -> AgentResponse:
        resolved_intent = intent or AgentIntent(kind=IntentKind.MANAGE_SCHEDULED_PROCESSES)
        complexity = task_complexity or self.resolve_complexity(request.user_message)
        set_trace_name(f"{self.__class__.__name__}.handle")
        set_trace_metadata(
            agent_name=self.name,
            agent_kind="specialist",
            intent_kind=resolved_intent.kind.value,
            task_complexity=complexity.value,
            workflow="scheduler_delegation",
        )
        if self.scheduled_process_service is None:
            return AgentResponse(
                final_answer=(
                    "Scheduler is not configured. Set DATABASE_URL and restart the "
                    "runtime to enable scheduled process management."
                ),
                selected_agent=self.name,
                metadata={
                    "workflow": "scheduler_delegation",
                    "workflow_status": "unavailable",
                },
                artifacts={"workflow": "scheduler_delegation"},
            )

        final_answer = self.reasoner.orchestrate_with_tools(
            agent_name=self.profile.name,
            purpose=self.profile.purpose,
            guidelines=self.profile.guidelines,
            toolbox_summary=self.profile.toolbox_summary,
            user_request=request.user_message,
            toolbox=SCHEDULER_AGENT_TOOLBOX,
            tools_mapping=build_scheduler_agent_tool_mapping(
                self.scheduled_process_service,
                default_timezone=self.default_timezone,
                default_poll_every_seconds=self.default_poll_every_seconds,
                chat_id=request.chat_id,
                user_id=_metadata_user_id(request.metadata),
            ),
            chat_history=self._history_for_prompt(request.history),
            persistent_guidance=self._persistent_guidance(),
        )
        if not final_answer.strip():
            final_answer = (
                "I could not complete the scheduler request. No scheduler change was "
                "made unless a tool result above explicitly returned a process_id."
            )
        return AgentResponse(
            final_answer=final_answer,
            selected_agent=self.name,
            metadata={
                "workflow": "scheduler_delegation",
                "workflow_status": "ok",
            },
            artifacts={"workflow": "scheduler_delegation"},
        )

def _metadata_user_id(metadata: dict[str, str]) -> int | None:
    raw = str(metadata.get("telegram_user_id", "")).strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None

