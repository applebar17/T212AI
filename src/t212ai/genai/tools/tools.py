"""Toolbox definitions and tool-call mappings."""

from __future__ import annotations

from copy import deepcopy
from functools import partial
import os
from typing import Any, Callable

from ..models import ToolError, ToolResult, ToolSpec
from .base import ToolBox, build_tool_index
from .scrape_article import SCRAPE_ARTICLE_TOOL, scrape_article
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


def _build_chat_yahoo_tool() -> ToolSpec:
    tool = deepcopy(YAHOO_PRICE_SUMMARY_WITH_CHART_REFS_TOOL)
    fn = tool.get("function", {})
    description = fn.get("description") or ""
    suffix = (
        " Use this when market data is needed in chat. It returns summary metrics "
        "plus chart placement references and a backing series so a UI can render "
        "price charts automatically."
    )
    fn["description"] = (description + suffix).strip()
    return tool


def build_tool_mapping(
    *,
    embed_fn: Callable[..., Any] | None = None,
    genai_client: Any | None = None,
    runtime: SearchResultRegistry | None = None,
    **_unused: Any,
) -> dict[str, Callable[..., Any]]:
    del embed_fn, genai_client
    yahoo_client = YahooFinanceClient()
    search_registry = runtime
    searxng_base_url = os.getenv("SEARXNG_BASE_URL")
    edgar_runtime = SecEdgarToolRuntime(
        manager=EdgarInsiderManager(SecEdgarClient.from_settings())
    )
    mapping = {
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
        "yahoo_options_snapshot": partial(yahoo_options_snapshot, client=yahoo_client),
        "yahoo_analyst_snapshot": partial(yahoo_analyst_snapshot, client=yahoo_client),
        "searxng_search": partial(
            searxng_search,
            base_url=searxng_base_url,
            runtime=search_registry,
        ),
        "scrape_article": partial(scrape_article, runtime=search_registry),
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


CHAT_TOOLBOX = ToolBox(
    name="chat",
    tools=[
        _build_chat_yahoo_tool(),
        SEARXNG_SEARCH_TOOL,
        SCRAPE_ARTICLE_TOOL,
    ],
    tools_by_name=build_tool_index(
        [
            _build_chat_yahoo_tool(),
            SEARXNG_SEARCH_TOOL,
            SCRAPE_ARTICLE_TOOL,
        ]
    ),
)

RESEARCH_TOOLBOX = ToolBox(
    name="research",
    tools=[SEARXNG_SEARCH_TOOL, SCRAPE_ARTICLE_TOOL, YAHOO_PRICE_SUMMARY_TOOL],
    tools_by_name=build_tool_index(
        [SEARXNG_SEARCH_TOOL, SCRAPE_ARTICLE_TOOL, YAHOO_PRICE_SUMMARY_TOOL]
    ),
)

MARKET_DATA_TOOLBOX = ToolBox(
    name="market_data",
    tools=[
        YAHOO_PRICE_HISTORY_TOOL,
        YAHOO_PRICE_SUMMARY_TOOL,
        YAHOO_PRICE_SUMMARY_WITH_CHART_REFS_TOOL,
        YAHOO_SYMBOL_SEARCH_TOOL,
        YAHOO_QUOTE_SNAPSHOT_TOOL,
        YAHOO_MARKET_SNAPSHOT_TOOL,
        YAHOO_VOLUME_MONITOR_TOOL,
        YAHOO_OPTIONS_SNAPSHOT_TOOL,
        YAHOO_ANALYST_SNAPSHOT_TOOL,
    ],
    tools_by_name=build_tool_index(
        [
            YAHOO_PRICE_HISTORY_TOOL,
            YAHOO_PRICE_SUMMARY_TOOL,
            YAHOO_PRICE_SUMMARY_WITH_CHART_REFS_TOOL,
            YAHOO_SYMBOL_SEARCH_TOOL,
            YAHOO_QUOTE_SNAPSHOT_TOOL,
            YAHOO_MARKET_SNAPSHOT_TOOL,
            YAHOO_VOLUME_MONITOR_TOOL,
            YAHOO_OPTIONS_SNAPSHOT_TOOL,
            YAHOO_ANALYST_SNAPSHOT_TOOL,
        ]
    ),
)

YAHOO_MARKET_CONTEXT_TOOLBOX = ToolBox(
    name="yahoo_market_context",
    tools=YAHOO_MARKET_CONTEXT_TOOLS,
    tools_by_name=build_tool_index(YAHOO_MARKET_CONTEXT_TOOLS),
)

MARKET_ANALYST_TOOLBOX = ToolBox(
    name="market_analyst",
    tools=[
        YAHOO_MARKET_SNAPSHOT_TOOL,
        YAHOO_VOLUME_MONITOR_TOOL,
        ALPHA_VANTAGE_MOST_ACTIVELY_TRADED_TOOL,
        EDGAR_OWNERSHIP_ACTIVITY_TOOL,
        EDGAR_MAJOR_STAKE_ACTIVITY_TOOL,
        EDGAR_COMPANY_DISCLOSURE_SNAPSHOT_TOOL,
        SEARXNG_SEARCH_TOOL,
        SCRAPE_ARTICLE_TOOL,
    ],
    tools_by_name=build_tool_index(
        [
            YAHOO_MARKET_SNAPSHOT_TOOL,
            YAHOO_VOLUME_MONITOR_TOOL,
            ALPHA_VANTAGE_MOST_ACTIVELY_TRADED_TOOL,
            EDGAR_OWNERSHIP_ACTIVITY_TOOL,
            EDGAR_MAJOR_STAKE_ACTIVITY_TOOL,
            EDGAR_COMPANY_DISCLOSURE_SNAPSHOT_TOOL,
            SEARXNG_SEARCH_TOOL,
            SCRAPE_ARTICLE_TOOL,
        ]
    ),
)

TOOLBOXES = {
    CHAT_TOOLBOX.name: CHAT_TOOLBOX,
    RESEARCH_TOOLBOX.name: RESEARCH_TOOLBOX,
    MARKET_DATA_TOOLBOX.name: MARKET_DATA_TOOLBOX,
    YAHOO_MARKET_CONTEXT_TOOLBOX.name: YAHOO_MARKET_CONTEXT_TOOLBOX,
    MARKET_ANALYST_TOOLBOX.name: MARKET_ANALYST_TOOLBOX,
}


def _provider_unavailable_tool(
    *,
    provider: str,
    tool_name: str,
    message: str,
) -> Callable[..., ToolResult]:
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
