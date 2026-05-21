"""Factory helpers for building specialist agents."""

from __future__ import annotations

from t212ai.capabilities.protocols import BrokerExecutionService, BrokerReadService
from t212ai.genai.tools.base import ToolBox
from t212ai.guidelines.service import GuidelineMemoryService
from t212ai.pending_actions import PendingActionService
from t212ai.proposals import ProposalService
from t212ai.scheduler.service import ScheduledProcessService
from t212ai.workflows import PendingOrdersReviewWorkflow, PortfolioSummaryWorkflow

from ..configurable import ConfigurablePlannerAgent, ConfigurableReasonerAgent
from ..execution import GroupedPlanExecutor
from ..guideline_memory import GuidelineMemoryAgent
from ..reasoning import AgentReasoner
from ..specialists import (
    CalculatorAgent,
    CompanyAnalystAgent,
    LogDiagnosticAgent,
    MarketAnalystAgent,
    OrderAgent,
    PortfolioAnalystAgent,
    RedditResearchAgent,
    SchedulerAgent,
)
from .registry import SpecialistAgents


def build_specialist_agents(
    reasoner: AgentReasoner,
    *,
    guideline_service: GuidelineMemoryService | None = None,
    calculator_agent: CalculatorAgent | None = None,
    portfolio_summary_workflow: PortfolioSummaryWorkflow | None = None,
    pending_orders_review_workflow: PendingOrdersReviewWorkflow | None = None,
    broker_read_service: BrokerReadService | None = None,
    broker_execution_service: BrokerExecutionService | None = None,
    market_data_service=None,
    market_signal_service=None,
    configurable_reasoner_agent: ConfigurableReasonerAgent | None = None,
    configurable_planner_agent: ConfigurablePlannerAgent | None = None,
    grouped_plan_executor: GroupedPlanExecutor | None = None,
    broker_provider: str = "broker",
    pending_action_service: PendingActionService | None = None,
    proposal_service: ProposalService | None = None,
    scheduled_process_service: ScheduledProcessService | None = None,
    log_diagnostic_agent: LogDiagnosticAgent | None = None,
    reddit_research_service=None,
    reddit_research_max_tool_calls: int = 8,
    scheduler_default_timezone: str = "UTC",
    scheduler_default_poll_every_seconds: int = 300,
    portfolio_toolbox_summary: str | None = None,
    order_toolbox: ToolBox | None = None,
    order_toolbox_summary: str | None = None,
    market_toolbox: ToolBox | None = None,
    market_toolbox_summary: str | None = None,
    company_toolbox_summary: str | None = None,
) -> SpecialistAgents:
    if guideline_service is None:
        guideline_service = GuidelineMemoryService.from_path("data/guidelines/guidelines.json")
    reddit_research_agent = (
        RedditResearchAgent(
            reasoner,
            guideline_service=guideline_service,
            reddit_service=reddit_research_service,
            max_tool_calls=reddit_research_max_tool_calls,
        )
        if reddit_research_service is not None
        else None
    )
    return SpecialistAgents(
        portfolio=PortfolioAnalystAgent(
            reasoner,
            guideline_service=guideline_service,
            portfolio_summary_workflow=portfolio_summary_workflow,
            toolbox_summary=portfolio_toolbox_summary,
        ),
        order=OrderAgent(
            reasoner,
            guideline_service=guideline_service,
            pending_orders_review_workflow=pending_orders_review_workflow,
            broker_read_service=broker_read_service,
            broker_execution_service=broker_execution_service,
            market_data_service=market_data_service,
            broker_provider=broker_provider,
            pending_action_service=pending_action_service,
            proposal_service=proposal_service,
            toolbox=order_toolbox,
            toolbox_summary=order_toolbox_summary,
            configurable_reasoner_agent=configurable_reasoner_agent,
            configurable_planner_agent=configurable_planner_agent,
            grouped_plan_executor=grouped_plan_executor,
        ),
        market=MarketAnalystAgent(
            reasoner,
            guideline_service=guideline_service,
            market_data_service=market_data_service,
            market_signal_service=market_signal_service,
            toolbox=market_toolbox,
            toolbox_summary=market_toolbox_summary,
            configurable_reasoner_agent=configurable_reasoner_agent,
            configurable_planner_agent=configurable_planner_agent,
            grouped_plan_executor=grouped_plan_executor,
            reddit_research_agent=reddit_research_agent,
        ),
        company=CompanyAnalystAgent(
            reasoner,
            guideline_service=guideline_service,
            toolbox_summary=company_toolbox_summary,
        ),
        guideline_memory=GuidelineMemoryAgent(reasoner, guideline_service),
        calculator=calculator_agent or CalculatorAgent(
            reasoner,
            guideline_service=guideline_service,
        ),
        scheduler=(
            SchedulerAgent(
                reasoner,
                guideline_service=guideline_service,
                scheduled_process_service=scheduled_process_service,
                default_timezone=scheduler_default_timezone,
                default_poll_every_seconds=scheduler_default_poll_every_seconds,
            )
            if scheduled_process_service is not None
            else None
        ),
        log_diagnostic=log_diagnostic_agent,
        reddit_research=reddit_research_agent,
    )
