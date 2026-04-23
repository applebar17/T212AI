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
