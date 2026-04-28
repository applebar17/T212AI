from __future__ import annotations

from dataclasses import dataclass, field

from t212ai.agent import (
    AgentJudge,
    AgentReasoner,
    CalculatorAgent,
    ChatHistoryManager,
    MainOrchestratorAgent,
    build_specialist_agents,
)
from t212ai.brokers.trading212 import Trading212BrokerService, Trading212Client
from t212ai.calculator import CalculatorService
from t212ai.data_sources.alpha_vantage import AlphaVantageClient
from t212ai.data_sources.reddit import RedditClient, RedditResearchService
from t212ai.data_sources.sec_edgar import EdgarInsiderManager, SecEdgarClient
from t212ai.data_sources.yahoo import YahooFinanceClient
from t212ai.genai import GenAIClient, genai_settings_from_app_settings
from t212ai.guidelines.service import (
    GuidelineMemoryService,
    build_empty_guideline_document,
)
from t212ai.pending_actions import PendingActionService
from t212ai.persistence.documents import FileBackedStructuredDocumentStore
from t212ai.persistence.database import build_engine, build_session_factory, ensure_schema
from t212ai.proposals import ProposalService
from t212ai.reconciliation import ReconciliationService
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
    reconciliation_service: ReconciliationService | None = None
    calculator_service: CalculatorService | None = None
    genai_client: GenAIClient | None = None
    agent_reasoner: AgentReasoner | None = None
    agent_judge: AgentJudge | None = None
    main_orchestrator: MainOrchestratorAgent | None = None
    calculator_agent: CalculatorAgent | None = None
    trading212_client: Trading212Client | None = None
    trading212_service: Trading212BrokerService | None = None
    portfolio_summary_workflow: PortfolioSummaryWorkflow | None = None
    pending_orders_review_workflow: PendingOrdersReviewWorkflow | None = None
    yahoo_client: YahooFinanceClient | None = None
    alpha_vantage_client: AlphaVantageClient | None = None
    reddit_client: RedditClient | None = None
    reddit_service: RedditResearchService | None = None
    sec_edgar_client: SecEdgarClient | None = None
    insider_manager: EdgarInsiderManager | None = None
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
        return self.trading212_service is not None

    @property
    def has_market_data_runtime(self) -> bool:
        return any(
            component is not None
            for component in (
                self.yahoo_client,
                self.alpha_vantage_client,
                self.reddit_service,
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
    _build_broker_stack(runtime)
    _build_data_source_stack(runtime)
    _build_workflow_stack(runtime)
    _build_calculator_stack(runtime)
    _build_reconciliation_stack(runtime)
    _build_agent_stack(runtime)
    return runtime


def _build_genai_stack(runtime: AppRuntime) -> None:
    try:
        client = GenAIClient(settings=genai_settings_from_app_settings(runtime.settings))
    except Exception as exc:
        runtime.component_errors["genai_client"] = str(exc)
        return

    runtime.genai_client = client
    runtime.agent_reasoner = AgentReasoner(client)
    runtime.agent_judge = AgentJudge(runtime.agent_reasoner)


def _build_broker_stack(runtime: AppRuntime) -> None:
    if runtime.settings.broker_provider != "trading212":
        return
    try:
        client = Trading212Client.from_settings(runtime.settings)
        service = Trading212BrokerService(client)
    except Exception as exc:
        runtime.component_errors["trading212"] = str(exc)
        return

    runtime.trading212_client = client
    runtime.trading212_service = service


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


def _build_data_source_stack(runtime: AppRuntime) -> None:
    if runtime.settings.yahoo_enabled:
        try:
            runtime.yahoo_client = YahooFinanceClient()
        except Exception as exc:  # pragma: no cover - constructor is simple
            runtime.component_errors["yahoo"] = str(exc)

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
    try:
        client = SecEdgarClient.from_settings(runtime.settings)
        runtime.sec_edgar_client = client
        runtime.insider_manager = EdgarInsiderManager(client)
    except Exception as exc:
        runtime.component_errors["sec_edgar"] = str(exc)


def _build_workflow_stack(runtime: AppRuntime) -> None:
    if runtime.trading212_service is not None:
        runtime.portfolio_summary_workflow = PortfolioSummaryWorkflow(runtime.trading212_service)
        runtime.pending_orders_review_workflow = PendingOrdersReviewWorkflow(
            runtime.trading212_service
        )
    if runtime.db_session_factory is not None:
        runtime.pending_action_service = PendingActionService(
            runtime.db_session_factory,
            broker_service=runtime.trading212_service,
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
        runtime.trading212_service is None
        or runtime.pending_action_service is None
    ):
        return
    runtime.reconciliation_service = ReconciliationService(
        broker_service=runtime.trading212_service,
        pending_action_service=runtime.pending_action_service,
        proposal_service=runtime.proposal_service,
    )


def _build_agent_stack(runtime: AppRuntime) -> None:
    if runtime.agent_reasoner is None:
        return
    try:
        specialists = build_specialist_agents(
            runtime.agent_reasoner,
            guideline_service=runtime.guideline_memory_service,
            portfolio_summary_workflow=runtime.portfolio_summary_workflow,
            pending_orders_review_workflow=runtime.pending_orders_review_workflow,
            broker_service=runtime.trading212_service,
            pending_action_service=runtime.pending_action_service,
            proposal_service=runtime.proposal_service,
        )
        runtime.main_orchestrator = MainOrchestratorAgent(
            runtime.agent_reasoner,
            guideline_service=runtime.guideline_memory_service,
            specialists=specialists,
        )
    except Exception as exc:  # pragma: no cover - defensive
        runtime.component_errors["main_orchestrator"] = str(exc)


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
