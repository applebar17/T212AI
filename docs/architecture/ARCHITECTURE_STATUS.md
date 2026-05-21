# Architecture Status

This file is a direct snapshot of the current repo state. Historical roadmap
context remains in [PLAN.md](../planning/PLAN.md), while active near-term work
is tracked in [TODO.md](../planning/TODO.md).

For diagrams, see [ARCHITECTURE_DIAGRAMS.md](./ARCHITECTURE_DIAGRAMS.md).

## Overall Status

The project is well beyond the design-only phase.

The current state is:
- bootstrap/setup layer: in place
- capability-driven runtime baseline: in place
- Telegram bridge baseline: in place
- agent baseline: in place
- provider integration baseline: in place
- persistent guideline memory: in place
- calculator baseline: in place and routed when the LLM runtime is configured
- workflow execution layer: partially in place
- operational persistence, approval flow, and reconciliation baseline: in place
- market-signal memory: in place
- GenAI context-window guardrails: in place

## Current Architecture

### 0. V1 Delivery Strategy

Implemented decision:
- tool-first
- thin-flow-second
- heavy workflows later

Meaning in practice:
- market/company/portfolio exploration can stay mostly agentic and tool-driven for now
- repeated or sensitive paths get deterministic thin flows first
- calculator capabilities are implemented as deterministic tools and routed through the orchestrator when the LLM runtime is configured

### 1. Bootstrap And Startup Layer

Implemented:
- `brokerai` / `t212ai` CLI
- `configure` wizard
- `doctor` diagnostics
- `run bot`
- `run reconcile-once`
- `run worker --reconcile-every <duration>`
- `.env` as the canonical local config artifact
- explicit provider selectors and enable flags
- capability assessment and startup preflight

Current status:
- config, diagnostics, and startup are no longer ad hoc
- local and containerized runs use the same command surface
- reconciliation already has both one-shot and worker-style run surfaces

Missing:
- webhook mode
- worker/scheduler commands beyond reconciliation
- DB init/migration operational commands

### 2. Runtime Layer

Implemented:
- `AppRuntime` as the application composition root
- config assessment + startup preflight attached to runtime
- guideline memory store/service wiring
- chat history manager wiring
- DB engine and session factory wiring
- pending-action service wiring
- proposal service wiring
- reconciliation service wiring
- calculator service wiring
- GenAI client wiring from `AppSettings`
- `AgentReasoner`, `AgentJudge`, `MainOrchestratorAgent`, and `CalculatorAgent` wiring
- Trading 212 runtime wiring
- Alpaca broker runtime wiring
- Yahoo runtime wiring
- Alpaca market-data runtime wiring
- Alpha Vantage runtime wiring
- Reddit runtime wiring

Current status:
- runtime owns the main app graph
- Telegram no longer assembles GenAI or the orchestrator by itself
- reconciliation is built as a backend runtime service, not as bot-only logic

Missing:
- unified market-context service
- broader worker/runtime composition for future scheduled jobs

### 3. Telegram Layer

Implemented:
- thin Telegram bridge
- access control
- messenger helpers
- command/help baseline
- runtime-backed free-text path into the orchestrator
- runtime-owned chat history reuse
- inline approval/rejection buttons for prepared actions
- optional `TELEGRAM_ALLOWED_USER_ID`
- proposal inspection commands:
  - `/proposals`
  - `/proposal <proposal_id>`

Current status:
- Telegram is correctly acting as a transport/bridge layer
- deterministic approval resolution happens only for Telegram button callbacks
- proposal and execution state can now be inspected from Telegram

Missing:
- richer command set
- richer execution result and reconciliation UX

### 4. Agent Layer

Implemented:
- `MainOrchestratorAgent`
- `PortfolioAnalystAgent`
- `OrderAgent`
- `MarketAnalystAgent`
- `CompanyAnalystAgent`
- `CalculatorAgent`
- `GuidelineMemoryAgent`
- centralized `AgentReasoner`
- optional `AgentJudge`
- structured request/response/plan/critique models
- short-term rolling chat history
- scoped persistent guideline injection

Current status:
- the agent architecture is in place and runtime-owned
- top-level orchestration is now LLM-first and tool-based
- the orchestrator holds the user-facing conversation and can answer directly, ask for clarification, or explicitly call specialist-routing tools
- specialist delegation happens through an orchestrator toolbox plus tool:function mapping, so routing decisions and specialist outputs stay inside the same LLM conversation
- specialists usually start with structured planning and then execute workflows or deterministic tools when available
- persistent guideline context is available to the orchestrator and specialists
- live specialist toolboxes are runtime-built and capability-first
- provider-specific toolboxes are retained only as compatibility or explicit specialist exceptions
- `OrderAgent` has a deterministic higher-level order-action path for:
  - prepared order submission
  - prepared order cancellation
- `CalculatorAgent` is routed through the orchestrator and still uses deterministic tools for execution-safe math
- `MarketAnalystAgent` can use SQL-backed market signal memory when `DATABASE_URL` is configured
- `GenAIClient` resolves context windows per model/tier and compacts long tool-heavy conversations before provider calls

Missing:
- company and market specialists are still mostly plan/tool-driven
- orchestration is not yet a fully open-ended recursive multi-agent loop; today it is an LLM manager with bounded sequential specialist tool calls
- the judge is implemented but not yet meaningfully plugged into critical pipelines

### 5. Data And Broker Integrations

Implemented:
- Trading 212 low-level API client
- Trading 212 broker service and tools
- Trading 212 historical-order read surface for reconciliation
- Alpaca shared HTTP base
- Alpaca market-data client and service
- Alpaca broker client and service
- Yahoo client and tools
- Alpha Vantage client and intelligence tools
- Reddit client, research service, and tools

Current status:
- provider building blocks exist and are runtime-wired
- the generic market-data facade can run on Yahoo or Alpaca
- the generic broker facade can run on Trading 212 or Alpaca
- the live agent-facing tool surface is generic-first:
  - `market_*` for market data
  - `broker_*` for broker operations
- provider-specific tool modules remain available, but they are no longer the primary live agent surface
- both broker providers support:
  - broker read capability
  - generic order preparation and execution capability
  - approval-safe pending-action execution
  - reconciliation reads against pending orders and recent historical orders

Missing:
- unified market-context object across providers
- stronger provider arbitration and symbol normalization
- caching/freshness strategy
- workflow-level provider composition

### 6. Persistence

Implemented:
- file-backed persistent guideline memory in JSON
- reusable structured document store
- CRUD operations for guideline nodes
- scoped Markdown rendering for prompt injection
- SQLite runtime database wiring
- Alembic baseline for application data
- persistent pending-action records for execution safety
- proposal storage
- approval event storage
- execution attempt storage
- reconciliation metadata on pending actions and execution attempts

Current status:
- long-term policy/config-style memory is in place
- execution-related operational persistence is in place for the current baseline

Missing:
- deeper reconciliation/audit depth beyond the current operational baseline
- scheduled maintenance for market signals, if cleanup/staleness policies become operationally important

### 7. Workflows

Implemented:
- portfolio summary workflow
- pending orders review workflow
- thin deterministic execution safety flow around prepared actions
- thin reconciliation backend flow with one-shot and worker run surfaces

Current status:
- there is a real thin workflow layer for the first broker-authoritative read paths
- portfolio and order specialists can already return real broker-backed outputs instead of only plans
- the broader workflow layer is still intentionally light

Missing:
- thin read-oriented flows where they give immediate value
- company snapshot flow
- market snapshot flow
- scheduled digest and alert workflows

### 8. Execution And Approval Model

Implemented:
- generic broker order tools
- Trading 212 `prepare_order`
- Trading 212 `place_order`
- Trading 212 `cancel_order`
- Alpaca `prepare_order`
- Alpaca `place_order`
- Alpaca `cancel_order`
- state-changing tool gating
- persistent pending-action records
- persistent proposal records and execution journaling
- broker-neutral order-action tools:
  - `broker_prepare_order_action`
  - `broker_prepare_cancel_action`
- Telegram approval buttons
- Telegram text fallback approval/rejection
- deterministic approval resolution against exact stored prepared actions
- optional Telegram user-level authorization
- backend reconciliation against remote pending orders and recent order history for both broker providers

Current status:
- execution safety is no longer only at the raw tool level
- the app now supports:
  - prepare exact action
  - persist pending action
  - approve through button or chat fallback
  - execute that exact stored action without a fresh LLM redesign
  - reconcile local state against the active broker remote state later

Current internal state shape:
- `awaiting_approval`
- `approved`
- `submitted`
- `rejected`
- `expired`
- `failed`
- `cancelled`
- `reconciled`

Missing:
- richer reconciliation/audit depth and broader status-reporting UX

## Current State Vs Target

| Area | Target | Current Status |
| --- | --- | --- |
| Bootstrap CLI | public setup + diagnostics + run surface | baseline done |
| Runtime composition | runtime-owned app graph | baseline done |
| Telegram bridge | natural-language front door | baseline done, still thin |
| Broker integration | generic broker interface + two providers | baseline done |
| External data | multi-provider research/context layer | baseline done, not unified |
| Orchestrator/specialists | routed agent-of-agents design | done at baseline |
| Persistent memory | long-term guidelines/config memory | done at baseline |
| Calculator | deterministic math and finance helper baseline | implemented and routed when LLM runtime is available |
| Workflow layer | thin deterministic flows for repeated/sensitive paths | partially done |
| Proposal engine | structured persisted proposals | baseline done |
| Approval flow | approval on deterministic prepared actions | baseline done |
| SQLite/Alembic | operational persistence | baseline done for current features |
| Demo execution pipeline | proposal -> approval -> execution -> reconciliation | baseline done, still thin |
| Scheduled jobs | digests, scans, alerts | partially done for reconciliation only |

## Main Missing Pieces

In priority order, the main gaps are now:

1. Expand scheduled jobs beyond the current reconciliation worker baseline.
2. Wire the shared reason-plan-execute-judge-return loop more broadly, including judge and repair behavior.
3. Add a unified market-context layer with clearer freshness/provenance handling across providers.
4. Implement company and market snapshot thin flows only where they provide immediate value.
5. Decide whether watchlist support is part of v1 scope or should be explicitly deferred.

## Practical Read On The Repo

The repo now has:
- a real bootstrap/config layer
- a real runtime/composition layer
- a real agent baseline
- real provider integrations
- a real calculator baseline
- SQL-backed market-signal memory
- GenAI context-window budgeting and compaction
- a real reconciliation backend baseline

The repo still does not have:
- unified market context
- broad scheduled operational flows beyond reconciliation
- watchlist implementation parity with the written v1 target

So the current state is best described as:
- architectural baseline: solid
- startup/runtime baseline: solid
- operational behavior: working, but still intentionally thin in some areas

## Recommended Next Build Order

1. Add a small scheduled-process baseline that can run deterministic jobs beyond reconciliation.
2. Wire judge/action-repair behavior into the configurable specialist loop.
3. Add a unified market-context layer with freshness-aware composition.
4. Add company and market snapshot thin flows only if usage shows they are worth structuring now.
5. Decide and implement the minimal watchlist baseline, or explicitly defer it out of v1.

## Short Conclusion

The architecture direction remains correct.

The main missing layer is no longer runtime composition, proposal persistence,
market-signal memory, token-context protection, or the initial execution-safety
baseline. Those are now in place. The next real gaps are scheduled operational
flows beyond reconciliation, broader agentic loop reuse, market-context
unification, additional high-value thin flows, and watchlist scope clarity.
