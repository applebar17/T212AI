from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from t212ai.agent import (
    AgentJudge,
    AgentReasoner,
    CalculatorAgent,
    ChatHistoryManager,
    ChatHistoryJournal,
    CompanyAnalystAgent,
    ConfigurablePlannerAgent,
    ConfigurableReasonerAgent,
    GroupedPlanExecutor,
    LogDiagnosticAgent,
    MainOrchestratorAgent,
    MarketAnalystAgent,
    NewsIngestionJudgeAgent,
    NewsJudgeDependencies,
    SchedulerAgent,
    SpecialistAgents,
    build_specialist_agents,
)
from t212ai.alpaca import AlpacaBrokerClient, AlpacaMarketDataClient, AlpacaStreamClient
from t212ai.app.alpaca_news_stream_supervisor import AlpacaNewsStreamSupervisor
from t212ai.alpaca.broker import AlpacaBrokerService
from t212ai.agent.tooling import SpecialistTooling, build_specialist_tooling
from t212ai.brokers.trading212 import Trading212BrokerService, Trading212Client
from t212ai.calculator import CalculatorService
from t212ai.capabilities import (
    AlpacaMarketDataService,
    AlphaVantageMarketIntelligenceService,
    BrokerExecutionService,
    BrokerReadService,
    CapabilityBinding,
    CommunityResearchService,
    DisclosureService,
    EdgarDisclosureService,
    MarketDataService,
    MarketIntelligenceService,
    OpenFigiReferenceDataService,
    ReferenceDataService,
    SearchService,
    SearxngSearchService,
    YahooMarketDataService,
)
from t212ai.data_sources.alpha_vantage import AlphaVantageClient
from t212ai.data_sources.reddit import RedditClient, RedditResearchService
from t212ai.data_sources.sec_edgar import EdgarInsiderManager, SecEdgarClient
from t212ai.data_sources.yahoo import YahooFinanceClient
from t212ai.diagnostics import LogFileNavigator
from t212ai.genai import GenAIClient, genai_settings_from_app_settings
from t212ai.genai.tools import build_toolboxes
from t212ai.guidelines.service import (
    GuidelineMemoryService,
    build_empty_guideline_document,
)
from t212ai.market_signals import MarketSignalService
from t212ai.pending_actions import PendingActionService
from t212ai.persistence.documents import FileBackedStructuredDocumentStore
from t212ai.persistence.database import build_engine, build_session_factory, ensure_schema
from t212ai.proposals import ProposalService
from t212ai.reference_data import OpenFigiClient
from t212ai.reconciliation import ReconciliationService
from t212ai.scheduler import (
    ScheduledProcessService,
    SchedulerNotificationService,
    TelegramSchedulerNotifier,
)
from t212ai.workflows import PendingOrdersReviewWorkflow, PortfolioSummaryWorkflow

try:
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session, sessionmaker
except Exception:  # pragma: no cover - only hit without db extras
    Engine = object  # type: ignore[assignment,misc]
    Session = object  # type: ignore[assignment,misc]
    sessionmaker = object  # type: ignore[assignment,misc]

from .bootstrap import (
    ConfigAssessment,
    StartupPreflight,
    assess_settings,
    ensure_runtime_directories,
    preflight_run_bot,
)
from .config import AppSettings, get_app_settings

if TYPE_CHECKING:
    from t212ai.genai.tools.base import ToolBox


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
    openfigi_client: OpenFigiClient | None = None
    reference_data_service: ReferenceDataService | None = None
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


def build_runtime(settings: AppSettings | None = None) -> AppRuntime:
    resolved_settings = settings or get_app_settings()
    config_assessment = assess_settings(resolved_settings)
    startup_preflight = preflight_run_bot(config_assessment)
    ensure_runtime_directories(resolved_settings)

    guideline_document_store = FileBackedStructuredDocumentStore(
        resolved_settings.guideline_memory_path,
        document_factory=build_empty_guideline_document,
    )
    guideline_memory_service = GuidelineMemoryService(guideline_document_store)
    history_manager = ChatHistoryManager()
    component_errors: dict[str, str] = {}
    startup_notes = _collect_startup_notes(config_assessment)

    runtime = AppRuntime(
        settings=resolved_settings,
        config_assessment=config_assessment,
        startup_preflight=startup_preflight,
        guideline_document_store=guideline_document_store,
        guideline_memory_service=guideline_memory_service,
        history_manager=history_manager,
        component_errors=component_errors,
        startup_notes=startup_notes,
    )

    _build_genai_stack(runtime)
    _build_database_stack(runtime)
    _build_market_signal_stack(runtime)
    _build_scheduler_stack(runtime)
    _build_broker_stack(runtime)
    _build_data_source_stack(runtime)
    _build_capability_stack(runtime)
    _build_workflow_stack(runtime)
    _build_scheduler_notification_stack(runtime)
    _build_capability_stack(runtime)
    _build_toolbox_stack(runtime)
    _build_calculator_stack(runtime)
    _build_reconciliation_stack(runtime)
    _build_agent_stack(runtime)
    _build_alpaca_news_stream_supervisor_stack(runtime)
    return runtime


def _build_genai_stack(runtime: AppRuntime) -> None:
    try:
        client = GenAIClient(settings=genai_settings_from_app_settings(runtime.settings))
    except Exception as exc:
        runtime.component_errors["genai_client"] = str(exc)
        return

    runtime.genai_client = client
    runtime.agent_reasoner = AgentReasoner(client)
    runtime.configurable_reasoner_agent = ConfigurableReasonerAgent(client)
    runtime.configurable_planner_agent = ConfigurablePlannerAgent(client)
    runtime.grouped_plan_executor = GroupedPlanExecutor(client)
    runtime.agent_judge = AgentJudge(runtime.agent_reasoner)


def _build_broker_stack(runtime: AppRuntime) -> None:
    provider = str(runtime.settings.broker_provider or "").strip().lower()
    if provider == "none":
        return
    if provider == "trading212":
        try:
            client = Trading212Client.from_settings(runtime.settings)
            service = Trading212BrokerService(client)
        except Exception as exc:
            runtime.component_errors["trading212"] = str(exc)
            return

        runtime.trading212_client = client
        runtime.trading212_service = service
        return
    if provider == "alpaca":
        try:
            client = AlpacaBrokerClient.from_settings(runtime.settings)
            service = AlpacaBrokerService(client)
        except Exception as exc:
            runtime.component_errors["alpaca_broker"] = str(exc)
            return

        runtime.alpaca_broker_client = client
        runtime.alpaca_broker_service = service


def _build_database_stack(runtime: AppRuntime) -> None:
    try:
        engine = build_engine(runtime.settings.database_url)
        ensure_schema(engine)
        session_factory = build_session_factory(engine)
    except Exception as exc:
        runtime.component_errors["database"] = str(exc)
        return

    runtime.db_engine = engine
    runtime.db_session_factory = session_factory


def _build_market_signal_stack(runtime: AppRuntime) -> None:
    if runtime.db_session_factory is None:
        return
    runtime.market_signal_service = MarketSignalService(runtime.db_session_factory)


def _build_scheduler_stack(runtime: AppRuntime) -> None:
    if runtime.db_session_factory is None:
        return
    runtime.scheduled_process_service = ScheduledProcessService(runtime.db_session_factory)


def _build_scheduler_notification_stack(runtime: AppRuntime) -> None:
    if runtime.scheduled_process_service is None:
        return
    capability = runtime.config_assessment.capabilities.get("scheduler_notifications")
    if capability is None or not capability.available:
        return
    try:
        notifier = TelegramSchedulerNotifier.from_settings(runtime.settings)
        runtime.telegram_scheduler_notifier = notifier
        runtime.scheduler_notification_service = SchedulerNotificationService(
            runtime.scheduled_process_service,
            notifier=notifier,
            pending_action_service=runtime.pending_action_service,
            chat_history_journal=ChatHistoryJournal(runtime.history_manager),
        )
    except Exception as exc:
        runtime.component_errors["scheduler_notifications"] = str(exc)


def _build_data_source_stack(runtime: AppRuntime) -> None:
    if runtime.settings.yahoo_enabled:
        try:
            runtime.yahoo_client = YahooFinanceClient()
        except Exception as exc:  # pragma: no cover - constructor is simple
            runtime.component_errors["yahoo"] = str(exc)

    if runtime.settings.market_data_provider == "alpaca":
        try:
            runtime.alpaca_market_data_client = AlpacaMarketDataClient.from_settings(
                runtime.settings
            )
        except Exception as exc:
            runtime.component_errors["alpaca"] = str(exc)

    if runtime.settings.alpaca_api_key and runtime.settings.alpaca_api_secret:
        try:
            runtime.alpaca_stream_client = AlpacaStreamClient.from_settings(runtime.settings)
        except Exception as exc:
            runtime.component_errors["alpaca_stream"] = str(exc)

    if runtime.settings.reference_data_provider == "openfigi":
        try:
            runtime.openfigi_client = OpenFigiClient.from_settings(runtime.settings)
        except Exception as exc:
            runtime.component_errors["openfigi"] = str(exc)

    if runtime.settings.alpha_vantage_enabled:
        try:
            runtime.alpha_vantage_client = AlphaVantageClient.from_settings(runtime.settings)
        except Exception as exc:
            runtime.component_errors["alpha_vantage"] = str(exc)

    if runtime.settings.reddit_enabled:
        try:
            client = RedditClient.from_settings(runtime.settings)
            runtime.reddit_client = client
            runtime.reddit_service = RedditResearchService(client)
        except Exception as exc:
            runtime.component_errors["reddit"] = str(exc)
    if runtime.settings.disclosure_provider == "sec_edgar":
        try:
            client = SecEdgarClient.from_settings(runtime.settings)
            runtime.sec_edgar_client = client
            runtime.insider_manager = EdgarInsiderManager(client)
        except Exception as exc:
            runtime.component_errors["sec_edgar"] = str(exc)


def _build_toolbox_stack(runtime: AppRuntime) -> None:
    runtime.toolboxes = build_toolboxes(
        settings=runtime.settings,
        assessment=runtime.config_assessment,
    )
    runtime.specialist_tooling = build_specialist_tooling(
        settings=runtime.settings,
        assessment=runtime.config_assessment,
    )


def _build_capability_stack(runtime: AppRuntime) -> None:
    broker_provider = runtime.config_assessment.providers["broker"]
    if broker_provider.ready:
        if runtime.trading212_service is not None:
            runtime.broker_read_service = runtime.trading212_service
            runtime.broker_execution_service = runtime.trading212_service
        elif runtime.alpaca_broker_service is not None:
            runtime.broker_read_service = runtime.alpaca_broker_service
            runtime.broker_execution_service = runtime.alpaca_broker_service

    if (
        runtime.config_assessment.capabilities["market_data"].available
        and runtime.settings.market_data_provider == "alpaca"
        and runtime.alpaca_market_data_client is not None
    ):
        runtime.market_data_service = AlpacaMarketDataService(
            runtime.alpaca_market_data_client
        )
    elif (
        runtime.config_assessment.capabilities["market_data"].available
        and runtime.yahoo_client is not None
    ):
        runtime.market_data_service = YahooMarketDataService(runtime.yahoo_client)

    if (
        runtime.config_assessment.capabilities["market_intelligence"].available
        and runtime.alpha_vantage_client is not None
    ):
        runtime.market_intelligence_service = AlphaVantageMarketIntelligenceService(
            runtime.alpha_vantage_client
        )

    if (
        runtime.config_assessment.capabilities["disclosure"].available
        and runtime.insider_manager is not None
    ):
        runtime.disclosure_service = EdgarDisclosureService(runtime.insider_manager)

    if (
        runtime.config_assessment.capabilities["research_community_context"].available
        and runtime.reddit_service is not None
    ):
        runtime.community_research_service = runtime.reddit_service

    if (
        runtime.config_assessment.capabilities["search"].available
        and str(runtime.settings.searxng_base_url or "").strip()
    ):
        runtime.search_service = SearxngSearchService(runtime.settings.searxng_base_url or "")

    if (
        runtime.config_assessment.capabilities["reference_data"].available
        and runtime.openfigi_client is not None
    ):
        runtime.reference_data_service = OpenFigiReferenceDataService(runtime.openfigi_client)

    runtime.capability_registry = {
        "broker_read": CapabilityBinding(
            capability="broker_read",
            selected_provider=_capability_provider(runtime, "broker_read"),
            ready=runtime.broker_read_service is not None,
            implementation=runtime.broker_read_service,
        ),
        "broker_execution": CapabilityBinding(
            capability="broker_execution",
            selected_provider=_capability_provider(runtime, "broker_execution_eligibility"),
            ready=runtime.broker_execution_service is not None,
            implementation=runtime.broker_execution_service,
        ),
        "market_data": CapabilityBinding(
            capability="market_data",
            selected_provider=_capability_provider(runtime, "market_data"),
            ready=runtime.market_data_service is not None,
            implementation=runtime.market_data_service,
        ),
        "market_intelligence": CapabilityBinding(
            capability="market_intelligence",
            selected_provider=_capability_provider(runtime, "market_intelligence"),
            ready=runtime.market_intelligence_service is not None,
            implementation=runtime.market_intelligence_service,
        ),
        "disclosure": CapabilityBinding(
            capability="disclosure",
            selected_provider=_capability_provider(runtime, "disclosure"),
            ready=runtime.disclosure_service is not None,
            implementation=runtime.disclosure_service,
        ),
        "community_research": CapabilityBinding(
            capability="community_research",
            selected_provider=_capability_provider(runtime, "research_community_context"),
            ready=runtime.community_research_service is not None,
            implementation=runtime.community_research_service,
        ),
        "search": CapabilityBinding(
            capability="search",
            selected_provider=_capability_provider(runtime, "search"),
            ready=runtime.search_service is not None,
            implementation=runtime.search_service,
        ),
        "reference_data": CapabilityBinding(
            capability="reference_data",
            selected_provider=_capability_provider(runtime, "reference_data"),
            ready=runtime.reference_data_service is not None,
            implementation=runtime.reference_data_service,
        ),
        "market_signal_memory": CapabilityBinding(
            capability="market_signal_memory",
            selected_provider=_capability_provider(runtime, "market_signal_memory"),
            ready=runtime.market_signal_service is not None,
            implementation=runtime.market_signal_service,
        ),
        "scheduled_processes": CapabilityBinding(
            capability="scheduled_processes",
            selected_provider=_capability_provider(runtime, "scheduled_processes"),
            ready=runtime.scheduled_process_service is not None,
            implementation=runtime.scheduled_process_service,
        ),
        "scheduler_notifications": CapabilityBinding(
            capability="scheduler_notifications",
            selected_provider=_capability_provider(runtime, "scheduler_notifications"),
            ready=runtime.scheduler_notification_service is not None,
            implementation=runtime.scheduler_notification_service,
        ),
        "scheduler_instrument_monitor": CapabilityBinding(
            capability="scheduler_instrument_monitor",
            selected_provider=_capability_provider(runtime, "scheduler_instrument_monitor"),
            ready=(
                runtime.scheduled_process_service is not None
                and runtime.market_data_service is not None
            ),
            implementation=runtime.market_data_service,
        ),
        "scheduler_delegate": CapabilityBinding(
            capability="scheduler_delegate",
            selected_provider=_capability_provider(runtime, "scheduler_delegate"),
            ready=(
                runtime.agent_reasoner is not None
                and runtime.scheduled_process_service is not None
            ),
            implementation=runtime.scheduled_process_service,
        ),
        "scheduler_company_event_analyst": CapabilityBinding(
            capability="scheduler_company_event_analyst",
            selected_provider=_capability_provider(runtime, "scheduler_company_event_analyst"),
            ready=(
                runtime.agent_reasoner is not None
                and runtime.scheduled_process_service is not None
            ),
            implementation=runtime.scheduled_process_service,
        ),
        "scheduler_market_regime_monitor": CapabilityBinding(
            capability="scheduler_market_regime_monitor",
            selected_provider=_capability_provider(runtime, "scheduler_market_regime_monitor"),
            ready=(
                runtime.agent_reasoner is not None
                and runtime.scheduled_process_service is not None
                and runtime.market_data_service is not None
            ),
            implementation=runtime.market_data_service,
        ),
        "scheduler_market_signal_capture": CapabilityBinding(
            capability="scheduler_market_signal_capture",
            selected_provider=_capability_provider(runtime, "scheduler_market_signal_capture"),
            ready=(
                runtime.agent_reasoner is not None
                and runtime.scheduled_process_service is not None
                and runtime.market_signal_service is not None
                and (
                    runtime.search_service is not None
                    or runtime.community_research_service is not None
                    or runtime.disclosure_service is not None
                )
            ),
            implementation=runtime.market_signal_service,
        ),
        "scheduler_trade_setup_monitor": CapabilityBinding(
            capability="scheduler_trade_setup_monitor",
            selected_provider=_capability_provider(runtime, "scheduler_trade_setup_monitor"),
            ready=(
                runtime.agent_reasoner is not None
                and runtime.scheduled_process_service is not None
                and runtime.market_data_service is not None
                and runtime.broker_read_service is not None
                and runtime.broker_execution_service is not None
                and runtime.pending_action_service is not None
                and runtime.proposal_service is not None
                and runtime.scheduler_notification_service is not None
            ),
            implementation=runtime.scheduled_process_service,
        ),
        "scheduler_alpaca_news_monitor": CapabilityBinding(
            capability="scheduler_alpaca_news_monitor",
            selected_provider=_capability_provider(runtime, "scheduler_alpaca_news_monitor"),
            ready=(
                runtime.agent_reasoner is not None
                and runtime.scheduled_process_service is not None
                and runtime.alpaca_stream_client is not None
            ),
            implementation=runtime.alpaca_stream_client,
        ),
    }


def _build_workflow_stack(runtime: AppRuntime) -> None:
    if runtime.broker_read_service is not None:
        provider_label = _display_broker_name(runtime.settings.broker_provider)
        runtime.portfolio_summary_workflow = PortfolioSummaryWorkflow(
            runtime.broker_read_service,
            provider_label=provider_label,
        )
        runtime.pending_orders_review_workflow = PendingOrdersReviewWorkflow(
            runtime.broker_read_service,
            provider_label=provider_label,
        )
    if runtime.db_session_factory is not None:
        runtime.pending_action_service = PendingActionService(
            runtime.db_session_factory,
            broker_service=runtime.broker_execution_service,
            broker_services_by_provider=(
                {runtime.settings.broker_provider: runtime.broker_execution_service}
                if runtime.broker_execution_service is not None
                else None
            ),
        )
        runtime.proposal_service = ProposalService(runtime.db_session_factory)


def _build_calculator_stack(runtime: AppRuntime) -> None:
    runtime.calculator_service = CalculatorService()
    if runtime.agent_reasoner is not None:
        runtime.calculator_agent = CalculatorAgent(
            runtime.agent_reasoner,
            guideline_service=runtime.guideline_memory_service,
            calculator_service=runtime.calculator_service,
        )


def _build_reconciliation_stack(runtime: AppRuntime) -> None:
    if (
        runtime.broker_read_service is None
        or runtime.pending_action_service is None
    ):
        return
    runtime.reconciliation_service = ReconciliationService(
        broker_service=runtime.broker_read_service,
        broker_provider=runtime.settings.broker_provider,
        pending_action_service=runtime.pending_action_service,
        proposal_service=runtime.proposal_service,
    )


def _build_agent_stack(runtime: AppRuntime) -> None:
    if runtime.agent_reasoner is None:
        return
    try:
        log_diagnostic_agent = _build_log_diagnostic_agent(runtime)
        specialists = build_specialist_agents(
            runtime.agent_reasoner,
            guideline_service=runtime.guideline_memory_service,
            calculator_agent=runtime.calculator_agent,
            portfolio_summary_workflow=runtime.portfolio_summary_workflow,
            pending_orders_review_workflow=runtime.pending_orders_review_workflow,
            broker_read_service=runtime.broker_read_service,
            broker_execution_service=runtime.broker_execution_service,
            market_data_service=runtime.market_data_service,
            reference_data_service=runtime.reference_data_service,
            market_signal_service=runtime.market_signal_service,
            configurable_reasoner_agent=runtime.configurable_reasoner_agent,
            configurable_planner_agent=runtime.configurable_planner_agent,
            grouped_plan_executor=runtime.grouped_plan_executor,
            broker_provider=runtime.settings.broker_provider,
            pending_action_service=runtime.pending_action_service,
            proposal_service=runtime.proposal_service,
            scheduled_process_service=runtime.scheduled_process_service,
            log_diagnostic_agent=log_diagnostic_agent,
            scheduler_default_timezone=runtime.settings.scheduler_default_timezone,
            scheduler_default_poll_every_seconds=_positive_int_setting(
                runtime.settings.scheduler_default_poll_every_seconds,
                default=300,
            ),
            portfolio_toolbox_summary=(
                runtime.specialist_tooling.portfolio_toolbox_summary
                if runtime.specialist_tooling is not None
                else None
            ),
            order_toolbox=(
                runtime.specialist_tooling.order_toolbox
                if runtime.specialist_tooling is not None
                else None
            ),
            order_toolbox_summary=(
                runtime.specialist_tooling.order_toolbox_summary
                if runtime.specialist_tooling is not None
                else None
            ),
            market_toolbox=(
                runtime.specialist_tooling.market_toolbox
                if runtime.specialist_tooling is not None
                else None
            ),
            market_toolbox_summary=(
                runtime.specialist_tooling.market_toolbox_summary
                if runtime.specialist_tooling is not None
                else None
            ),
            company_toolbox_summary=(
                runtime.specialist_tooling.company_toolbox_summary
                if runtime.specialist_tooling is not None
                else None
            ),
        )
        runtime.main_orchestrator = MainOrchestratorAgent(
            runtime.agent_reasoner,
            guideline_service=runtime.guideline_memory_service,
            specialists=specialists,
            scheduled_process_service=(
                runtime.scheduled_process_service
                if runtime.capability_registry.get("scheduler_alpaca_news_monitor")
                and runtime.capability_registry["scheduler_alpaca_news_monitor"].ready
                else None
            ),
            scheduler_default_timezone=runtime.settings.scheduler_default_timezone,
            scheduler_default_poll_every_seconds=_positive_int_setting(
                runtime.settings.scheduler_default_poll_every_seconds,
                default=300,
            ),
        )
        runtime.specialist_agents = specialists
        runtime.company_agent = specialists.company
        runtime.market_agent = specialists.market
        runtime.scheduler_agent = specialists.scheduler
        runtime.log_diagnostic_agent = specialists.log_diagnostic
        runtime.news_judge_agent = NewsIngestionJudgeAgent(
            runtime.agent_reasoner,
            guideline_service=runtime.guideline_memory_service,
            dependencies=NewsJudgeDependencies(
                market_agent=specialists.market,
                order_agent=specialists.order,
                market_signal_service=runtime.market_signal_service,
                broker_read_service=runtime.broker_read_service,
            ),
            configurable_reasoner_agent=runtime.configurable_reasoner_agent,
            configurable_planner_agent=runtime.configurable_planner_agent,
            grouped_plan_executor=runtime.grouped_plan_executor,
            default_timezone=runtime.settings.scheduler_default_timezone,
            max_tool_calls=runtime.settings.alpaca_news_judge_max_tool_calls,
        )
    except Exception as exc:  # pragma: no cover - defensive
        runtime.component_errors["main_orchestrator"] = str(exc)


def _build_alpaca_news_stream_supervisor_stack(runtime: AppRuntime) -> None:
    if not runtime.settings.alpaca_news_stream_supervisor_enabled:
        return
    if (
        runtime.scheduled_process_service is None
        or runtime.alpaca_stream_client is None
        or runtime.news_judge_agent is None
    ):
        return
    runtime.alpaca_news_stream_supervisor = AlpacaNewsStreamSupervisor(
        runtime.scheduled_process_service,
        runtime.alpaca_stream_client,
        runtime.news_judge_agent,
        notification_service=runtime.scheduler_notification_service,
        history_manager=runtime.history_manager,
        poll_seconds=runtime.settings.alpaca_news_stream_supervisor_poll_seconds,
        lease_seconds=runtime.settings.alpaca_news_stream_lease_seconds,
        worker_id=runtime.settings.scheduler_worker_id,
    )


def _build_log_diagnostic_agent(runtime: AppRuntime) -> LogDiagnosticAgent | None:
    if not runtime.settings.log_diagnostic_agent_enabled:
        return None
    navigator = LogFileNavigator(
        runtime.settings.app_log_file_path,
        max_records=runtime.settings.log_diagnostic_max_records,
        max_bytes=runtime.settings.log_diagnostic_max_bytes,
    )
    return LogDiagnosticAgent(
        runtime.agent_reasoner,
        guideline_service=runtime.guideline_memory_service,
        navigator=navigator,
        max_tool_calls=runtime.settings.log_diagnostic_max_tool_calls,
    )


def _collect_startup_notes(assessment: ConfigAssessment) -> tuple[str, ...]:
    notes: list[str] = list(assessment.warnings)
    for provider in assessment.providers.values():
        notes.extend(provider.notes)
    deduped: list[str] = []
    seen: set[str] = set()
    for note in notes:
        normalized = str(note).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return tuple(deduped)


def _positive_int_setting(value: object, *, default: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _capability_provider(runtime: AppRuntime, name: str) -> str | None:
    capability = runtime.config_assessment.capabilities.get(name)
    if capability is None:
        return None
    return capability.selected_provider


def _display_broker_name(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized == "trading212":
        return "Trading 212"
    if normalized == "alpaca":
        return "Alpaca"
    return str(provider or "Broker").replace("_", " ").strip().title() or "Broker"
