# Agentic Patterns Baseline

Status: design reference.

## Goal

Use a small number of agentic patterns that materially improve the Trading 212 Telegram agent without turning the system into an overengineered multi-agent platform.

This document is based on the pattern families you listed from your guide, but applies only the subset that is useful for the current baseline.

## Use Now

### 1. Routing

Use for:

- classifying Telegram input into read-only, advisory, execution, admin, or scheduling intents
- deciding whether the request needs clarification

Why now:

- this is the cleanest way to support free text and slash commands through the same runtime

### 2. Prompt Chaining

Use for:

- intent extraction
- evidence synthesis
- final answer or proposal generation

Why now:

- it keeps prompts narrow and reduces the chance that one giant prompt becomes fragile

### 3. Tool Use

Use for:

- Trading 212 actions
- market/news/calendar fetches
- portfolio analytics
- watchlist and digest operations

Why now:

- this is the actual backbone of the agent

### 4. Planning

Use for:

- multi-step requests such as pending-order review, rebalance proposals, or cancellation requests with filters

Why now:

- many useful requests require more than one tool call, but not a full autonomous planner

Keep it light:

- only build explicit plans for tasks with dependencies or side effects

### 5. Parallelization

Use for:

- fetching prices, news, calendars, and portfolio state when they are independent

Why now:

- improves latency without changing the core logic

### 6. Reflection

Use for:

- single-pass checking of proposals, summaries, or ambiguous outputs

Why now:

- helps improve proposal quality without introducing long self-critique loops

Keep it light:

- one verification pass, not recursive debate

### 7. Memory Management

Use for:

- short-term Telegram context
- persisted operational state in SQLite

Why now:

- the agent needs continuity across turns and process restarts

Keep it small:

- proposals
- approvals
- execution records
- policies
- watchlists
- digest state

### 8. Goal Setting And Monitoring

Use for:

- daily digests
- scheduled briefings
- watchlist and portfolio monitoring jobs

Why now:

- these are practical scheduled behaviors, not autonomous goals

### 9. Exception Handling And Recovery

Use for:

- Trading 212 submit uncertainty
- provider failures
- stale or conflicting data
- safe retry and reconciliation

Why now:

- this directly protects the trading workflow

### 10. Human-in-the-Loop

Use for:

- every live order or cancellation
- ambiguous state-changing requests

Why now:

- this is a hard requirement from your baseline

### 11. Guardrails / Safety Patterns

Use for:

- tool schema validation
- policy checks
- source trust rules
- demo/live separation
- idempotency guard

Why now:

- these are required, not optional, for a broker-connected agent

### 12. Evaluation And Monitoring

Use for:

- replaying a few canonical requests
- checking proposal schema quality
- checking that execution never bypasses approval

Why now:

- even a small agent benefits from a lightweight regression harness

Keep it pragmatic:

- a few scenario fixtures are enough at the start

### 13. Prioritization

Use for:

- ordering alerts
- ranking attention items
- deciding which market/news items matter most

Why now:

- the agent should not dump raw noise into Telegram

### 14. Exploration And Discovery

Use for:

- watchlist scanning
- news expansion
- web-search follow-ups
- optional community-signal discovery

Why now:

- helps idea discovery without committing to autonomous trading

## Use Later, If Needed

### Multi-Agent

Possible use:

- on-demand deep company research specialist
- macro brief specialist

Not baseline because:

- the main runtime is simpler and safer as one orchestrator plus bounded tools

### Knowledge Retrieval (RAG)

Possible use:

- retrieval over your own notes, strategy docs, or saved research packets

Not baseline because:

- the first version does not need a vector store to be useful

### Resource-Aware Optimization

Possible use:

- smaller model for routing
- stronger model for proposals and digests

Not baseline because:

- useful, but secondary to getting the workflow correct

### Reasoning Techniques

Possible use:

- structured compare-and-choose prompts
- explicit pros/cons and risk review

Not baseline because:

- basic structured reasoning is enough at the start

## Avoid In v1

- inter-agent communication frameworks
- learning and adaptation loops
- autonomous self-set goals
- broad memory stores
- heavy audit or observability platforms
- swarm-style research agents

## Pattern Map By Sub-Process

### Telegram Intake

- routing
- short-term memory
- clarification strategy

### Portfolio Summary And Attention Scan

- tool use
- parallelization
- prompt chaining
- prioritization

### Research Packet Generation

- tool use
- exploration and discovery
- parallelization
- prompt chaining

### Trade Proposal Generation

- planning
- prompt chaining
- reflection
- guardrails
- human-in-the-loop

### Order Execution And Cancellation

- tool use
- guardrails
- exception handling and recovery
- human-in-the-loop

### Digests And Scheduled Jobs

- goal setting and monitoring
- prioritization
- prompt chaining

## Recommended Baseline Runtime

1. Route the incoming request.
2. Build a small plan if the task is multi-step.
3. Run read-only tools, in parallel where possible.
4. Build structured context.
5. Let the LLM explain or propose.
6. Run guardrails and policy checks.
7. Require human approval for live side effects.
8. Execute once.
9. Reconcile and persist the minimal operational state.

That is the optimal baseline for this project. It gives you real agent behavior without dragging in patterns that you do not need yet.
