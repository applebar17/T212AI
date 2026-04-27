# Architecture Status

This file is a simple snapshot of the current repo state vs the target in [PLAN.md](./PLAN.md).

For a visual view, see [ARCHITECTURE_DIAGRAMS.md](./ARCHITECTURE_DIAGRAMS.md).

## Overall Status

The project has a solid foundation, but it is still in a partial-wiring stage.

What is already in place:
- core repo structure
- Telegram bridge layer
- GenAI client, tracing, and agent baseline
- orchestrator + specialist agent architecture
- Trading 212 low-level client, service, and agent-facing tools
- Yahoo, Alpha Vantage, and Reddit read-only data integrations
- rolling chat history for agent context
- persistent guideline memory with CRUD tools and dedicated memory agent

What is not finished yet:
- full runtime composition
- real end-to-end workflows
- proposal lifecycle
- SQLite/Alembic operational persistence
- approval-driven execution flow
- scheduled jobs and digest automation

## Current Architecture

### 1. Telegram Layer

Implemented:
- thin Telegram bridge
- access control
- messenger helpers
- command/help baseline
- free-text path into the orchestrator when GenAI is configured

Current status:
- Telegram can receive messages, normalize them, keep short-term history, and call the main orchestrator
- this layer is correctly treated as a bridge, not as the business-logic owner

Missing:
- richer command coverage
- approval UX for proposals and executions
- tighter integration with persisted proposal/execution records

### 2. Agent Layer

Implemented:
- `MainOrchestratorAgent`
- `PortfolioAnalystAgent`
- `OrderAgent`
- `MarketAnalystAgent`
- `CompanyAnalystAgent`
- `GuidelineMemoryAgent`
- centralized `AgentReasoner`
- optional `AgentJudge`
- structured agent request/response/plan/critique models
- short-term chat history management

Current status:
- the architecture design is good and aligned with the target
- the orchestrator can route user requests to specialist agents
- agents can plan consistently and receive scoped persistent guideline context

Missing:
- specialists are still mostly planning-oriented
- specialists do not yet drive robust deterministic workflows for their domains
- the judge exists, but is not yet plugged into critical flows in a meaningful way

### 3. Data And Broker Integrations

Implemented:
- Trading 212 low-level API interfacing
- Trading 212 service and baseline agent tools
- Yahoo baseline client and tools
- Alpha Vantage baseline client and intelligence toolbox
- Reddit research client/service/tools

Current status:
- provider integrations exist and are usable as building blocks
- tooling shape is aligned with the intended agent design

Missing:
- a unified market-context layer combining providers into one normalized context object
- stronger symbol mapping and provider arbitration
- caching and freshness strategy
- more deliberate workflow-level use of these providers

### 4. Persistence

Implemented:
- file-backed persistent guideline memory in JSON
- reusable structured document store
- CRUD operations on guideline nodes
- scoped Markdown rendering for prompt injection

Current status:
- long-term policy/config-style memory is in place
- this is the only real persistent storage currently wired

Missing:
- SQLite operational persistence
- Alembic migrations for real application data
- proposal storage
- execution attempt storage
- approval record storage
- reconciliation/audit persistence

### 5. Workflows

Implemented:
- workflow modules exist as placeholders

Current status:
- `proposal.py`, `order_review.py`, `attention_scan.py`, and `digest.py` are still placeholders
- there is no real workflow layer yet connecting agents to deterministic Python execution steps

Missing:
- portfolio summary workflow
- pending orders review workflow
- company snapshot workflow
- market snapshot workflow
- proposal generation workflow
- execution/reconciliation workflow
- scheduled digest and alert workflows

### 6. Runtime Wiring

Implemented:
- `AppRuntime`
- settings loading from `.env`
- guideline memory service wiring

Current status:
- runtime is still too thin
- it does not yet act as the real composition root of the application

Missing:
- Trading 212 client/service wiring
- Yahoo, Alpha Vantage, Reddit wiring
- GenAI client/runtime wiring at app level
- workflow wiring
- DB/session wiring
- proposal/approval service wiring

## Current State Vs Target

| Area | Target | Current Status |
| --- | --- | --- |
| Core repo structure | stable baseline repo | mostly done |
| Telegram bridge | natural-language front door | partially done |
| Trading 212 integration | normalized broker interface + tools | baseline done |
| External data | multi-provider research/context layer | baseline done, not unified |
| Orchestrator/specialists | routed agent-of-agents design | done at baseline |
| Persistent memory | long-term guidelines/config memory | done at baseline |
| Workflow layer | deterministic operational workflows | not done |
| Proposal engine | structured persisted proposals | partially done conceptually, not operationally |
| Approval flow | Telegram-driven approval for risky actions | not done |
| SQLite/Alembic | operational persistence | not done |
| Demo execution pipeline | proposal -> approval -> execution -> reconciliation | not done |
| Scheduled jobs | digests, scans, alerts | not done |

## Main Missing Pieces

In priority order, the missing pieces are:

1. Expand `AppRuntime` into the real composition root.
2. Implement real workflows instead of placeholders.
3. Make specialist agents call workflows, not only produce plans.
4. Add SQLite/Alembic persistence for proposals, approvals, and executions.
5. Implement the proposal lifecycle.
6. Implement Telegram approval flow.
7. Add reconciliation and execution audit trail.
8. Build a unified market-context layer across providers.
9. Add scheduled jobs only after the manual path works end-to-end.

## Practical Read On The Repo

The repo is no longer at the design-only stage.

It is also not yet at the “usable end-to-end copilot” stage.

The current state is:
- architecture baseline: in place
- integrations baseline: in place
- agent baseline: in place
- long-term guideline memory: in place
- real operational wiring: still missing

## Recommended Next Build Order

1. Expand `AppRuntime` so it owns all main services and clients.
2. Implement the first real read-only workflows:
   - portfolio summary
   - pending orders review
   - company snapshot
   - market snapshot
3. Wire specialist agents to these workflows.
4. Make Telegram return real workflow-backed answers.
5. Add SQLite/Alembic persistence.
6. Add proposal creation and retrieval.
7. Add approval flow.
8. Add demo execution and reconciliation.

## Short Conclusion

The architecture direction is correct.

The repo already contains most of the foundational pieces needed for v1, but the main missing layer is application wiring: runtime composition, workflow execution, persistence, and approval-driven operational flow.
