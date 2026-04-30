# Trading 212 Telegram Agent Design

Status: design reference.

## Design Principles

- The LLM should advise and explain. Deterministic code should enforce policy and execute.
- Every trade must be traceable to data, rules, and a user or system approval event.
- Demo trading should be the default execution environment until the workflow is proven.
- The agent should produce structured outputs, not free-form commands.
- External data needs freshness metadata and source provenance.
- A failed or uncertain execution attempt must never be retried blindly.
- Natural language should be the main interface. Commands should be convenience wrappers, not the core model.
- This is a personal-use system, so the design should stay compact and operationally simple.
- Use lightweight local persistence first: SQLite with Alembic-managed schema migrations.

## High-Level Architecture

```text
Telegram Bot
  -> Command / message router
  -> Agent orchestrator
     -> Trading 212 client
     -> External data adapters
     -> News and web research pipeline
     -> Portfolio analytics engine
     -> Risk and policy engine
     -> Local state store (SQLite + Alembic)
     -> Execution service
     -> Scheduler / alert jobs
     -> Operational log
```

## Confirmed Baseline

- single-user, personal account only
- demo first, live later
- all Trading 212 order types should be supported
- extended-hours trading should be disabled by default
- every live order or cancellation requires Telegram confirmation
- approval and rejection are button-only; natural-language messages may request,
  discuss, or revise actions, but they do not resolve pending side effects
- free-text interaction is the primary UX
- slash commands remain available as shortcuts, including `/help`
- broad market context matters first; deep company research can come later
- use lightweight persistence for operational state, not a large data platform

## Suggested Component Responsibilities

### Telegram bot layer

- receive commands and natural-language prompts
- send summaries, proposals, approvals, and alerts
- expose approve/reject actions safely
- normalize Telegram updates into app-level message objects
- authorize chats before the agent sees the request
- keep Telegram-specific SDK objects out of the agent/workflow layers

### Agent orchestrator

- classify user intent
- gather the required account and market context
- choose whether the task is read-only analysis or execution-related
- call the LLM only after deterministic context is assembled
- build a stepwise tool plan when the task requires multiple actions
- keep clarification loops short and only ask when ambiguity affects a side effect

### Trading 212 client

- handle auth and environment selection
- normalize account, positions, orders, and history responses
- place and cancel supported order types
- respect endpoint-specific rate limits

### External data adapters

- fetch market data, fundamentals, news, calendar events, and other signals
- normalize symbols and timestamps
- cache slow or rate-limited datasets
- tag every field with provider, freshness, and intended usage class

### News and web research pipeline

- query news feeds or search tools for a ticker, portfolio theme, or macro topic
- fetch and normalize source metadata
- classify event type, relevance, sentiment, and novelty
- cluster duplicate stories
- extract evidence objects with citation links and timestamps
- expose only structured research packets to the LLM

### Portfolio analytics engine

- compute allocation, concentration, unrealized PnL, exposure, and cash usage
- track changes since the last snapshot
- prepare structured context for the LLM

### Risk and policy engine

- validate whether a proposal is allowed
- enforce position, turnover, and concentration limits
- require approval where needed
- block stale-data decisions

### Execution service

- translate approved proposals into Trading 212 order requests
- apply local idempotency protections
- reconcile uncertain outcomes before any retry

### Tool registry

- define what the agent is allowed to do
- describe tool schemas, side effects, approval requirements, and risk class
- separate read-only tools from state-changing tools
- give the planner a bounded capability surface
- expose final toolboxes by agent or flow, using scope-based groups only as
  internal building blocks
- return LLM-readable outputs and actionable error hints, not only operational
  metadata

## Recommended Agent Pattern

Keep the first implementation simple:

- one orchestrator service
- one LLM-assisted analyst
- one deterministic risk engine
- one deterministic execution service
- one lightweight local state store

Do not start with multiple autonomous agents talking to each other. That adds complexity before the core workflow is safe.

## Recommended Pattern Stack

Use a small subset of agentic patterns as the baseline:

- routing for intent classification
- prompt chaining for analysis and proposal generation
- tool use as the core capability model
- planning only for multi-step tasks
- parallelization for independent data fetches
- lightweight reflection for proposal quality checks
- human-in-the-loop for any live side effect
- minimal memory management for session state and persisted operational state
- exception handling and recovery around broker/API failures
- guardrails and policy checks before state-changing tools
- prioritization for alerts, digests, and attention scans
- exploration and discovery for news, search, and watchlist research

Patterns that should stay out of the initial baseline:

- autonomous multi-agent swarms
- inter-agent communication frameworks
- learning/adaptation loops
- heavy RAG or vector database infrastructure
- MCP as a core runtime dependency

See `AGENT_PATTERNS.md` for the concrete mapping.

## Interaction Pattern

Build the system around a capability-driven agent:

- natural-language input comes in from Telegram
- the intent layer converts it into a structured task
- the planner selects tools and sequences them
- read-only tools gather context
- the LLM explains or proposes using structured outputs
- state-changing tools are only called through policy gates

Slash commands can call the same internal capability graph, but they should not be a separate logic path.

## Configurable Agent Loop

Specialist agents should converge on a configurable loop:

- reason over recent chat history, invocation reason, optional orchestrator intent, persistent guidance, and toolbox descriptions with no tools attached
- plan with structured output that includes action ordering, dependencies, parallelization flags, assumptions, risks, missing inputs, and approval requirements
- execute the plan action by action with the agent's narrow toolbox, passing previous action outputs into later steps
- judge the draft result for completeness, safety, grounding, and clarity
- return a concise result package to the orchestrator or caller

Agents do not all need every step. Deterministic workflows may plug only execute
and return. Complex advisory agents should use the full loop. State-changing
flows must split proposal/preparation from button approval and final execution.

## Tool Spectrum

The agent should reason over a bounded set of tool classes:

- account tools
- order tools
- portfolio analytics tools
- market data tools
- research tools
- watchlist and alert tools
- memory and policy tools

Each tool should declare:

- name
- purpose
- input schema
- output schema
- side-effect flag
- approval requirement
- retry policy
- operational log fields

The implementation can maintain reusable scope groups such as `broker_read`,
`order_planning`, `market_data`, or `research`, but the runtime should plug in
agent-defined toolboxes. A portfolio-summary agent, order-review flow, digest
job, and execution-confirmation flow should each receive a deliberately narrow
toolbox for their context.

Tool results should be designed as context packets for the LLM. For broker and
market tools, the `output` should summarize authoritative facts and decision
caveats in plain language, while `data` carries the exact structured payload.
Error results should include likely causes, recovery hints, and whether the
agent should retry, pivot parameters, ask the user, or stop.

## Data Source Tiers

Use explicit source tiers so the system knows what it can trust for each task.

### Tier 0: Broker-authoritative

- Trading 212

Use for:

- account summary
- cash
- positions
- pending orders
- historical orders and transactions
- order execution and cancellation

Never replace broker state with third-party estimates.

### Tier 1: Execution-adjacent market data

- one designated price feed, with free or low-friction options preferred first

Use for:

- latest price context
- intraday bars
- session-aware alerts
- watchlist monitoring
- price-based trigger logic

This is the right place for real-time or streaming price context.

### Tier 2: Enrichment and research

- Alpha Vantage or similar providers
- other fundamentals, macro, or event APIs
- news APIs
- web search tools used for discovery
- calendar sources

Use for:

- fundamentals
- economic indicators
- technical indicators
- screening inputs
- slow-moving company or ETF metadata

This layer improves decision quality but should not overwrite broker facts.

### Tier 3: Informational and convenience sources

- Yahoo Finance and similar convenience sources
- generic web pages discovered through search
- community sources such as Reddit

Use for:

- cross-checking
- quick summaries
- convenience features
- non-critical research augmentation

Do not make this tier a hard dependency for order execution.

## Decision Flow

### Read-only flow

1. Receive Telegram request.
2. Resolve the user's intent and identify the required tools.
3. Load latest account and market context.
4. Compute deterministic analytics.
5. Ask the LLM for explanation or recommendation in a structured schema.
6. Return a concise answer with evidence and caveats.

### Trade proposal flow

1. Receive trade request or idea-generation request.
2. Resolve intent and create a provisional action plan.
3. Build a portfolio snapshot and market context.
4. Ask the LLM for a structured proposal:
   - action
   - ticker
   - sizing idea
   - order type
   - thesis
   - supporting evidence
   - key risks
   - confidence
5. Run deterministic policy checks.
6. If checks pass, persist the proposal and send it to Telegram for approval.
7. After approval, convert the proposal into a concrete Trading 212 order payload.
8. Submit once.
9. Reconcile account state and pending orders.
10. Notify the user of the resulting state.

### Dynamic action flow

This covers requests such as "cancel my oldest pending order" or "tell me whether any pending orders should be cancelled."

1. Receive a natural-language request.
2. Convert it into a structured intent such as `cancel_order`, `review_orders`, or `portfolio_attention_scan`.
3. Build a tool plan.
4. Execute read-only steps first.
5. If the action is unambiguous and policy allows it, create an execution plan.
6. If ambiguity remains, ask one focused clarifying question or return ranked options.
7. Apply the approval policy.
8. Execute the state-changing tool.
9. Verify the resulting broker state.
10. Return a concise explanation of what happened.

## Safety Model

### Hard rules

- no live execution without explicit configuration
- no live execution without explicit Telegram confirmation
- no order execution directly from raw LLM text
- no retry of a failed submit until reconciliation is complete
- no execution from stale or partial account state
- no execution if required external inputs are missing
- no execution outside allowed instruments or allocation policy
- no execution when source conflicts exceed defined tolerance
- no live trade triggered from a single news item or search result
- no execution from uncited web summaries
- no state-changing tool access without schema validation and operational logging

### Soft rules

- require two or more evidence sources for thesis-based trades
- downgrade confidence when data freshness is weak
- apply cooldowns after repeated buys or sells in the same instrument
- make event risk explicit before execution when earnings or macro events are close

## Trading 212-Specific Execution Risks

The Trading 212 docs imply several design requirements:

- order endpoints are non-idempotent, so duplicate submissions are a real risk
- sell orders use negative quantity, which must be handled explicitly
- main-account-currency execution means sizing logic must be currency-aware
- per-endpoint rate limits vary and should be encoded in the client
- exchange metadata should be used to reason about market sessions

## Local Idempotency Strategy

Because Trading 212 does not provide idempotent order creation in the current beta API, the system should create its own execution guard:

1. Create a `proposal_id`.
2. Build an `order_fingerprint` from account, ticker, side, quantity, order type, prices, and a short validity window.
3. Store `submission_status = pending_local`.
4. Submit the order once.
5. If the HTTP result is uncertain, mark the order as `unknown_remote_state`.
6. Query pending orders and recent history before allowing any retry.
7. Only retry if reconciliation shows that no equivalent order exists.

This is one of the most important parts of the design.

## Source Arbitration Rules

When multiple providers return overlapping data, the system should resolve them deterministically:

1. Prefer Trading 212 for account and order state.
2. Prefer the designated real-time feed for latest price and intraday signals.
3. Prefer enrichment providers for fundamentals, macro, and derived indicators.
4. Prefer primary or official sources over commentary when evaluating news-driven claims.
5. If two sources disagree materially, flag the discrepancy and downgrade or block the decision.
6. Store which source actually supplied each field used in a proposal.

## News And Search Rules

Use news and web search to improve awareness, not to bypass risk controls.

1. Treat search as a discovery mechanism, not an authoritative source by itself.
2. Prefer primary sources when available:
   - company investor relations
   - exchange notices
   - regulatory filings
   - official macro releases
3. Require citation URLs, publisher names, publish times, and retrieval times in every research packet.
4. Distinguish article publish time from the underlying event time.
5. Deduplicate repeated coverage of the same event before scoring relevance.
6. Do not trade on a single unsourced headline.

## Domain Model Draft

```ts
type Environment = "demo" | "live";

type ApprovalMode = "none" | "manual" | "policy_auto";

type OrderType = "market" | "limit" | "stop" | "stop_limit";

type Action = "buy" | "sell" | "reduce" | "exit" | "cancel";

interface UserPolicy {
  environment: Environment;
  approvalMode: ApprovalMode;
  baseCurrency: string;
  allowedTickers: string[];
  blockedTickers: string[];
  maxOrderValue: number;
  maxPositionValue: number;
  maxSingleNameWeightPct: number;
  maxDailyTurnover: number;
  allowExtendedHours: boolean;
}

interface PositionSnapshot {
  ticker: string;
  quantity: number;
  averagePrice: number;
  marketValue: number;
  unrealizedPnl: number;
  weightPct: number;
}

interface PortfolioSnapshot {
  asOf: string;
  cash: number;
  totalValue: number;
  positions: PositionSnapshot[];
  pendingOrdersCount: number;
  largestPositionWeightPct: number;
}

interface EvidenceItem {
  source: string;
  timestamp: string;
  summary: string;
  relevance: number;
  url?: string;
  evidenceType?: "market_data" | "fundamental" | "news" | "web";
}

interface ResearchPacket {
  topic: string;
  ticker?: string;
  generatedAt: string;
  items: EvidenceItem[];
  noveltyScore: number;
  sourceDiversity: number;
}

interface AgentIntent {
  kind:
    | "portfolio_summary"
    | "portfolio_attention_scan"
    | "analyze_instrument"
    | "propose_trade"
    | "place_order"
    | "cancel_order"
    | "review_pending_orders"
    | "rebalance";
  entities: Record<string, string | number | boolean>;
  confidence: number;
}

interface ToolCapability {
  name: string;
  riskClass: "read_only" | "advisory" | "state_changing";
  requiresApproval: boolean;
  inputSchemaName: string;
  outputSchemaName: string;
}

interface ActionStep {
  toolName: string;
  purpose: string;
  dependsOn?: string[];
}

interface ActionPlan {
  intent: AgentIntent;
  steps: ActionStep[];
  requiresApproval: boolean;
}

interface MarketDataPoint {
  field: string;
  value: string | number | boolean;
  provider: string;
  asOf: string;
  freshnessSeconds: number;
  usageClass: "broker" | "execution_adjacent" | "research" | "informational";
}

interface TradeIntent {
  action: Action;
  ticker: string;
  orderType: OrderType;
  quantity?: number;
  valueBudget?: number;
  limitPrice?: number;
  stopPrice?: number;
  extendedHours?: boolean;
}

interface TradeProposal {
  proposalId: string;
  createdAt: string;
  intent: TradeIntent;
  thesis: string;
  risks: string[];
  evidence: EvidenceItem[];
  confidence: number;
  requiresApproval: boolean;
}

interface SafetyCheckResult {
  passed: boolean;
  blockingReasons: string[];
  warnings: string[];
}

interface ExecutionRecord {
  proposalId: string;
  orderFingerprint: string;
  t212OrderId?: number;
  status:
    | "pending_local"
    | "submitted"
    | "unknown_remote_state"
    | "confirmed_open"
    | "cancelled"
    | "rejected";
}
```

## Data Storage

Use a lightweight local relational database from the start:

- SQLite for the local database
- Alembic for schema migrations
- SQLAlchemy or equivalent ORM layer if helpful in implementation

Persist only the minimum operational state that protects the workflow:

- trade proposals
- approvals and rejections
- execution records
- user policy and watchlists
- alert definitions and last-run state
- scheduled digest state
- intent classifications and action plans when they matter across turns
- lightweight cached provider metadata where useful

Optional later:

- account or position snapshots if you need historical comparisons not available from APIs
- weekly or Monday highlights
- richer research history

Do not build a broad warehouse, vector store, or full audit system in v1.

## Operational Logging

Store only enough detail to debug actions and recover safely:

- incoming intent
- selected tools
- proposal identifiers
- order fingerprint and broker response status
- approval or rejection event
- reconciliation outcome

This is operational state, not a broad compliance-grade audit layer.
