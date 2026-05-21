# Agentic Logic

Status: design reference.

## Core Idea

The agent should be natural-language first.

Static commands are fine, but they should only be shortcuts into the same internal capability model. The real product is:

- the user states a goal in plain language
- the agent interprets the goal
- the agent selects tools dynamically
- the agent gathers context
- the agent explains, proposes, or acts
- the agent verifies the outcome

This is more important than having a long command list.

## Confirmed Baseline

- personal-use only
- Python-first implementation
- local development first, then containerization
- Trading 212 demo first
- manual Telegram confirmation for every live decision
- commands exist as fallbacks, with `/help` for discoverability
- lightweight local persistence only where it protects the workflow

## Why This Matters

Real user requests will be messy and contextual:

- "Cancel the oldest pending order for Tesla."
- "Should I cancel any stale pending orders before the open?"
- "Look at my current positions, the latest news, and tell me what I should pay attention to."
- "Trim my largest holding if it exceeds my policy."

If the design is command-first, these become hard-coded flows too early. If the design is capability-first, they become reusable compositions of tools.

## Interaction Model

### Primary path

- Telegram natural-language chat

### Secondary path

- slash commands for speed, discoverability, and common workflows
- button-based approval or rejection messages in Telegram

Both paths should end in the same internal intent-resolution and tool-planning logic.
Approvals are the exception: natural language may request, discuss, or revise an
action, but it must not approve or reject a pending side effect. Pending actions
are resolved only through deterministic Telegram button callback payloads.

## Capability Model

The agent should not think in terms of commands. It should think in terms of capabilities.

### Read-only capabilities

- get account summary
- get positions
- get pending orders
- get historical orders and transactions
- get market data
- get news and research context
- compute allocation and risk metrics
- explain portfolio changes

### Advisory capabilities

- analyze a ticker
- review pending orders
- identify portfolio risks
- propose a rebalance
- propose a buy or sell
- summarize recent catalysts

### State-changing capabilities

- place market order
- place limit order
- place stop order
- place stop-limit order
- cancel pending order
- create or update watches and alerts

## Tool Selection Rules

Every tool should carry metadata:

- read-only or state-changing
- approval required or not
- deterministic or LLM-assisted
- rate-limited or not
- authoritative or informational

This lets the planner compose actions safely.

## Toolbox Assembly Logic

Toolboxes can be created by capability scope, such as broker read tools,
order-planning tools, market-data tools, or research tools. These scope-based
toolboxes are useful as reusable building blocks.

The toolbox attached to an actual LLM call should normally be defined by the
agent, flow, or process that is running, not by raw scope alone. For example:

- a portfolio-summary agent may receive broker snapshot and market-summary tools
- an order-review flow may receive pending-order, quote, news, and prepare-order tools
- an execution-confirmation flow may receive only the exact execution tools it needs
- a digest job may receive read-only broker, market, news, and calendar tools

This keeps the tool surface narrow for each reasoning context while still letting
the implementation reuse scope-based tool groups internally.

## Tool Result Contract

Tool outputs are part of the LLM context, so they should be informative enough
for reasoning without forcing the model to infer hidden state from metadata.

Good tool results should include:

- a concise but content-rich `output` string that states what was retrieved,
  what source is authoritative, and what the important facts are
- structured `data` for exact downstream parsing
- error messages that explain the likely cause and the safest next action
- hints that help the LLM pivot parameters, ask the user, retry later, or stop
  safely

Avoid terse outputs like `ok`, `done`, or `retrieved 3 items` for tools that
feed decisions. Metadata is useful for tracing, but the agent should primarily
consume domain-specific facts, caveats, and recovery guidance.

## Recommended Agentic Patterns

Use these patterns in the baseline runtime:

- routing for mapping messages into read-only, advisory, execution, and admin intents
- prompt chaining for intent extraction, evidence synthesis, and final answer/proposal
- tool use for all broker, market, and research actions
- planning for requests that need multiple dependent steps
- parallelization for independent market/news/calendar fetches
- reflection as a single-pass quality check on proposals or ambiguous summaries
- human-in-the-loop for any state-changing action in live mode
- memory management split into short-term chat memory and small persisted operational state
- exception handling and recovery for provider failures, ambiguous broker outcomes, and retries
- guardrails for schema validation, policy checks, and source trust
- prioritization for ranking alerts, opportunities, and portfolio-attention items
- exploration and discovery for watchlist scanning, news expansion, and web-search follow-ups

Keep these out of the baseline unless a concrete need appears:

- multi-agent swarms
- A2A communication frameworks
- learning/adaptation loops
- heavy RAG infrastructure
- full autonomous goal systems

## Agent Loop Contract

Each agent can be configured to run all or part of this loop:

1. Reason.
   - Input: recent chat history, invocation reason from the orchestrator, optional structured intent, persistent guidance, and available toolbox descriptions.
   - Tools: none.
   - Output: structured reasoning context for the next step, not hidden chain-of-thought.
2. Plan.
   - Input: history, invocation reason, intent, reasoning context, and available toolbox descriptions.
   - Tools: none.
   - Output: structured plan with ordered actions, dependencies, parallelization flags, missing inputs, assumptions, risks, and approval requirements.
3. Execute.
   - Input: history, invocation reason, intent, reasoning context, plan, prior action outputs, and the agent's configured toolbox.
   - Tools: the deliberately narrow toolbox for that agent or flow.
   - Behavior: execute plan actions sequentially unless the plan marks independent actions as parallelizable.
4. Judge.
   - Input: original request, intent, reasoning context, plan, tool outputs, and draft result.
   - Tools: normally none, unless a specific verification flow needs read-only checks.
   - Output: structured critique covering completeness, safety, grounding, and clarity.
5. Return.
   - Input: accepted execution output and judge result.
   - Output: concise result back to the orchestrator or caller, including caveats, follow-up options, and approval payloads when a side effect is prepared.

The loop is configurable. Simple deterministic workflows can plug only execute
and return. Advisory analysis can use reason, plan, execute, judge, and return.
State-changing workflows must separate preparation from approval and execution.

## Example: Cancel Order

User:

"Cancel my oldest pending buy order if it is still open."

Agent plan:

1. Fetch pending orders from Trading 212.
2. Filter to pending buy orders.
3. Sort by creation time.
4. Select the oldest open candidate.
5. If one clear candidate exists, create a cancel action plan.
6. Apply approval policy.
7. Call cancel order.
8. Re-fetch pending orders or order status.
9. Report result in Telegram.

This is a dynamic tool workflow, not a fixed command.

## Example: Review Pending Orders

User:

"Check whether any of my pending orders should be cancelled."

Agent plan:

1. Load pending orders.
2. Load latest market data for each relevant ticker.
3. Load recent news or event context if required.
4. Evaluate stale-price distance, age, event risk, and user policy.
5. Return ranked recommendations:
   - keep
   - cancel
   - modify later if supported
6. If the user approves a cancellation with the Telegram button, execute it.

## Example: Attention Scan

User:

"Tell me what needs attention in my portfolio today."

Agent plan:

1. Load account summary and positions.
2. Compute concentration, drawdown, and pending-order risk.
3. Pull latest market data.
4. Pull news and event context.
5. Create a structured attention report:
   - urgent items
   - watch items
   - no-action items
6. Suggest next actions without executing anything automatically.

## Clarification Strategy

The agent should avoid unnecessary back-and-forth, but it should ask when ambiguity is dangerous.

Ask a clarifying question when:

- the ticker or order target is ambiguous
- the request could affect multiple open orders
- a live side effect would otherwise rely on a guess

Do not ask when:

- the target is obvious from context
- the request is read-only and ambiguity can be handled by ranked options
- the request is just a command shortcut for a known single-step action

## Safety Constraints

- LLM output never calls tools directly
- tool inputs must match schemas
- all state changes are logged
- state-changing tools require policy checks first
- uncertain executions must be reconciled before retry
- natural language can drive the workflow, but not bypass the controls
- live decisions require explicit Telegram button approval

## Recommended v1 Scope

Build these dynamic flows first:

1. portfolio summary and attention scan
2. ticker analysis with research
3. trade proposal generation
4. pending-order review
5. single-order cancellation
6. daily digest and scheduled briefing
7. `/help` plus command fallbacks for the most common actions

That gives you real agent behavior without jumping straight into full autonomy.
