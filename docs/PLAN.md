# Trading 212 Telegram Agent Plan

Status: working implementation plan.

## Goal

Build a Telegram-based investment copilot that can analyze portfolio state, use external data for better decisions, and execute approved Trading 212 orders safely.

## Confirmed Baseline

- personal-use only
- Python first
- local development first, then containerize, then deploy later
- Trading 212 demo first, live later
- all live decisions require Telegram confirmation
- free text is the main UX; commands are fallbacks
- use a lightweight local SQLite database with Alembic for operational persistence

## Phase 0: Scope And Safety Baseline

Deliverables:

- define product scope and non-goals
- define execution modes: read-only, approval-based, guarded automation
- define user policy model
- define proposal and execution lifecycle

Exit criteria:

- the system is explicitly designed as a copilot first
- live trading is not the default
- order-safety rules are agreed before implementation

## Phase 1: Core Read-Only Integrations

Deliverables:

- apply the structure guidance in `docs/REPO_STRUCTURE.md`
- add `src/t212ai`, `pyproject.toml`, `tests`, and `.env.example`
- move the cleaned `genai` package under `src/t212ai/genai`
- clean up and reuse the useful parts of `./genai`
- Trading 212 API client
- environment handling for demo and live
- account summary, positions, orders, and history sync
- Telegram bot skeleton
- intent classification and capability registry
- read-only commands for summary, positions, orders, and recent activity
- natural-language handling for the same read-only flows

Exit criteria:

- you can ask Telegram for account state and get reliable responses
- all Trading 212 responses are normalized into internal types
- commands and natural-language requests hit the same internal logic

## Phase 2: External Data Foundation

Deliverables:

- choose market/news/calendar data providers with free options preferred first
- define provider roles for Trading 212, a pluggable price feed, optional enrichment sources, and optional Yahoo usage
- define how news feeds and web search fit into the trust model
- symbol mapping and normalization layer
- caching strategy
- freshness metadata on all external inputs
- source provenance and arbitration rules
- scheduled refresh jobs

Exit criteria:

- the system can build a single market context object for a ticker or portfolio
- stale or missing data is visible to downstream logic
- the system knows which provider is authoritative for each class of data

## Phase 3A: Research Layer

Deliverables:

- broad market and portfolio-theme news ingestion first
- ticker and theme-based news ingestion
- web search integration for discovery
- citation and provenance capture
- duplicate-story clustering
- relevance, novelty, and source-quality scoring

Exit criteria:

- the bot can produce cited research summaries
- news and search evidence can feed the proposal engine without bypassing controls

## Phase 3B: Portfolio Analytics And Insight Layer

Deliverables:

- allocation and concentration analytics
- performance and exposure summaries
- daily digest generation
- watchlist monitoring
- risk alerts and event alerts

Exit criteria:

- the bot can answer portfolio questions without execution capability
- alerts are useful without being noisy

## Phase 4: Structured LLM Proposal Engine

Deliverables:

- prompt contract for read-only analysis
- prompt contract for trade proposals
- prompt contract for dynamic action planning
- structured output schema
- evidence and risk extraction
- deterministic validation after every LLM response

Exit criteria:

- every proposal has thesis, evidence, risk notes, and confidence
- free-form LLM output is never sent directly to execution
- the agent can map natural-language requests to bounded tool plans

## Phase 5: Safe Order Execution In Demo

Deliverables:

- Telegram approval flow with natural-language confirmation as the baseline
- proposal persistence
- order translation for market, limit, stop, and stop-limit
- local idempotency guard
- post-submit reconciliation
- cancel pending order flow

Exit criteria:

- approved proposals can be executed in the demo environment
- duplicate order risk is managed explicitly
- execution outcomes can be reconstructed safely from local state

## Phase 6: Live Trading Hardening

Deliverables:

- live-only config separation
- operational alerts
- kill switch and trading pause controls, including a command-based read-only switch
- stricter approval and limit policies
- end-to-end logging review

Exit criteria:

- the exact same workflow works in demo first
- live mode can be disabled instantly
- there is enough operational trace to understand what happened after an action

## Phase 7: Optional Automation

Deliverables:

- strategy templates with explicit limits
- scheduled or event-driven trade generation
- auto-execution only inside approved policy bounds

Exit criteria:

- automation is narrow, explainable, and reversible
- manual approval can be restored instantly

## Suggested First Coding Milestone

The first implementation slice should be:

1. Trading 212 client in demo mode
2. Telegram bot with natural-language portfolio queries plus `/help`, `/summary`, `/positions`, and `/orders`
3. internal domain types, capability registry, and local SQLite/Alembic storage schema
4. proposal lifecycle without real execution

This gives you a usable foundation without taking execution risk too early.

## Definition Of Done For v1

The system is ready for wider use when:

- Telegram can answer portfolio and watchlist questions reliably
- external data is integrated and freshness-aware
- trade proposals are structured and explainable
- execution works in demo with reconciliation
- live execution is still approval-based

## Near-Term Decisions Still Needed

- exact free price-feed choice
- exact news and web-search providers
- calendar provider choice
- initial user policy defaults for order size and position limits
- how aggressive the planner should be before it asks clarifying questions
- when to add deeper company research specialists
- what summary or journaling data should be retained for weekly highlights

## Provider Abstraction And Alpaca Roadmap

Status: settled direction, implementation pending by waves.

### Confirmed Direction

- provider selection should be capability-driven, not vendor-driven
- agent-facing tools should converge toward stable domain tools
- tool and toolbox visibility must be driven by runtime configuration
- Yahoo remains the default market-data baseline because it is free and accessible
- Alpaca should be supported as:
  - an optional better market-data provider
  - a future broker provider
- in v1, use one primary provider per capability
- existing providers remain valid and should be reused during migration

### Capability Model

The app should move toward these primary configurable capabilities:

- `BROKER_PROVIDER=trading212|alpaca|none`
- `MARKET_DATA_PROVIDER=yahoo|alpaca|none`
- `MARKET_INTELLIGENCE_PROVIDER=alpha_vantage|none`
- `DISCLOSURE_PROVIDER=sec_edgar|none`
- `COMMUNITY_PROVIDER=reddit|none`
- `SEARCH_PROVIDER=searxng|none`

For v1:

- Yahoo is the baseline `MARKET_DATA_PROVIDER`
- Alpaca, when configured, becomes the preferred market-data provider
- Trading 212 remains the baseline `BROKER_PROVIDER`
- Alpha Vantage, SEC EDGAR, Reddit, and SearXNG remain optional capability-specific providers

### Wave 1: Runtime-Driven Tool Visibility

Deliverables:

- audit current provider/tool wiring
- stop exposing non-configured tools to agents
- replace static always-on toolboxes with runtime/config-aware toolbox construction
- ensure agent toolbox summaries only mention configured capabilities
- preserve current provider-specific tool handlers during this wave
- update CLI doctor/configure flow so enabled providers are smoke-tested and marked ready or invalid

Exit criteria:

- if Alpha Vantage is not configured, Alpha Vantage tools are not visible or callable
- if Reddit is not configured, Reddit tools are not visible or callable
- if SearXNG is not configured, search tools are not visible or callable
- toolbox visibility matches the runtime capability graph

### Wave 2: Capability Interfaces

Deliverables:

- introduce app-level capability protocols/interfaces
- split broker contracts into at least:
  - `BrokerReadService`
  - `BrokerExecutionService`
- introduce a `MarketDataService` interface for quote, bars, and volume monitoring
- keep existing provider implementations, but start adapting them to those interfaces
- do not remove current provider-specific services yet

Exit criteria:

- runtime can reason in terms of capabilities instead of raw provider classes
- the app has stable internal contracts for broker and market-data behavior

### Wave 3: Generic Market-Data Tool Facade

Deliverables:

- add provider-neutral market-data tools such as:
  - `market_get_quote`
  - `market_get_bars`
  - `market_get_volume_monitor`
  - `market_get_market_snapshot`
- map those tools to the configured `MARKET_DATA_PROVIDER`
- keep Yahoo as the default implementation
- keep existing Yahoo-specific tools during transition where still needed

Exit criteria:

- agents can access market data through stable capability tools
- Yahoo remains the no-config-surprise baseline

### Wave 4: Alpaca Market-Data Integration

Deliverables:

- add `AlpacaMarketDataClient`
- add Alpaca adapter/service implementing the market-data capability
- support candle/bar retrieval and volume-monitoring-friendly market data
- wire Alpaca into CLI configuration and doctor checks
- allow users to choose Alpaca as `MARKET_DATA_PROVIDER`

Exit criteria:

- Alpaca can fully back the generic market-data tool facade
- Yahoo remains available as the baseline alternative

### Wave 5: Generic Broker Tool Facade

Deliverables:

- add provider-neutral broker tools such as:
  - `broker_get_portfolio_snapshot`
  - `broker_list_pending_orders`
  - `broker_prepare_order_action`
  - `broker_prepare_cancel_action`
- map those tools to the configured broker capability
- adapt current Trading 212 flow to the generic broker tool facade
- keep execution safety, approval, proposals, and reconciliation unchanged in behavior

Exit criteria:

- agents can use broker capability tools without depending on Trading 212-specific names
- existing Trading 212 execution safety flow still works through the new abstraction

### Wave 6: Alpaca Broker Integration

Status:
- implemented in the current repo state

Deliverables:

- add `AlpacaBrokerClient`
- add Alpaca broker adapter implementing broker read and execution capabilities
- wire Alpaca into CLI configuration and provider smoke tests
- support choosing Alpaca as `BROKER_PROVIDER`
- define and document any provider-specific behavioral differences that do not fit the common contract exactly

Exit criteria:

- runtime can operate with either Trading 212 or Alpaca as the active broker provider
- the common broker tool facade works for both providers on supported operations

### Wave 7: Migration And Cleanup

Status:
- implemented in the current repo state

Deliverables:

- migrate specialist agents and toolbox summaries to the capability-based tool names
- reduce direct provider-specific tool exposure in agent-facing toolboxes
- retain provider-specific tools only where they are intentionally specialized
- update architecture docs and developer guidelines

Exit criteria:

- the agent layer thinks primarily in capabilities, not vendors
- provider-specific tools are implementation details or explicit specialist exceptions

### Rules To Preserve Throughout The Migration

- do not break the existing Trading 212 order-safety flow
- do not expose non-configured tools to the LLM
- keep Yahoo as the default market-data baseline unless the user explicitly configures Alpaca
- prefer additive migration over large rewrites
- keep CLI/provider smoke tests aligned with runtime capability checks
