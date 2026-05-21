"""Runtime container model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session, sessionmaker

    from t212ai.agent import (
        AgentJudge,
        AgentReasoner,
        CalculatorAgent,
        ChatHistoryManager,
        CompanyAnalystAgent,
        ConfigurablePlannerAgent,
        ConfigurableReasonerAgent,
        GroupedPlanExecutor,
        LogDiagnosticAgent,
        MainOrchestratorAgent,
        MarketAnalystAgent,
        NewsIngestionJudgeAgent,
        RedditResearchAgent,
        SchedulerAgent,
        SpecialistAgents,
    )
    from t212ai.alpaca import AlpacaBrokerClient, AlpacaMarketDataClient, AlpacaStreamClient
    from t212ai.alpaca.broker import AlpacaBrokerService
    from t212ai.app.alpaca_news_stream_supervisor import AlpacaNewsStreamSupervisor
    from t212ai.app.bootstrap import ConfigAssessment, StartupPreflight
    from t212ai.app.config import AppSettings
    from t212ai.agent.tooling import SpecialistTooling
    from t212ai.brokers.trading212 import Trading212BrokerService, Trading212Client
    from t212ai.calculator import CalculatorService
    from t212ai.capabilities import (
        BrokerExecutionService,
        BrokerReadService,
        CapabilityBinding,
        CommunityResearchService,
        DisclosureService,
        MarketDataService,
        MarketIntelligenceService,
        SearchService,
    )
    from t212ai.data_sources.alpha_vantage import AlphaVantageClient
    from t212ai.data_sources.reddit import RedditClient, RedditResearchService
    from t212ai.data_sources.sec_edgar import EdgarInsiderManager, SecEdgarClient
    from t212ai.data_sources.yahoo import YahooFinanceClient
    from t212ai.genai import GenAIClient
    from t212ai.genai.tools.base import ToolBox
    from t212ai.guidelines.service import GuidelineMemoryService
    from t212ai.market_signals import MarketSignalService
    from t212ai.pending_actions import PendingActionService
    from t212ai.persistence.documents import FileBackedStructuredDocumentStore
    from t212ai.proposals import ProposalService
    from t212ai.reconciliation import ReconciliationService
    from t212ai.scheduler import (
        ScheduledProcessService,
        SchedulerNotificationService,
        TelegramSchedulerNotifier,
    )
    from t212ai.workflows import PendingOrdersReviewWorkflow, PortfolioSummaryWorkflow


@dataclass(slots=True)
class AppRuntime:
    settings: AppSettings
    config_assessment: ConfigAssessment
    startup_preflight: StartupPreflight
    guideline_document_store: FileBackedStructuredDocumentStore
    guideline_memory_service: GuidelineMemoryService
    history_manager: ChatHistoryManager
    db_engine: Engine | None = None
    db_session_factory: sessionmaker[Session] | None = None
    pending_action_service: PendingActionService | None = None
    proposal_service: ProposalService | None = None
    market_signal_service: MarketSignalService | None = None
    scheduled_process_service: ScheduledProcessService | None = None
    scheduler_notification_service: SchedulerNotificationService | None = None
    telegram_scheduler_notifier: TelegramSchedulerNotifier | None = None
    reconciliation_service: ReconciliationService | None = None
    calculator_service: CalculatorService | None = None
    genai_client: GenAIClient | None = None
    agent_reasoner: AgentReasoner | None = None
    configurable_reasoner_agent: ConfigurableReasonerAgent | None = None
    configurable_planner_agent: ConfigurablePlannerAgent | None = None
    grouped_plan_executor: GroupedPlanExecutor | None = None
    agent_judge: AgentJudge | None = None
    specialist_agents: SpecialistAgents | None = None
    main_orchestrator: MainOrchestratorAgent | None = None
    company_agent: CompanyAnalystAgent | None = None
    market_agent: MarketAnalystAgent | None = None
    reddit_research_agent: RedditResearchAgent | None = None
    calculator_agent: CalculatorAgent | None = None
    scheduler_agent: SchedulerAgent | None = None
    log_diagnostic_agent: LogDiagnosticAgent | None = None
    news_judge_agent: NewsIngestionJudgeAgent | None = None
    alpaca_news_stream_supervisor: AlpacaNewsStreamSupervisor | None = None
    trading212_client: Trading212Client | None = None
    trading212_service: Trading212BrokerService | None = None
    alpaca_broker_client: AlpacaBrokerClient | None = None
    alpaca_broker_service: AlpacaBrokerService | None = None
    broker_read_service: BrokerReadService | None = None
    broker_execution_service: BrokerExecutionService | None = None
    portfolio_summary_workflow: PortfolioSummaryWorkflow | None = None
    pending_orders_review_workflow: PendingOrdersReviewWorkflow | None = None
    yahoo_client: YahooFinanceClient | None = None
    alpaca_market_data_client: AlpacaMarketDataClient | None = None
    alpaca_stream_client: AlpacaStreamClient | None = None
    market_data_service: MarketDataService | None = None
    alpha_vantage_client: AlphaVantageClient | None = None
    market_intelligence_service: MarketIntelligenceService | None = None
    reddit_client: RedditClient | None = None
    reddit_service: RedditResearchService | None = None
    community_research_service: CommunityResearchService | None = None
    sec_edgar_client: SecEdgarClient | None = None
    insider_manager: EdgarInsiderManager | None = None
    disclosure_service: DisclosureService | None = None
    search_service: SearchService | None = None
    capability_registry: dict[str, CapabilityBinding] = field(default_factory=dict)
    toolboxes: dict[str, "ToolBox"] = field(default_factory=dict)
    specialist_tooling: SpecialistTooling | None = None
    component_errors: dict[str, str] = field(default_factory=dict)
    startup_notes: tuple[str, ...] = ()

    @property
    def has_agent_runtime(self) -> bool:
        return (
            self.genai_client is not None
            and self.agent_reasoner is not None
            and self.main_orchestrator is not None
        )

    @property
    def has_broker_runtime(self) -> bool:
        return self.broker_read_service is not None or self.broker_execution_service is not None

    @property
    def has_market_data_runtime(self) -> bool:
        return any(
            service is not None
            for service in (
                self.market_data_service,
                self.market_intelligence_service,
                self.community_research_service,
                self.disclosure_service,
                self.search_service,
            )
        )

    @property
    def missing_components(self) -> tuple[str, ...]:
        return tuple(sorted(self.component_errors))
