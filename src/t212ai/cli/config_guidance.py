"""Operator-facing setup guidance for the interactive configuration wizard."""

from __future__ import annotations

from dataclasses import dataclass

from .style import render_box


@dataclass(frozen=True, slots=True)
class ConfigurationGuide:
    title: str
    purpose: str
    ai_usage: str
    obtain: tuple[str, ...]
    references: tuple[str, ...] = ()


def render_configuration_welcome() -> str:
    return render_box(
        "\n".join(
            (
                "Welcome to BrokerAI.",
                "",
                "This wizard configures the local services BrokerAI can use. "
                "BrokerAI is a local AI trading and research copilot: it can "
                "reason over requests, read broker account state, enrich analysis "
                "with market and research data, send Telegram prompts, and persist "
                "scheduler, proposal, and guideline state.",
                "",
                "You stay in control. Credentials are written only to the target "
                "env file, live trading has explicit gates, and the recommended "
                "starting point is demo or paper credentials.",
                "",
                "Each section explains what the configuration controls, how the AI "
                "uses it, and where to get the required values.",
            )
        ),
        title="Welcome",
    )


CONFIGURATION_GUIDES: dict[str, ConfigurationGuide] = {
    "process": ConfigurationGuide(
        title="Configuration purpose",
        purpose=(
            "Build the local .env file that tells brokerai which providers are "
            "enabled, which credentials to use, and which safety limits apply."
        ),
        ai_usage=(
            "The AI uses this configuration to decide which tools are available, "
            "authenticate provider calls, enforce broker/Telegram safety gates, "
            "and persist proposals, schedules, logs, and guidelines."
        ),
        obtain=(
            "Keep the docs/configuration/CLI_CONFIGURATION_WALKTHROUGH.md file open.",
            "Start with paper/demo providers before live credentials.",
            "Paste secrets only into your local .env and never commit that file.",
        ),
    ),
    "llm": ConfigurationGuide(
        title="LLM setup",
        purpose=(
            "Select the reasoning backend used for chat, portfolio analysis, "
            "proposal drafting, routing, and summarization."
        ),
        ai_usage=(
            "When enabled, the AI sends task context to the selected LLM provider "
            "and receives structured reasoning or text responses. With LLM disabled, "
            "only non-LLM operational commands remain useful."
        ),
        obtain=(
            "Choose OpenAI for direct platform keys.",
            "Choose Azure OpenAI when your models are deployed in Azure.",
            "Choose Disabled for storage, scheduler, or local-only inspection work.",
        ),
    ),
    "openai": ConfigurationGuide(
        title="OpenAI credentials",
        purpose="Provide the API key and model ids used for OpenAI reasoning and embeddings.",
        ai_usage=(
            "The AI uses OpenAI chat models for orchestration and analysis, and "
            "the embedding model for vector/search-related memory workflows."
        ),
        obtain=(
            "Sign in to the OpenAI platform.",
            "Open the API keys page and create a project API key.",
            "Copy the key into OPENAI_API_KEY.",
            "Use the wizard's listed model ids unless you have updated the internal registry.",
        ),
        references=(
            "https://platform.openai.com/api-keys",
            "https://developers.openai.com/api/docs/quickstart",
        ),
    ),
    "azure_openai": ConfigurationGuide(
        title="Azure OpenAI credentials",
        purpose=(
            "Provide the Azure OpenAI endpoint, API key, API version, and deployment "
            "names used for chat and embedding calls."
        ),
        ai_usage=(
            "The AI calls Azure OpenAI deployments instead of direct OpenAI model ids. "
            "Deployment names entered here map to the default, smart, reasoning, and "
            "embedding roles used by the app."
        ),
        obtain=(
            "Create or select an Azure OpenAI resource in Azure.",
            "Copy the endpoint and one key from the resource's Keys and Endpoint area.",
            "Deploy the chat and embedding models you need.",
            "Enter Azure deployment names in the model prompts, not raw model ids.",
        ),
        references=(
            "https://learn.microsoft.com/en-us/azure/cognitive-services/openai/"
            "how-to/create-resource",
        ),
    ),
    "observability": ConfigurationGuide(
        title="Observability setup",
        purpose="Control whether model, agent, and tool execution traces are exported.",
        ai_usage=(
            "Tracing helps you inspect how the AI routed a request, which provider "
            "calls happened, which tools ran, and why a workflow failed."
        ),
        obtain=(
            "Leave disabled for the smallest local setup.",
            "Enable LangSmith when debugging provider calls, routing, tool use, "
            "or production runs.",
        ),
    ),
    "langsmith": ConfigurationGuide(
        title="LangSmith credentials",
        purpose="Provide tracing credentials and project routing for LangSmith.",
        ai_usage=(
            "When tracing is enabled, the app records LLM and tool runs so you can "
            "audit agent behavior without relying only on local logs."
        ),
        obtain=(
            "Sign in to LangSmith.",
            "Open settings and create an API key.",
            "Copy the key into LANGSMITH_API_KEY.",
            "Keep the default endpoint unless your workspace uses another region.",
        ),
        references=("https://docs.langchain.com/langsmith/create-account-api-key",),
    ),
    "broker": ConfigurationGuide(
        title="Broker setup",
        purpose=(
            "Select the broker used for account-authoritative reads and prepared "
            "order execution."
        ),
        ai_usage=(
            "The AI uses broker access to read cash, positions, orders, and account "
            "state. It can prepare broker actions, but live execution remains gated "
            "by explicit approval and live-trading settings."
        ),
        obtain=(
            "Choose Trading 212 for the Trading 212 broker adapter.",
            "Choose Alpaca for Alpaca brokerage workflows.",
            "Choose Disabled for research-only mode.",
        ),
    ),
    "trading212": ConfigurationGuide(
        title="Trading 212 credentials",
        purpose="Provide the API key pair for the selected Trading 212 environment.",
        ai_usage=(
            "The AI uses Trading 212 as broker-authoritative account and order state, "
            "and can submit approved orders through the configured environment."
        ),
        obtain=(
            "Open Trading 212 web or mobile settings.",
            "Go to API (Beta), accept the API risk warning, and generate a key pair.",
            "Copy the API key into T212_DEMO_API_KEY or T212_LIVE_API_KEY.",
            "Copy the secret into T212_DEMO_API_SECRET or T212_LIVE_API_SECRET.",
            "Start with demo and enable live trading only after doctor smoke checks pass.",
        ),
        references=(
            "https://helpcentre.trading212.com/hc/en-us/articles/"
            "14584770928157-Trading-212-API-key",
            "docs/api/T212ApiDocs.md",
        ),
    ),
    "alpaca": ConfigurationGuide(
        title="Alpaca credentials",
        purpose="Provide Alpaca API credentials for broker access and/or market data.",
        ai_usage=(
            "The AI can use Alpaca for account/order workflows, market bars, quote "
            "context, and real-time news or market-data monitoring when enabled."
        ),
        obtain=(
            "Create or sign in to an Alpaca account.",
            "Use paper trading credentials for development.",
            "Generate API keys from the dashboard API keys panel.",
            "Copy the key and secret into the matching paper or live env vars.",
            "Keep paper and live credentials separate.",
        ),
        references=(
            "https://alpaca.markets/learn/connect-to-alpaca-api",
            "https://docs.alpaca.markets/us/docs/getting-started-with-trading-api",
        ),
    ),
    "telegram": ConfigurationGuide(
        title="Telegram setup",
        purpose="Configure the bot token and allow-list used for chat access and approvals.",
        ai_usage=(
            "The AI uses Telegram as the operator interface for requests, summaries, "
            "approval buttons, scheduler notifications, and guarded broker actions."
        ),
        obtain=(
            "Message @BotFather in Telegram and send /newbot.",
            "Copy the returned token into TELEGRAM_BOT_TOKEN.",
            "Send a message to the target chat, then call getUpdates with the bot token.",
            "Use message.chat.id as TELEGRAM_ALLOWED_CHAT_ID.",
            "Optionally use message.from.id as TELEGRAM_ALLOWED_USER_ID.",
        ),
        references=(
            "https://core.telegram.org/bots/features#botfather",
            "https://core.telegram.org/bots/api#getupdates",
        ),
    ),
    "market_data": ConfigurationGuide(
        title="Market data setup",
        purpose="Select the quote and bar source used for price and chart context.",
        ai_usage=(
            "The AI uses market data to contextualize proposals, monitor instruments, "
            "evaluate price movement, and enrich explanations. It is context, not "
            "broker-authoritative execution state."
        ),
        obtain=(
            "Choose Yahoo for a no-key local research baseline.",
            "Choose Alpaca if you want Alpaca-backed bars, quotes, or stream-adjacent workflows.",
            "Choose Disabled when market data should not be available.",
        ),
    ),
    "alpha_vantage": ConfigurationGuide(
        title="Alpha Vantage credentials",
        purpose="Enable optional market intelligence and enrichment data.",
        ai_usage=(
            "The AI uses Alpha Vantage for research context such as movers, "
            "indicators, fundamentals, news sentiment, transcripts, and macro data."
        ),
        obtain=(
            "Open the Alpha Vantage API key page.",
            "Request a key with an email address you can access.",
            "Copy the generated key into ALPHA_VANTAGE_API_KEY.",
            "Review current request limits before using it in frequent scheduler jobs.",
        ),
        references=(
            "https://www.alphavantage.co/support/#api-key",
            "https://www.alphavantage.co/documentation/",
        ),
    ),
    "sec_edgar": ConfigurationGuide(
        title="SEC EDGAR setup",
        purpose="Enable official filing, insider, and company disclosure context.",
        ai_usage=(
            "The AI uses EDGAR as official-source evidence for company analysis and "
            "risk review. EDGAR does not become broker or execution authority."
        ),
        obtain=(
            "No API key is required for the public data used here.",
            "Set SEC_EDGAR_USER_AGENT to identify your automated requests.",
            "Include a project or personal name and a working contact email.",
        ),
        references=(
            "https://www.sec.gov/edgar/searchedgar/accessing-edgar-data.htm",
            "https://data.sec.gov/",
        ),
    ),
    "search": ConfigurationGuide(
        title="Search setup",
        purpose="Explain the search provider used for web discovery workflows.",
        ai_usage=(
            "The AI uses search to discover sources, then should still inspect and "
            "cite primary or high-quality documents before treating them as evidence."
        ),
        obtain=(
            "The wizard does not prompt for SearXNG credentials.",
            "Run SearXNG through the deployment or Compose stack.",
            "Edit SEARCH_PROVIDER and SEARXNG_BASE_URL later if needed.",
        ),
    ),
    "storage": ConfigurationGuide(
        title="Local storage setup",
        purpose="Configure local persistence paths and log behavior.",
        ai_usage=(
            "The AI-backed workflows use the database for pending actions, proposals, "
            "reconciliation, and schedules. Guideline memory stores durable operator "
            "preferences, and logs support diagnosis."
        ),
        obtain=(
            "Use the defaults for local development.",
            "Use persistent mounted paths when running in containers.",
            "Do not commit databases, logs, or guideline memory files.",
        ),
    ),
    "scheduler": ConfigurationGuide(
        title="Scheduler setup",
        purpose="Configure default timing and worker behavior for background processes.",
        ai_usage=(
            "The AI uses scheduler settings to interpret local-time requests, run "
            "monitors, throttle LLM-assisted jobs, recover stale work, and send "
            "notifications from the right process."
        ),
        obtain=(
            "Use an IANA timezone such as Europe/Rome, America/New_York, or UTC.",
            "Keep defaults for local development unless you are operating workers.",
            "Use a separate scheduler worker for production-like deployments.",
        ),
    ),
}


def render_configuration_guide(guide: ConfigurationGuide) -> str:
    lines = [
        f"Purpose: {guide.purpose}",
        f"How the AI uses it: {guide.ai_usage}",
        "How to obtain or choose it:",
    ]
    lines.extend(f"- {step}" for step in guide.obtain)
    if guide.references:
        lines.append("References:")
        lines.extend(f"- {reference}" for reference in guide.references)
    return render_box("\n".join(lines), title=guide.title)
