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
- workflow execution layer: still missing
- operational persistence and approval flow: still missing

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
- workflow service wiring
- DB/session wiring
- proposal/approval service wiring
- unified market-context service

### 3. Telegram Layer

Implemented:
- thin Telegram bridge
- access control
- messenger helpers
- command/help baseline
- runtime-backed free-text path into the orchestrator
- runtime-owned chat history reuse

Current status:
- Telegram is correctly acting as a transport/bridge layer
- the bot now consumes a ready runtime instead of building a second hidden agent stack

Missing:
- richer command set
- approval UX for proposals and executions
- persisted proposal/execution integration

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

Missing:
- specialists still mainly return plans rather than executing real workflows
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

Current status:
- long-term policy/config-style memory is in place
- this remains the only application persistence that is actually operational today

Missing:
- SQLite operational persistence
- Alembic migrations for application data
- proposal storage
- execution attempt storage
- approval storage
- reconciliation/audit persistence

### 7. Workflows

Implemented:
- workflow modules exist as placeholders

Current status:
- `proposal.py`, `order_review.py`, `attention_scan.py`, and `digest.py` are still placeholders
- there is still no real workflow layer connecting agents to deterministic Python execution logic
- this is acceptable for v1 as long as we keep the flow strategy intentionally lightweight

Missing:
- thin read-oriented flows where they give immediate value
- portfolio summary flow
- pending orders review flow
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

Current status:
- execution safety is partially in place at the tool level
- the intended v1 UX is chat-based confirmation, not necessarily Telegram buttons

Agreed direction:
- assistant prepares an action first
- assistant presents the exact prepared action back to the user
- user confirms in chat, for example: `Yes, proceed`
- the system should execute the already prepared action, not reinterpret the trade from scratch through a new LLM pass

Required structured behavior:
- keep execution-related paths deterministic even if research and analysis remain tool-driven
- model a pending prepared action internally before execution
- treat confirmation as approval of that exact pending action
- avoid letting a simple `yes` trigger fresh free-form trade design

Expected internal state shape later:
- `draft`
- `prepared`
- `awaiting_approval`
- `approved`
- `submitted`
- `reconciled`
- `rejected`
- `expired`

Missing:
- persisted proposal or pending-action records
- deterministic approval resolution
- expiry/staleness handling
- final reconciliation flow
- optional Telegram button UX on top of the same approval model

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
| Workflow layer | thin deterministic flows for repeated/sensitive paths | not done |
| Proposal engine | structured persisted proposals | partially designed, not operational |
| Approval flow | chat-based approval on deterministic prepared actions | not done |
| SQLite/Alembic | operational persistence | not done |
| Demo execution pipeline | proposal -> approval -> execution -> reconciliation | not done |
| Scheduled jobs | digests, scans, alerts | not done |

## Main Missing Pieces

In priority order, the main gaps are now:

1. Implement thin deterministic flows only where they add immediate value.
2. Keep specialist agents mostly tool-driven, but add structure to sensitive paths.
3. Add SQLite/Alembic persistence.
4. Implement the proposal or pending-action lifecycle.
5. Implement chat-based approval resolution for prepared actions.
6. Add demo execution and reconciliation.
7. Add workflow-level provider composition as repeated patterns become clear.
8. Add scheduled jobs only after the manual path works end-to-end.

## Practical Read On The Repo

The repo now has:
- a real bootstrap/config layer
- a real runtime/composition layer
- a real agent baseline
- real provider integrations

The repo still does not have:
- thin operational flows for critical paths
- persisted proposal/execution state
- approval-driven execution

So the current state is best described as:
- architectural baseline: solid
- startup/runtime baseline: solid
- operational behavior: still partial by design

## Recommended Next Build Order

1. Implement the first real read-only workflows:
   - portfolio summary
   - pending orders review
2. Implement thin execution safety flow:
   - prepare action
   - chat approval
   - execute exact prepared action
3. Add SQLite/Alembic persistence.
4. Add proposal or pending-action creation and retrieval.
5. Add company and market snapshot flows only if usage shows they are worth structuring now.
6. Add demo execution and reconciliation.

## Short Conclusion

The architecture direction remains correct.

The main missing layer is no longer runtime composition. That baseline is now in place. The next real gap is operational: a light workflow strategy, persistence, prepared-action lifecycle, and approval-driven execution.
