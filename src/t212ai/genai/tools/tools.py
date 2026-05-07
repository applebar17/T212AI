"""Toolbox definitions and tool-call mappings."""

from __future__ import annotations

from copy import deepcopy
from functools import partial
import os
from typing import TYPE_CHECKING, Any, Callable

from t212ai.app.bootstrap import ConfigAssessment, assess_settings
from t212ai.app.config import AppSettings, get_app_settings
from t212ai.genai.tracing import (
    traceable,
)
from t212ai.market_signals import (
    MARKET_SIGNAL_TOOLS,
    build_market_signal_tool_mapping,
)
from ..models import ToolError, ToolResult, ToolSpec
from .base import ToolBox, build_tool_index
from .market_data import (
    GENERIC_MARKET_DATA_TOOLS,
    MARKET_GET_CHART_CONTEXT_TOOL,
    MARKET_GET_MARKET_SNAPSHOT_TOOL,
    MARKET_GET_VOLUME_MONITOR_TOOL,
    build_market_data_tool_mapping,
)
from .scrape_article import SCRAPE_ARTICLE_TOOL, SCRAPE_PAGE_TOOL, scrape_article, scrape_page
from .search_registry import SearchResultRegistry
from .searxng import SEARXNG_SEARCH_TOOL, searxng_search
from t212ai.data_sources.alpha_vantage import (
    ALPHA_VANTAGE_MOST_ACTIVELY_TRADED_TOOL,
    AlphaVantageClient,
    AlphaVantageToolRuntime,
    alpha_vantage_most_actively_traded,
)
from t212ai.data_sources.sec_edgar import (
    EDGAR_COMPANY_DISCLOSURE_SNAPSHOT_TOOL,
    EDGAR_MAJOR_STAKE_ACTIVITY_TOOL,
    EDGAR_OWNERSHIP_ACTIVITY_TOOL,
    EdgarInsiderManager,
    SecEdgarClient,
    SecEdgarToolRuntime,
    edgar_company_disclosure_snapshot,
    edgar_recent_major_stake_activity,
    edgar_recent_ownership_activity,
)
from .yahoo_finance import (
    YAHOO_ANALYST_SNAPSHOT_TOOL,
    YAHOO_MARKET_CONTEXT_TOOLS,
    YAHOO_MARKET_SNAPSHOT_TOOL,
    YAHOO_OPTIONS_SNAPSHOT_TOOL,
    YAHOO_PRICE_HISTORY_TOOL,
    YAHOO_PRICE_SUMMARY_TOOL,
    YAHOO_PRICE_SUMMARY_WITH_CHART_REFS_TOOL,
    YAHOO_QUOTE_SNAPSHOT_TOOL,
    YAHOO_SYMBOL_SEARCH_TOOL,
    YAHOO_VOLUME_MONITOR_TOOL,
    YahooFinanceClient,
    yahoo_analyst_snapshot,
    yahoo_market_snapshot,
    yahoo_options_snapshot,
    yahoo_price_history,
    yahoo_price_summary,
    yahoo_price_summary_with_chart_refs,
    yahoo_quote_snapshot,
    yahoo_symbol_search,
    yahoo_volume_monitor,
)

if TYPE_CHECKING:
    from t212ai.capabilities.protocols import MarketDataService
    from t212ai.market_signals import MarketSignalService


def _market_data_provider_ready(
    settings: AppSettings,
    assessment: ConfigAssessment,
) -> bool:
    selected = _selected_provider(settings.market_data_provider)
    if selected == "none":
        return False
    return _provider_ready(assessment, selected)


def _build_chat_market_chart_tool() -> ToolSpec:
    tool = deepcopy(MARKET_GET_CHART_CONTEXT_TOOL)
    fn = tool.get("function", {})
    description = fn.get("description") or ""
    suffix = (
        " Use this when market data is needed in chat. It returns summary metrics "
        "plus chart placement references and a backing series so a UI can render "
        "price charts automatically."
    )
    fn["description"] = (description + suffix).strip()
    return tool


def _resolve_toolbox_context(
    settings: AppSettings | None,
    assessment: ConfigAssessment | None,
) -> tuple[AppSettings, ConfigAssessment]:
    resolved_settings = settings or get_app_settings()
    resolved_assessment = assessment or assess_settings(resolved_settings)
    return resolved_settings, resolved_assessment


def _provider_ready(assessment: ConfigAssessment, name: str) -> bool:
    provider = assessment.providers.get(name)
    return bool(provider and provider.ready)


def _selected_provider(value: str | None) -> str:
    return str(value or "").strip().lower()


def _resolve_market_data_service(
    *,
    market_data_service: "MarketDataService | None",
    settings: AppSettings | None,
    assessment: ConfigAssessment | None,
) -> "MarketDataService | None":
    if market_data_service is not None:
        return market_data_service
    resolved_settings, resolved_assessment = _resolve_toolbox_context(settings, assessment)
    selected_provider = _selected_provider(resolved_settings.market_data_provider)
    if not _market_data_provider_ready(resolved_settings, resolved_assessment):
        return None
    if selected_provider == "alpaca":
        from t212ai.alpaca.market_data import AlpacaMarketDataClient
        from t212ai.capabilities.services import AlpacaMarketDataService

        return AlpacaMarketDataService(AlpacaMarketDataClient.from_settings(resolved_settings))
    if selected_provider == "yahoo":
        from t212ai.capabilities.services import YahooMarketDataService

        return YahooMarketDataService(YahooFinanceClient())
    return None


def build_chat_toolbox(
    *,
    settings: AppSettings | None = None,
    assessment: ConfigAssessment | None = None,
) -> ToolBox:
    resolved_settings, resolved_assessment = _resolve_toolbox_context(settings, assessment)
    tools: list[ToolSpec] = []
    if _market_data_provider_ready(resolved_settings, resolved_assessment):
        tools.append(_build_chat_market_chart_tool())
    if (
        _selected_provider(resolved_settings.search_provider) == "searxng"
        and _provider_ready(resolved_assessment, "searxng")
    ):
        tools.extend([SEARXNG_SEARCH_TOOL, SCRAPE_PAGE_TOOL, SCRAPE_ARTICLE_TOOL])
    return ToolBox(name="chat", tools=tools, tools_by_name=build_tool_index(tools))


def build_research_toolbox(
    *,
    settings: AppSettings | None = None,
    assessment: ConfigAssessment | None = None,
) -> ToolBox:
    resolved_settings, resolved_assessment = _resolve_toolbox_context(settings, assessment)
    tools: list[ToolSpec] = []
    if (
        _selected_provider(resolved_settings.search_provider) == "searxng"
        and _provider_ready(resolved_assessment, "searxng")
    ):
        tools.extend([SEARXNG_SEARCH_TOOL, SCRAPE_PAGE_TOOL, SCRAPE_ARTICLE_TOOL])
    if (
        _market_data_provider_ready(resolved_settings, resolved_assessment)
    ):
        tools.append(MARKET_GET_MARKET_SNAPSHOT_TOOL)
    return ToolBox(name="research", tools=tools, tools_by_name=build_tool_index(tools))


def build_market_data_toolbox(
    *,
    settings: AppSettings | None = None,
    assessment: ConfigAssessment | None = None,
) -> ToolBox:
    resolved_settings, resolved_assessment = _resolve_toolbox_context(settings, assessment)
    tools: list[ToolSpec] = []
    if _market_data_provider_ready(resolved_settings, resolved_assessment):
        tools.extend(GENERIC_MARKET_DATA_TOOLS)
    return ToolBox(
        name="market_data",
        tools=tools,
        tools_by_name=build_tool_index(tools),
    )


def build_yahoo_market_context_toolbox(
    *,
    settings: AppSettings | None = None,
    assessment: ConfigAssessment | None = None,
) -> ToolBox:
    resolved_settings, resolved_assessment = _resolve_toolbox_context(settings, assessment)
    tools = (
        list(YAHOO_MARKET_CONTEXT_TOOLS)
        if (
            _selected_provider(resolved_settings.market_data_provider) == "yahoo"
            and _provider_ready(resolved_assessment, "yahoo")
        )
        else []
    )
    return ToolBox(
        name="yahoo_market_context",
        tools=tools,
        tools_by_name=build_tool_index(tools),
    )


def build_market_analyst_toolbox(
    *,
    settings: AppSettings | None = None,
    assessment: ConfigAssessment | None = None,
) -> ToolBox:
    resolved_settings, resolved_assessment = _resolve_toolbox_context(settings, assessment)
    tools: list[ToolSpec] = []
    if _market_data_provider_ready(resolved_settings, resolved_assessment):
        tools.extend([MARKET_GET_MARKET_SNAPSHOT_TOOL, MARKET_GET_VOLUME_MONITOR_TOOL])
    if (
        _selected_provider(resolved_settings.market_intelligence_provider)
        == "alpha_vantage"
        and _provider_ready(resolved_assessment, "alpha_vantage")
    ):
        tools.append(ALPHA_VANTAGE_MOST_ACTIVELY_TRADED_TOOL)
    if (
        _selected_provider(resolved_settings.disclosure_provider) == "sec_edgar"
        and _provider_ready(resolved_assessment, "sec_edgar")
    ):
        tools.extend(
            [
                EDGAR_OWNERSHIP_ACTIVITY_TOOL,
                EDGAR_MAJOR_STAKE_ACTIVITY_TOOL,
                EDGAR_COMPANY_DISCLOSURE_SNAPSHOT_TOOL,
            ]
        )
    if (
        _selected_provider(resolved_settings.search_provider) == "searxng"
        and _provider_ready(resolved_assessment, "searxng")
    ):
        tools.extend([SEARXNG_SEARCH_TOOL, SCRAPE_PAGE_TOOL, SCRAPE_ARTICLE_TOOL])
    if resolved_assessment.capabilities["market_signal_memory"].available:
        tools.extend(MARKET_SIGNAL_TOOLS)
    return ToolBox(
        name="market_analyst",
        tools=tools,
        tools_by_name=build_tool_index(tools),
    )


def build_toolboxes(
    *,
    settings: AppSettings | None = None,
    assessment: ConfigAssessment | None = None,
) -> dict[str, ToolBox]:
    chat = build_chat_toolbox(settings=settings, assessment=assessment)
    research = build_research_toolbox(settings=settings, assessment=assessment)
    market_data = build_market_data_toolbox(settings=settings, assessment=assessment)
    market_analyst = build_market_analyst_toolbox(
        settings=settings,
        assessment=assessment,
    )
    return {
        chat.name: chat,
        research.name: research,
        market_data.name: market_data,
        market_analyst.name: market_analyst,
    }


def _build_default_toolboxes() -> dict[str, ToolBox]:
    default_settings = AppSettings()
    default_assessment = assess_settings(default_settings)
    return build_toolboxes(
        settings=default_settings,
        assessment=default_assessment,
    )


def build_tool_mapping(
    *,
    embed_fn: Callable[..., Any] | None = None,
    genai_client: Any | None = None,
    runtime: SearchResultRegistry | None = None,
    settings: AppSettings | None = None,
    assessment: ConfigAssessment | None = None,
    market_data_service: "MarketDataService | None" = None,
    market_signal_service: "MarketSignalService | None" = None,
    **_unused: Any,
) -> dict[str, Callable[..., Any]]:
    del embed_fn, genai_client
    search_registry = runtime
    searxng_base_url = os.getenv("SEARXNG_BASE_URL")
    resolved_market_data_service = _resolve_market_data_service(
        market_data_service=market_data_service,
        settings=settings,
        assessment=assessment,
    )
    yahoo_client = (
        getattr(resolved_market_data_service, "client", None)
        if getattr(resolved_market_data_service, "provider_name", None) == "yahoo"
        else None
    )
    if yahoo_client is None and (
        _selected_provider((settings or get_app_settings()).market_data_provider) == "yahoo"
    ):
        yahoo_client = YahooFinanceClient()
    edgar_runtime = SecEdgarToolRuntime(
        manager=EdgarInsiderManager(SecEdgarClient.from_settings())
    )
    mapping = {
        "searxng_search": partial(
            searxng_search,
            base_url=searxng_base_url,
            runtime=search_registry,
        ),
        "scrape_article": partial(scrape_article, runtime=search_registry),
        "scrape_page": partial(scrape_page, runtime=search_registry),
        "edgar_recent_ownership_activity": partial(
            edgar_recent_ownership_activity,
            runtime=edgar_runtime,
        ),
        "edgar_recent_major_stake_activity": partial(
            edgar_recent_major_stake_activity,
            runtime=edgar_runtime,
        ),
        "edgar_company_disclosure_snapshot": partial(
            edgar_company_disclosure_snapshot,
            runtime=edgar_runtime,
        ),
    }
    mapping.update(build_market_data_tool_mapping(resolved_market_data_service))
    if yahoo_client is not None:
        mapping.update(
            {
                "yahoo_price_history": partial(yahoo_price_history, client=yahoo_client),
                "yahoo_price_summary": partial(yahoo_price_summary, client=yahoo_client),
                "yahoo_price_summary_with_chart_refs": partial(
                    yahoo_price_summary_with_chart_refs,
                    client=yahoo_client,
                ),
                "yahoo_symbol_search": partial(yahoo_symbol_search, client=yahoo_client),
                "yahoo_quote_snapshot": partial(yahoo_quote_snapshot, client=yahoo_client),
                "yahoo_market_snapshot": partial(yahoo_market_snapshot, client=yahoo_client),
                "yahoo_volume_monitor": partial(yahoo_volume_monitor, client=yahoo_client),
                "yahoo_options_snapshot": partial(
                    yahoo_options_snapshot,
                    client=yahoo_client,
                ),
                "yahoo_analyst_snapshot": partial(
                    yahoo_analyst_snapshot,
                    client=yahoo_client,
                ),
            }
        )
    else:
        for tool_name in (
            "yahoo_price_history",
            "yahoo_price_summary",
            "yahoo_price_summary_with_chart_refs",
            "yahoo_symbol_search",
            "yahoo_quote_snapshot",
            "yahoo_market_snapshot",
            "yahoo_volume_monitor",
            "yahoo_options_snapshot",
            "yahoo_analyst_snapshot",
        ):
            mapping[tool_name] = _provider_unavailable_tool(
                provider="yahoo",
                tool_name=tool_name,
                message="Yahoo market-data provider is not configured.",
            )
    try:
        alpha_runtime = AlphaVantageToolRuntime(client=AlphaVantageClient.from_settings())
        mapping["alpha_vantage_most_actively_traded"] = partial(
            alpha_vantage_most_actively_traded,
            runtime=alpha_runtime,
        )
    except Exception as exc:
        mapping["alpha_vantage_most_actively_traded"] = _provider_unavailable_tool(
            provider="alpha_vantage",
            tool_name="alpha_vantage_most_actively_traded",
            message=str(exc),
        )
    try:
        from t212ai.data_sources.reddit import build_reddit_tool_mapping

        mapping.update(build_reddit_tool_mapping())
    except RuntimeError:
        pass
    mapping.update(build_market_signal_tool_mapping(market_signal_service))
    return mapping


def build_tool_mapping_for(
    toolbox: ToolBox,
    *,
    embed_fn: Callable[..., Any] | None = None,
    genai_client: Any | None = None,
    runtime: SearchResultRegistry | None = None,
    session: Any | None = None,
    job_run_id: str | None = None,
    **kwargs: Any,
) -> dict[str, Callable[..., Any]]:
    search_registry = runtime or SearchResultRegistry(
        prefix="url",
        session=session,
        job_run_id=job_run_id,
    )
    mapping = build_tool_mapping(
        embed_fn=embed_fn,
        genai_client=genai_client,
        runtime=search_registry,
        **kwargs,
    )
    allowed = set(toolbox.tools_by_name.keys())
    return {name: handler for name, handler in mapping.items() if name in allowed}

# Compatibility-only static snapshots. Live runtime code should prefer the
# builder functions above so provider readiness drives the visible tool surface.
TOOLBOXES = _build_default_toolboxes()
CHAT_TOOLBOX = TOOLBOXES["chat"]
RESEARCH_TOOLBOX = TOOLBOXES["research"]
MARKET_DATA_TOOLBOX = TOOLBOXES["market_data"]
MARKET_ANALYST_TOOLBOX = TOOLBOXES["market_analyst"]
YAHOO_MARKET_CONTEXT_TOOLBOX = build_yahoo_market_context_toolbox()


def _provider_unavailable_tool(
    *,
    provider: str,
    tool_name: str,
    message: str,
) -> Callable[..., ToolResult]:
    @traceable(
        name="provider_unavailable_tool",
        run_type="tool"
    )
    def _tool(**_kwargs: Any) -> ToolResult:
        return ToolResult(
            status="error",
            output=(
                f"{tool_name} is unavailable because the {provider} provider is not configured."
            ),
            error=ToolError(
                message=message or f"{provider} provider is not configured.",
                code=f"{provider}_not_configured",
                hint="Configure the provider and retry.",
                retryable=False,
            ),
        )

    return _tool
