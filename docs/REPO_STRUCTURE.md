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
|   |-- AGENT_DESIGN.md
|   |-- AGENTIC_FLOW.md
|   |-- AGENTIC_LOGIC.md
|   |-- AGENT_PATTERNS.md
|   |-- DATA_SOURCES.md
|   |-- FEATURES.md
|   |-- NEWS_AND_WEBSEARCH.md
|   |-- OPEN_QUESTIONS.md
|   |-- PLAN.md
|   |-- REPO_STRUCTURE.md
|   `-- T212ApiDocs.md
|-- scripts/
|   |-- dev_bot.py
|   `-- smoke_tools.py
|-- src/
|   `-- t212ai/
|       |-- agent/
|       |-- app/
|       |-- brokers/
|       |-- data_sources/
|       |-- genai/
|       |-- persistence/
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
- tracing helpers
- generic tool registry mechanics

This package should remain domain-light. Trading 212-specific behavior belongs in `brokers` or `agent`.

### `src/t212ai/persistence`

Lightweight local persistence:

- SQLite session setup
- Alembic-managed models
- repositories for proposals, approvals, executions, policies, watchlists, and digest state

This is not a warehouse. Persist only data needed for continuity and safety.

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
- execution records and order fingerprints
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
- runs `python -m t212ai` by default
- mounts `./data` through Compose

The default container command is a placeholder until the Telegram bot runner exists.

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

Start filling the first real domain package:

```text
src/t212ai/brokers/trading212/
```

The first useful implementation target is a demo-mode Trading 212 client for account summary, positions, and pending orders.
