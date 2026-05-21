# Repository Structure

Status: working structure reference.

## Goal

Keep the project easy to evolve from a prototype into a Telegram-connected Trading 212 agent without turning it into a large platform too early.

The structure should support:

- Python-first implementation
- local development first
- containerization later
- Telegram natural-language agent
- Trading 212 broker integration
- external research and market-data tools
- lightweight SQLite/Alembic persistence
- reusable GenAI/tooling code

## Current Shape

```text
.
|-- alembic/
|   |-- env.py
|   `-- versions/
|-- data/
|-- docs/
|   |-- README.md
|   |-- agents/
|   |-- api/
|   |-- architecture/
|   |-- data/
|   |-- operations/
|   |-- planning/
|   `-- scheduler/
|-- scripts/
|   |-- alpaca_news_stream_capture.py
|   |-- check_trading212_instrument_resolution.py
|   |-- dev_bot.py
|   `-- smoke_tools.py
|-- src/
|   `-- t212ai/
|       |-- agent/
|       |-- alpaca/
|       |-- app/
|       |-- brokers/
|       |-- calculator/
|       |-- capabilities/
|       |-- data_sources/
|       |-- genai/
|       |-- guidelines/
|       |-- market_signals/
|       |-- pending_actions/
|       |-- persistence/
|       |-- proposals/
|       |-- reconciliation/
|       |-- telegram/
|       `-- workflows/
|-- tests/
|   |-- fixtures/
|   |-- integration/
|   `-- unit/
|-- .dockerignore
|-- .env
|-- .env.example
|-- Dockerfile
|-- README.md
|-- alembic.ini
|-- docker-compose.yml
`-- pyproject.toml
```

Generated folders such as `__pycache__`, `.pytest_cache`, or `pytest-cache-files-*` are not part of the source structure.

## Root Files

- `README.md`: project entrypoint and basic commands.
- `pyproject.toml`: package metadata, dependencies, pytest, and lint settings.
- `.env`: local secrets and runtime config; never commit real values.
- `.env.example`: documented environment variables.
- `Dockerfile`: baseline application image.
- `docker-compose.yml`: local container run/build entrypoint.
- `.dockerignore`: excludes secrets, caches, local DB files, and stale generated files.
- `alembic.ini`: Alembic configuration.

## Package Boundaries

### `src/t212ai/app`

Application-wide wiring:

- environment config
- logging setup
- runtime object construction

Keep business logic out of this package.

### `src/t212ai/agent`

Agent reasoning and control flow:

- intent models
- planning primitives
- policy models
- structured output schemas
- orchestration

The LLM should not call broker methods directly. It should produce structured intent, plans, or proposals that this layer validates.

### `src/t212ai/brokers/trading212`

Trading 212 broker integration:

- auth
- account summary
- positions
- pending orders
- historical orders and transactions
- order placement
- order cancellation
- rate-limit handling

This package is broker-authoritative. Do not mix Yahoo, web-search, or news data here.

### `src/t212ai/alpaca`

Alpaca broker and market-data integration:

- shared Alpaca HTTP base
- paper/live broker client and service
- market-data client and service
- generic broker and market-data facade support

Alpaca broker integration follows the same broker-authoritative boundary for
paper/live account state and order actions.

### `src/t212ai/capabilities`

Provider-neutral capability models used to bind runtime implementations to the
agent-facing tool surface.

### `src/t212ai/guidelines`

Persistent guideline memory storage and service logic for durable user
preferences and operating rules.

### `src/t212ai/data_sources`

Non-broker external data:

- market-data adapters
- research adapters
- news/calendar providers
- future Reddit/community sources
- Alpha Vantage client and category-specific toolboxes
- Yahoo Finance convenience client and market-context tools

Provider clients should be pluggable. The agent should depend on interfaces or tool functions, not hardcoded vendor assumptions.

### `src/t212ai/genai`

Reusable LLM/tooling infrastructure:

- OpenAI/Azure client wrapper
- tool execution loop
- token counting
- context-window budgeting and summarization guardrails
- tracing helpers
- generic tool registry mechanics

This package should remain domain-light. Trading 212-specific behavior belongs in `brokers` or `agent`.

### `src/t212ai/persistence`

Lightweight local persistence:

- SQLite session setup
- SQLAlchemy base metadata and database helpers

Feature packages own their operational rows and services while using this shared
database layer. This is not a warehouse. Persist only data needed for continuity
and safety.

### `src/t212ai/market_signals`

SQL-backed persistent market-signal memory:

- compact market-relevant notes
- active-signal search
- create/archive tools for the market analyst
- deterministic maintenance methods for cleanup

Market signals are advisory context only. They are not broker state, market-data
authority, or execution validation.

### `src/t212ai/pending_actions` and `src/t212ai/proposals`

Operational execution-safety persistence:

- prepared broker actions
- proposal records
- approval events
- execution attempts
- reconciliation metadata

These packages protect the approval and execution flow. Do not bypass them for
state-changing broker actions.

### `src/t212ai/reconciliation`

Broker reconciliation backend for syncing local pending actions and execution
attempts against remote broker state.

### `src/t212ai/telegram`

Telegram integration:

- bot startup
- command handlers
- natural-language message handlers
- approval/rejection handling
- `/help`
- chat authorization
- normalized inbound/outbound message models
- outbound messenger helpers for replies, errors, and approval requests

Telegram should call the agent orchestrator, not individual broker/data-source tools directly.

### `src/t212ai/workflows`

Reusable high-level flows:

- portfolio attention scan
- pending-order review
- trade proposal generation
- daily digest
- single-order cancellation

These are deterministic application workflows that can use the agent layer, tools, and policy layer.

## Operational Folders

### `alembic`

Alembic migration environment. Keep migrations small and focused on operational state.

### `data`

Local runtime data. Intended for SQLite files and development artifacts. Keep only `.gitkeep` in source control.

### `docs`

Design and reference docs. Root should stay focused on runtime/package files.

### `scripts`

Small local commands:

- `dev_bot.py`: future local Telegram bot runner
- `smoke_tools.py`: quick tool registry smoke check
- `check_trading212_instrument_resolution.py`: local broker instrument
  resolution diagnostic

### `tests`

Test organization:

- `unit`
- `integration`
- `fixtures`

## Import Rules

Preferred dependency direction:

```text
telegram -> agent -> workflows -> brokers/data_sources/persistence/genai
```

Avoid:

- broker importing Telegram
- data source importing Telegram
- `genai` importing Trading 212 domain logic
- persistence importing app workflows
- scripts becoming the source of business logic

## Persistence Scope

Use SQLite + Alembic for operational state only:

- trade proposals
- approvals/rejections
- pending actions
- execution records and order fingerprints
- market signals
- user policy
- watchlists
- alert definitions
- scheduled digest state
- cross-turn action state when needed

Do not persist:

- every raw provider response
- full scraped article archives
- broad research corpora
- embeddings/vector indexes
- compliance-grade audit logs

## Docker Baseline

The current Docker setup is intentionally minimal:

- installs the package from `pyproject.toml`
- includes database, Telegram, and research optional dependencies
- runs `python -m t212ai run bot` by default
- mounts `./data` through Compose

Compose also starts a local SearXNG service for search tooling.

## What Not To Build Yet

- multi-user account structure
- heavy service container framework
- vector database
- separate worker queue
- full audit/compliance subsystem
- multi-agent runtime framework
- full provider abstraction for every possible market-data source

Add these only when a concrete use case forces them.

## Recommended Next Step

Use [TODO.md](../planning/TODO.md) for the active implementation queue. The
current near-term focus is hardening implemented agentic, scheduler, broker, and
observability flows rather than initial project scaffolding.
