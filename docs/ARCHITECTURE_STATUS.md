# Architecture Status

This file is a direct snapshot of the current repo state vs the target in [PLAN.md](./PLAN.md).

For diagrams, see [ARCHITECTURE_DIAGRAMS.md](./ARCHITECTURE_DIAGRAMS.md).

## Overall Status

The project is no longer in the design-only phase.

The current state is:
- bootstrap/setup layer: in place
- capability-driven runtime baseline: in place
- Telegram bridge baseline: in place
- agent baseline: in place
- provider integration baseline: in place
- persistent guideline memory: in place
- workflow execution layer: partially in place
- operational persistence and approval flow: partially in place

## Current Architecture

### 0. V1 Delivery Strategy

Implemented decision:
- tool-first
- thin-flow-second
- heavy workflows later

Current status:
- v1 is intentionally not moving toward large, highly structured workflows yet
- the current goal is to keep micro-tools and specialist agents flexible so real usage can show which repeated patterns deserve promotion into workflows later

Meaning in practice:
- market/company/portfolio exploration can remain mostly agentic and tool-driven for now
- only repeated or sensitive paths should become thin deterministic flows in the near term

### 1. Bootstrap And Startup Layer

Implemented:
- `brokerai` / `t212ai` CLI
- `configure` wizard
- `doctor` diagnostics
- `run bot` startup path
- `.env` as the canonical local config artifact
- explicit provider selectors and enable flags
- capability assessment and startup preflight

Current status:
- the app now has a real public-facing bootstrap surface
- config, diagnostics, and startup are no longer ad hoc
- local and containerized runs go through the same command surface

Missing:
- webhook mode
- worker/scheduler run commands
- DB init/migration operational commands

### 2. Runtime Layer

Implemented:
- `AppRuntime` as the application composition root
- config assessment + startup preflight attached to runtime
- guideline memory store/service wiring
- chat history manager wiring
- GenAI client wiring from `AppSettings`
- `AgentReasoner`, `AgentJudge`, and `MainOrchestratorAgent` wiring
- Trading 212 runtime wiring
- Yahoo runtime wiring
- Alpha Vantage runtime wiring
- Reddit runtime wiring
- runtime status helpers like:
  - `has_agent_runtime`
  - `has_broker_runtime`
  - `has_market_data_runtime`
  - `component_errors`
  - `startup_notes`

Current status:
- runtime is no longer just settings + guideline memory
- runtime now owns the main app graph for the current baseline
- Telegram no longer assembles GenAI and the orchestrator by itself

Missing:
- unified proposal/execution service wiring
- unified market-context service

### 3. Telegram Layer

Implemented:
- thin Telegram bridge
- access control
- messenger helpers
- command/help baseline
- runtime-backed free-text path into the orchestrator
- runtime-owned chat history reuse
- inline approval/rejection buttons for prepared actions
- chat fallback for approval/rejection:
  - `yes`
  - `no`
  - `si`
  - `sì`
  - `approve <action_id>`
  - `reject <action_id>`
- optional `TELEGRAM_ALLOWED_USER_ID`

Current status:
- Telegram is correctly acting as a transport/bridge layer
- the bot now consumes a ready runtime instead of building a second hidden agent stack
- Telegram can now resolve deterministic pending-action approvals before normal LLM routing

Missing:
- richer command set
- proposal-aware approval UX
- richer execution result and reconciliation UX

### 4. Agent Layer

Implemented:
- `MainOrchestratorAgent`
- `PortfolioAnalystAgent`
- `OrderAgent`
- `MarketAnalystAgent`
- `CompanyAnalystAgent`
- `GuidelineMemoryAgent`
- centralized `AgentReasoner`
- optional `AgentJudge`
- structured request/response/plan/critique models
- short-term rolling chat history
- scoped persistent guideline injection

Current status:
- the agent architecture is in place and runtime-owned
- routing and planning are consistent
- persistent guideline context is available to the orchestrator and specialists
- `OrderAgent` now has a deterministic higher-level order-action path for:
  - prepared order submission
  - prepared order cancellation

Missing:
- company and market specialists are still mostly plan/tool-driven
- the judge is implemented but not yet meaningfully plugged into critical pipelines

### 5. Data And Broker Integrations

Implemented:
- Trading 212 low-level API client
- Trading 212 broker service and tools
- Yahoo client and tools
- Alpha Vantage client and intelligence tools
- Reddit client, research service, and tools

Current status:
- the provider building blocks exist and are runtime-wired
- configuration and degraded-mode behavior are clearer than before
- Trading 212 now supports both:
  - low-level broker tools
  - higher-level conversational order-action tools used by the order specialist

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

Current status:
- long-term policy/config-style memory is in place
- long-term guideline memory and pending-action operational persistence are both now in place

Missing:
- proposal storage
- approval event storage
- execution attempt storage
- reconciliation/audit persistence

### 7. Workflows

Implemented:
- portfolio summary workflow
- pending orders review workflow
- thin deterministic execution safety flow around prepared actions

Current status:
- there is now a real thin workflow layer for the first broker-authoritative read paths
- portfolio and order specialists can already return real broker-backed outputs instead of only plans
- the broader workflow layer is still intentionally light

Missing:
- thin read-oriented flows where they give immediate value
- company snapshot flow
- market snapshot flow
- proposal generation workflow
- execution/reconciliation workflow
- scheduled digest and alert workflows

V1 direction:
- do not overdesign workflows yet
- keep tools small and composable
- promote only repeated or safety-critical patterns into deterministic flows

### 8. Execution And Approval Model

Implemented:
- Trading 212 `prepare_order`
- Trading 212 `place_order`
- Trading 212 `cancel_order`
- state-changing tool gating
- persistent pending-action records
- higher-level Trading 212 order-action tools:
  - `t212_prepare_order_action`
  - `t212_prepare_cancel_action`
- Telegram approval buttons
- Telegram text fallback approval/rejection
- deterministic approval resolution against exact stored prepared actions
- optional Telegram user-level authorization

Current status:
- execution safety is no longer only at the raw tool level
- the app now supports:
  - prepare exact action
  - persist pending action
  - approve through button or chat fallback
  - execute that exact stored action without a fresh LLM redesign

Agreed direction:
- assistant prepares an action first
- assistant presents the exact prepared action back to the user
- user confirms through Telegram buttons or chat fallback
- the system should execute the already prepared action, not reinterpret the trade from scratch through a new LLM pass

Required structured behavior:
- keep execution-related paths deterministic even if research and analysis remain tool-driven
- model a pending prepared action internally before execution
- treat confirmation as approval of that exact pending action
- avoid letting a simple `yes` trigger fresh free-form trade design

Current internal state shape:
- `awaiting_approval`
- `approved`
- `submitted`
- `rejected`
- `expired`
- `failed`

Expected later extension:
- `draft`
- `prepared`
- `reconciled`

Missing:
- proposal records
- final reconciliation flow
- execution audit trail beyond the pending-action record

## Current State Vs Target

| Area | Target | Current Status |
| --- | --- | --- |
| Bootstrap CLI | public setup + diagnostics + run surface | baseline done |
| Runtime composition | runtime-owned app graph | baseline done |
| Telegram bridge | natural-language front door | baseline done, still thin |
| Trading 212 integration | normalized broker interface + tools | baseline done |
| External data | multi-provider research/context layer | baseline done, not unified |
| Orchestrator/specialists | routed agent-of-agents design | done at baseline |
| Persistent memory | long-term guidelines/config memory | done at baseline |
| Workflow layer | thin deterministic flows for repeated/sensitive paths | partially done |
| Proposal engine | structured persisted proposals | partially designed, not operational |
| Approval flow | approval on deterministic prepared actions | baseline done for pending actions |
| SQLite/Alembic | operational persistence | partially done |
| Demo execution pipeline | proposal -> approval -> execution -> reconciliation | partially done, reconciliation missing |
| Scheduled jobs | digests, scans, alerts | not done |

## Main Missing Pieces

In priority order, the main gaps are now:

1. Refresh the docs and diagrams so they match the implemented runtime and approval flow.
2. Add proposal persistence and proposal lifecycle on top of the current pending-action baseline.
3. Add execution-event and reconciliation persistence.
4. Implement company and market snapshot thin flows only if they provide immediate value.
5. Add workflow-level provider composition as repeated patterns become clear.
6. Add scheduled jobs only after the manual path works end-to-end.

## Practical Read On The Repo

The repo now has:
- a real bootstrap/config layer
- a real runtime/composition layer
- a real agent baseline
- real provider integrations

The repo still does not have:
- persisted proposal state
- reconciliation-grade execution state
- unified market context
- scheduled operational flows

So the current state is best described as:
- architectural baseline: solid
- startup/runtime baseline: solid
- operational behavior: partially working, still incomplete by design

## Recommended Next Build Order

1. Add proposal persistence and retrieval.
2. Add proposal approval/rejection lifecycle on top of the existing pending-action flow.
3. Add execution attempt and reconciliation persistence.
4. Add company and market snapshot thin flows only if usage shows they are worth structuring now.
5. Add demo execution journaling and audit-friendly reconstruction.
6. Add scheduled jobs only after the manual path is complete.

## Short Conclusion

The architecture direction remains correct.

The main missing layer is no longer runtime composition, first workflows, or the initial prepared-action approval flow. Those baselines are now in place. The next real gap is operational depth: proposal lifecycle, execution/reconciliation persistence, and richer thin flows where they are clearly worth the added structure.
