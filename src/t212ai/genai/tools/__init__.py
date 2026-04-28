"""Reusable GenAI tool definitions and mappings.

The package keeps exports lazy so provider-specific tool modules can import
`t212ai.genai.tools.base` without forcing the full generic tool registry to load
and creating circular imports.
"""

from __future__ import annotations

from typing import Any


__all__ = [
    "ToolBox",
    "SearchResultRegistry",
    "CHAT_TOOLBOX",
    "RESEARCH_TOOLBOX",
    "MARKET_ANALYST_TOOLBOX",
    "MARKET_DATA_TOOLBOX",
    "YAHOO_MARKET_CONTEXT_TOOLBOX",
    "TOOLBOXES",
    "build_tool_mapping",
    "build_tool_mapping_for",
    "build_chat_toolbox",
    "build_research_toolbox",
    "build_market_data_toolbox",
    "build_yahoo_market_context_toolbox",
    "build_market_analyst_toolbox",
    "build_toolboxes",
    "SEARXNG_SEARCH_TOOL",
    "searxng_search",
    "SCRAPE_ARTICLE_TOOL",
    "scrape_article",
    "MARKET_SEARCH_SYMBOL_TOOL",
    "MARKET_GET_QUOTE_TOOL",
    "MARKET_GET_BARS_TOOL",
    "MARKET_GET_VOLUME_MONITOR_TOOL",
    "MARKET_GET_MARKET_SNAPSHOT_TOOL",
    "MARKET_GET_CHART_CONTEXT_TOOL",
    "market_search_symbol",
    "market_get_quote",
    "market_get_bars",
    "market_get_volume_monitor",
    "market_get_market_snapshot",
    "market_get_chart_context",
    "YAHOO_PRICE_HISTORY_TOOL",
    "YAHOO_PRICE_SUMMARY_TOOL",
    "YAHOO_PRICE_SUMMARY_WITH_CHART_REFS_TOOL",
    "YAHOO_SYMBOL_SEARCH_TOOL",
    "YAHOO_QUOTE_SNAPSHOT_TOOL",
    "YAHOO_MARKET_SNAPSHOT_TOOL",
    "YAHOO_VOLUME_MONITOR_TOOL",
    "YAHOO_OPTIONS_SNAPSHOT_TOOL",
    "YAHOO_ANALYST_SNAPSHOT_TOOL",
    "yahoo_price_history",
    "yahoo_price_summary",
    "yahoo_price_summary_with_chart_refs",
    "yahoo_symbol_search",
    "yahoo_quote_snapshot",
    "yahoo_market_snapshot",
    "yahoo_volume_monitor",
    "yahoo_options_snapshot",
    "yahoo_analyst_snapshot",
]


def __getattr__(name: str) -> Any:
    if name == "SearchResultRegistry":
        from .search_registry import SearchResultRegistry

        return SearchResultRegistry

    if name in {"SEARXNG_SEARCH_TOOL", "searxng_search"}:
        from .searxng import SEARXNG_SEARCH_TOOL, searxng_search

        exports = {
            "SEARXNG_SEARCH_TOOL": SEARXNG_SEARCH_TOOL,
            "searxng_search": searxng_search,
        }
        return exports[name]

    if name in {
        "MARKET_SEARCH_SYMBOL_TOOL",
        "MARKET_GET_QUOTE_TOOL",
        "MARKET_GET_BARS_TOOL",
        "MARKET_GET_VOLUME_MONITOR_TOOL",
        "MARKET_GET_MARKET_SNAPSHOT_TOOL",
        "MARKET_GET_CHART_CONTEXT_TOOL",
        "market_search_symbol",
        "market_get_quote",
        "market_get_bars",
        "market_get_volume_monitor",
        "market_get_market_snapshot",
        "market_get_chart_context",
    }:
        from .market_data import (
            MARKET_GET_BARS_TOOL,
            MARKET_GET_CHART_CONTEXT_TOOL,
            MARKET_GET_MARKET_SNAPSHOT_TOOL,
            MARKET_GET_QUOTE_TOOL,
            MARKET_GET_VOLUME_MONITOR_TOOL,
            MARKET_SEARCH_SYMBOL_TOOL,
            market_get_bars,
            market_get_chart_context,
            market_get_market_snapshot,
            market_get_quote,
            market_get_volume_monitor,
            market_search_symbol,
        )

        exports = {
            "MARKET_SEARCH_SYMBOL_TOOL": MARKET_SEARCH_SYMBOL_TOOL,
            "MARKET_GET_QUOTE_TOOL": MARKET_GET_QUOTE_TOOL,
            "MARKET_GET_BARS_TOOL": MARKET_GET_BARS_TOOL,
            "MARKET_GET_VOLUME_MONITOR_TOOL": MARKET_GET_VOLUME_MONITOR_TOOL,
            "MARKET_GET_MARKET_SNAPSHOT_TOOL": MARKET_GET_MARKET_SNAPSHOT_TOOL,
            "MARKET_GET_CHART_CONTEXT_TOOL": MARKET_GET_CHART_CONTEXT_TOOL,
            "market_search_symbol": market_search_symbol,
            "market_get_quote": market_get_quote,
            "market_get_bars": market_get_bars,
            "market_get_volume_monitor": market_get_volume_monitor,
            "market_get_market_snapshot": market_get_market_snapshot,
            "market_get_chart_context": market_get_chart_context,
        }
        return exports[name]

    if name in {"SCRAPE_ARTICLE_TOOL", "scrape_article"}:
        from .scrape_article import SCRAPE_ARTICLE_TOOL, scrape_article

        exports = {
            "SCRAPE_ARTICLE_TOOL": SCRAPE_ARTICLE_TOOL,
            "scrape_article": scrape_article,
        }
        return exports[name]

    if name in {
        "YAHOO_PRICE_HISTORY_TOOL",
        "YAHOO_PRICE_SUMMARY_TOOL",
        "YAHOO_PRICE_SUMMARY_WITH_CHART_REFS_TOOL",
        "YAHOO_SYMBOL_SEARCH_TOOL",
        "YAHOO_QUOTE_SNAPSHOT_TOOL",
        "YAHOO_MARKET_SNAPSHOT_TOOL",
        "YAHOO_VOLUME_MONITOR_TOOL",
        "YAHOO_OPTIONS_SNAPSHOT_TOOL",
        "YAHOO_ANALYST_SNAPSHOT_TOOL",
        "yahoo_price_history",
        "yahoo_price_summary",
        "yahoo_price_summary_with_chart_refs",
        "yahoo_symbol_search",
        "yahoo_quote_snapshot",
        "yahoo_market_snapshot",
        "yahoo_volume_monitor",
        "yahoo_options_snapshot",
        "yahoo_analyst_snapshot",
    }:
        from .yahoo_finance import (
            YAHOO_ANALYST_SNAPSHOT_TOOL,
            YAHOO_MARKET_SNAPSHOT_TOOL,
            YAHOO_OPTIONS_SNAPSHOT_TOOL,
            YAHOO_PRICE_HISTORY_TOOL,
            YAHOO_PRICE_SUMMARY_TOOL,
            YAHOO_PRICE_SUMMARY_WITH_CHART_REFS_TOOL,
            YAHOO_QUOTE_SNAPSHOT_TOOL,
            YAHOO_SYMBOL_SEARCH_TOOL,
            YAHOO_VOLUME_MONITOR_TOOL,
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

        exports = {
            "YAHOO_PRICE_HISTORY_TOOL": YAHOO_PRICE_HISTORY_TOOL,
            "YAHOO_PRICE_SUMMARY_TOOL": YAHOO_PRICE_SUMMARY_TOOL,
            "YAHOO_PRICE_SUMMARY_WITH_CHART_REFS_TOOL": YAHOO_PRICE_SUMMARY_WITH_CHART_REFS_TOOL,
            "YAHOO_SYMBOL_SEARCH_TOOL": YAHOO_SYMBOL_SEARCH_TOOL,
            "YAHOO_QUOTE_SNAPSHOT_TOOL": YAHOO_QUOTE_SNAPSHOT_TOOL,
            "YAHOO_MARKET_SNAPSHOT_TOOL": YAHOO_MARKET_SNAPSHOT_TOOL,
            "YAHOO_VOLUME_MONITOR_TOOL": YAHOO_VOLUME_MONITOR_TOOL,
            "YAHOO_OPTIONS_SNAPSHOT_TOOL": YAHOO_OPTIONS_SNAPSHOT_TOOL,
            "YAHOO_ANALYST_SNAPSHOT_TOOL": YAHOO_ANALYST_SNAPSHOT_TOOL,
            "yahoo_price_history": yahoo_price_history,
            "yahoo_price_summary": yahoo_price_summary,
            "yahoo_price_summary_with_chart_refs": yahoo_price_summary_with_chart_refs,
            "yahoo_symbol_search": yahoo_symbol_search,
            "yahoo_quote_snapshot": yahoo_quote_snapshot,
            "yahoo_market_snapshot": yahoo_market_snapshot,
            "yahoo_volume_monitor": yahoo_volume_monitor,
            "yahoo_options_snapshot": yahoo_options_snapshot,
            "yahoo_analyst_snapshot": yahoo_analyst_snapshot,
        }
        return exports[name]

    if name in {
        "ToolBox",
        "CHAT_TOOLBOX",
        "RESEARCH_TOOLBOX",
        "MARKET_ANALYST_TOOLBOX",
        "MARKET_DATA_TOOLBOX",
        "YAHOO_MARKET_CONTEXT_TOOLBOX",
        "TOOLBOXES",
        "build_tool_mapping",
        "build_tool_mapping_for",
        "build_chat_toolbox",
        "build_research_toolbox",
        "build_market_data_toolbox",
        "build_yahoo_market_context_toolbox",
        "build_market_analyst_toolbox",
        "build_toolboxes",
    }:
        from .tools import (
            CHAT_TOOLBOX,
            MARKET_ANALYST_TOOLBOX,
            MARKET_DATA_TOOLBOX,
            RESEARCH_TOOLBOX,
            TOOLBOXES,
            ToolBox,
            YAHOO_MARKET_CONTEXT_TOOLBOX,
            build_chat_toolbox,
            build_market_analyst_toolbox,
            build_market_data_toolbox,
            build_tool_mapping,
            build_tool_mapping_for,
            build_research_toolbox,
            build_toolboxes,
            build_yahoo_market_context_toolbox,
        )

        exports = {
            "ToolBox": ToolBox,
            "CHAT_TOOLBOX": CHAT_TOOLBOX,
            "RESEARCH_TOOLBOX": RESEARCH_TOOLBOX,
            "MARKET_ANALYST_TOOLBOX": MARKET_ANALYST_TOOLBOX,
            "MARKET_DATA_TOOLBOX": MARKET_DATA_TOOLBOX,
            "YAHOO_MARKET_CONTEXT_TOOLBOX": YAHOO_MARKET_CONTEXT_TOOLBOX,
            "TOOLBOXES": TOOLBOXES,
            "build_tool_mapping": build_tool_mapping,
            "build_tool_mapping_for": build_tool_mapping_for,
            "build_chat_toolbox": build_chat_toolbox,
            "build_research_toolbox": build_research_toolbox,
            "build_market_data_toolbox": build_market_data_toolbox,
            "build_yahoo_market_context_toolbox": build_yahoo_market_context_toolbox,
            "build_market_analyst_toolbox": build_market_analyst_toolbox,
            "build_toolboxes": build_toolboxes,
        }
        return exports[name]

    raise AttributeError(f"module 't212ai.genai.tools' has no attribute {name!r}")
