# Scheduler Design Notes

Last updated: 2026-05-07

This document captures the scheduler discussion before implementation. The user's view is treated as the product/source-of-truth intent. The assistant design notes are separated so implementation choices remain reviewable and adjustable.

## User View

The scheduler should let LLM-based agents and orchestrators create and manage background trading-related activities from natural language.

The goal is broader than simple cron jobs. The system should support subprocesses that can run at specific times, recur, poll deterministic conditions, gather market context, invoke LLM analysis when useful, and notify the user through Telegram in natural language when something relevant happens.

Useful examples include:

- Run an LLM-assisted quarterly-report analysis for a company at a specified time, such as 22:00 CET.
- Monitor a ticker price or percentage variation and notify when it reaches a target, monthly low, all-time low, or similar condition.
- Monitor broad market stress, such as Nasdaq falling by a configured percentage intraday, then search for news and explain what may be happening.
- Watch a trading setup, trigger on deterministic conditions, gather context, reason about it, and potentially create an order proposal for explicit user approval.

The scheduler should be invokable by other agents through a tool that accepts a natural-language request describing the scheduling/process scope. The tool output should be useful to the invoking agent, for example confirming that a process was submitted, explaining why a request cannot be handled, or asking for a more precise instruction.

Subprocesses may have different natures:

- Fully or mostly deterministic, such as polling a price threshold.
- LLM-assisted, such as gathering report data and asking an LLM to analyze the impact.
- More agent-like, when a bounded sub-agent uses a dedicated prompt and limited tools to perform research or analysis.

Some jobs should be one-shot, some recurring, and some polling-based. Jobs also need lifecycle rules so they can complete, expire, pause, or be archived. For example, a Tesla price monitor may run until the condition is met, then die automatically, or it may expire intraday if the condition never happens.

## Assistant Design Notes

The implementation should use a dynamic natural-language interface backed by typed deterministic process specifications.

The LLM should translate intent, fill process specs, provide analysis, and write user-facing notifications. The deterministic scheduler should own persistence, trigger evaluation, retries, cooldowns, lifecycle transitions, and safety boundaries.

The system should avoid storing arbitrary prompts like "run this agent every hour with all tools and let it decide what to do." That is hard to validate, audit, rate-limit, test, and keep away from broker-side side effects.

Instead, each scheduled process should declare:

- `kind`: the supported process type, such as `company_event_analyst` or `instrument_monitor`.
- `execution_mode`: deterministic, LLM-assisted, or bounded LLM-planned.
- `schedule`: one-shot, recurring, polling, or manual.
- `trigger`: the deterministic due condition or market condition.
- `inputs`: symbols, sectors, sources, thresholds, watchlists, report type, or other process-specific parameters.
- `llm_scope`: optional system prompt ID, task guidelines, allowed tools, and output contract.
- `notification`: Telegram or later notification targets, formatting, and whether LLM wording is used.
- `lifecycle`: completion policy, expiry, max runs, max matches, cooldown, pause/archive state.
- `safety`: no broker execution by default; order-related workflows can only create pending proposals requiring explicit approval.

## Architectural Definitions

The scheduler should use a layered architecture. The reusable modules are not agents by default. They are bounded capabilities used by process adapters. Some modules may call an LLM or a specialist agent, but they do not autonomously schedule themselves or decide their own tool access.

```text
Main Orchestrator
  -> routes user requests and invokes scheduler delegation when needed

Scheduler Agent
  -> translates natural language into validated process specs
  -> manages process creation, listing, pausing, resuming, and archiving
  -> returns useful explanations to the invoking agent

Scheduled Process
  -> persisted job definition with schedule, trigger, lifecycle, inputs, LLM scope, action, and safety policy

Process Adapter
  -> executable implementation for a supported process kind
  -> combines reusable modules in a deterministic order
  -> decides when an LLM call is appropriate according to the process spec

Reusable Modules
  -> schedule, trigger, gather, analyze, act, lifecycle, notify
  -> deterministic by default unless explicitly configured to call LLMs
```

The practical rule is: the scheduler agent creates and manages process definitions; the worker runs process adapters; process adapters use reusable modules; modules do the smallest possible unit of work.

## Reusable Modules

### `schedule`

Capability:

- Parse and normalize schedule definitions.
- Compute `next_run_at` in UTC.
- Support one-shot, recurring, polling, and manual schedules.
- Keep timezone explicit, using IANA zones such as `Europe/Rome`.

LLM involvement:

- Low during creation only. The scheduler agent may translate "every weekday at 10pm CET" into a schedule spec.
- None during worker execution. Runtime due checks should be deterministic.

LLM scope:

- Interpret human scheduling language.
- Ask for clarification or reject unsupported timing instructions.
- Never decide at runtime whether a due job should run.

### `trigger`

Capability:

- Evaluate deterministic conditions.
- Support market-data triggers such as price above/below, percentage move, index drawdown, volume spike, monthly low, or all-time low.
- Support event-availability triggers such as a report, filing, or disclosure becoming available.
- Return match evidence, such as observed value, threshold, timestamp, and source freshness.

LLM involvement:

- None or very low. Trigger matching should be deterministic.
- LLM may help translate a user request into a supported trigger spec during creation.

LLM scope:

- Convert natural language such as "alert me if Nasdaq is crashing today" into explicit fields, for example index symbol, intraday drawdown threshold, polling interval, and expiry.
- Do not allow the LLM to invent hidden trigger conditions at runtime.

### `gather`

Capability:

- Retrieve the context required by a process adapter.
- Use existing market data, search, scraped pages, SEC/filing/disclosure services, Reddit/community context, broker portfolio/watchlist context, and market signal memory where configured.
- Produce compact structured evidence for analysis or notification.

LLM involvement:

- Low to medium depending on the process.
- Deterministic gatherers should call known services with explicit parameters.
- LLM may be used to choose among a limited set of search queries in bounded LLM-planned processes.

LLM scope:

- For deterministic and LLM-assisted modes, the LLM should not freely browse or choose unlimited tools.
- For bounded LLM-planned mode, the LLM can select from an allowlisted toolbox with max steps, timeout, and output schema.

### `analyze`

Capability:

- Turn gathered evidence into a trading-relevant interpretation.
- Reuse existing specialist agents when appropriate, especially the market analyst agent.
- Produce structured conclusions, risks, relevant time horizon, source references, and notification-ready summaries.

LLM involvement:

- Medium to high.
- Deterministic processes may skip this module or use it only for notification wording.
- LLM-assisted processes use this module as the main value-producing step.

LLM scope:

- Analyze only the gathered evidence and the configured task guidelines.
- State uncertainty and source limitations.
- Treat market signals as advisory context.
- Never execute trades.
- For order-related flows, produce a proposal rationale only; order proposal creation remains a separate guarded action.

### `act`

Capability:

- Apply the configured action after a run or trigger match.
- Actions may include notify-only, save a market signal, create a pending order proposal, schedule a follow-up, complete a process, or archive a process.

LLM involvement:

- Low.
- The LLM may draft action explanations.
- The actual action execution must be deterministic and validated.

LLM scope:

- Explain what action is being taken and why.
- Do not decide to expand action scope beyond the process spec.
- Do not directly execute broker actions.

### `lifecycle`

Capability:

- Move processes between `active`, `paused`, `completed`, `expired`, `archived`, and `failed`.
- Enforce max runs, max matches, expiry, cooldowns, and completion policies.
- Prevent duplicate notifications and runaway loops.

LLM involvement:

- None during execution.
- Low during creation when translating user intent such as "only today" or "until it fires once."

LLM scope:

- Fill lifecycle fields from the user's instruction.
- Ask for clarification if the expected lifetime is ambiguous and materially affects behavior.
- Never override hard lifecycle constraints at runtime.

### `notify`

Capability:

- Send user-facing notifications, initially through Telegram.
- Include run context, trigger evidence, analysis, source references, and lifecycle outcome.
- Support deterministic templates or LLM-written concise messages.

LLM involvement:

- Optional.
- Low for deterministic alerts, such as "TSLA crossed 180."
- Medium for research summaries or complex market explanations.

LLM scope:

- Convert structured run context into a concise, useful Telegram message.
- Avoid pretending stale or advisory context is real-time truth.
- Include relevant caveats when market data, sources, or broker context are incomplete.

## Safe Versus Unsafe Shape

Safe shape:

```json
{
  "kind": "company_event_analyst",
  "execution_mode": "llm_assisted",
  "schedule": {
    "type": "recurring",
    "frequency": "weekdays",
    "time": "22:00",
    "timezone": "Europe/Rome"
  },
  "inputs": {
    "symbols": ["MSFT"],
    "event_type": "quarterly_report",
    "sections": ["revenue", "eps", "guidance", "risks"]
  },
  "llm_scope": {
    "system_prompt_id": "company_event_analyst_v1",
    "task_guidelines": "Explain whether the report changes the medium-term thesis. Focus on revenue growth, margin direction, guidance revisions, and risks.",
    "output_format": "telegram_brief"
  },
  "lifecycle": {
    "completion_policy": "keep_running"
  },
  "safety": {
    "broker_actions_allowed": false,
    "notify_only": true
  }
}
```

Unsafe shape:

```json
{
  "kind": "arbitrary_agent",
  "prompt": "Watch Tesla news all day, decide if sentiment is bad, and reduce my position by 50% if things deteriorate.",
  "tools": "all",
  "schedule": "always"
}
```

The unsafe version gives an LLM too much freedom over condition definition, tool selection, side effects, and broker-adjacent behavior. A safer version would define a typed scan, deterministic match criteria, notification-only behavior, and no direct broker execution.

## Scheduling And Lifecycle

Scheduling should be independent from process kind.

Initial schedule types:

- `one_shot`: run once at a specific date/time, then complete.
- `recurring`: run at calendar times, such as every weekday at 22:00 Europe/Rome.
- `polling`: evaluate a deterministic condition every configured interval.
- `manual`: store a reusable process template that only runs when explicitly triggered.

Lifecycle policies should be explicit.

Initial lifecycle statuses:

- `active`
- `paused`
- `completed`
- `expired`
- `archived`
- `failed`

Initial lifecycle controls:

- `complete_on_first_run`
- `complete_on_first_match`
- `keep_running`
- `complete_after_n_matches`
- `expires_at`
- `expire_after`
- `max_runs`
- `max_matches`
- `cooldown`

Example price monitor lifecycle:

```json
{
  "kind": "instrument_monitor",
  "schedule": {
    "type": "polling",
    "poll_every": "5m",
    "timezone": "Europe/Rome"
  },
  "trigger": {
    "type": "below_price",
    "symbol": "TSLA",
    "value": 180
  },
  "lifecycle": {
    "completion_policy": "complete_on_first_match",
    "expires_at": "2026-05-07T23:59:59+02:00",
    "max_matches": 1
  }
}
```

## First Useful Process Types

The first process types should cover scheduled research, deterministic polling, and conditional LLM escalation.

Recommended first slice:

- `company_event_analyst`: LLM-assisted process for company events, quarterly reports, guidance, filings, and major company news.
- `instrument_monitor`: mostly deterministic process for symbol price thresholds, percentage moves, lows/highs, or volume conditions.
- `market_regime_monitor`: hybrid process that polls broad indices or market proxies and escalates to LLM research when stress conditions match.

Next candidates:

- `trade_setup_monitor`: watches a setup, gathers context when triggered, reasons about quality, and may create a pending order proposal for explicit user approval.
- `watchlist_briefing`: recurring LLM-assisted digest for watchlist and portfolio-relevant context.
- `market_signal_capture`: recurring scan that writes durable insights into the market signals store.
- `filing_or_insider_monitor`: deterministic disclosure trigger plus LLM materiality summary.
- `portfolio_attention_monitor`: portfolio-aware monitor for unusual moves, exposure concentration, or relevant news.

## Process Adapter Examples

### `company_event_analyst`

Purpose:

- Analyze company-specific events such as quarterly reports, earnings releases, guidance, major news, SEC filings, or management commentary.

Typical execution mode:

- `llm_assisted`

Expected modules:

- `schedule`: one-shot or recurring event check.
- `trigger`: optional report/news availability check.
- `gather`: search, scrape page, SEC/filings, market data, market signals, and optionally portfolio/watchlist context.
- `analyze`: company news or market analyst prompt focused on impact.
- `notify`: LLM-written Telegram brief.
- `lifecycle`: complete on first run, keep running, or expire after event window.

Example flow:

1. User asks: "At 22:00 Europe/Rome, check Microsoft's quarterly report and tell me what changed."
2. Scheduler agent creates a `company_event_analyst` process with a one-shot schedule and task guidelines.
3. Worker sees the process is due.
4. Adapter gathers report sources, recent market data, and stored market signals for `MSFT`.
5. Analyze module calls an LLM with a dedicated company-event prompt and the gathered evidence.
6. Notification module sends a Telegram brief with revenue, EPS, guidance, risks, and thesis impact.
7. Lifecycle module marks the process completed.

LLM role:

- Interpret the report and explain trading relevance.
- Stay within the configured company/event scope.
- Avoid broker actions.

### `instrument_monitor`

Purpose:

- Monitor a symbol or instrument for deterministic market conditions.

Typical execution mode:

- `deterministic`

Expected modules:

- `schedule`: usually polling.
- `trigger`: price threshold, percentage move, monthly low, all-time low, volume spike, or other market-data condition.
- `gather`: market data only unless the trigger fires.
- `analyze`: optional and usually skipped until match.
- `notify`: deterministic or LLM-assisted wording.
- `lifecycle`: complete on first match, complete after N matches, keep running, or expire.

Example flow:

1. User asks: "Watch TSLA today and tell me if it falls below 180. Stop after it alerts once."
2. Scheduler agent creates an `instrument_monitor` with a polling schedule, below-price trigger, intraday expiry, and `complete_on_first_match`.
3. Worker polls market data every configured interval.
4. Trigger module compares latest price to 180.
5. If no match, run is recorded and the process remains active.
6. If matched, notification module sends price, threshold, timestamp, and freshness.
7. Lifecycle module marks the process completed.

LLM role:

- Low or none for execution.
- Optional for notification wording.
- Optional escalation to research only if the process spec says to explain the move after match.

### `market_regime_monitor`

Purpose:

- Monitor broad market conditions and escalate to research when a stress condition appears.

Typical execution mode:

- `llm_assisted` after deterministic trigger match.

Expected modules:

- `schedule`: polling or recurring.
- `trigger`: index drawdown, volatility proxy, breadth proxy, or major asset move.
- `gather`: market data first, then search/news only after trigger match.
- `analyze`: market analyst prompt focused on explaining regime stress.
- `notify`: LLM-written market brief.
- `lifecycle`: keep running with cooldown or complete after match.

Example flow:

1. User asks: "Today, monitor Nasdaq every 15 minutes. If it drops more than 2%, check if there is news explaining it."
2. Scheduler agent creates a `market_regime_monitor` with polling, intraday expiry, index drawdown trigger, and cooldown.
3. Worker polls Nasdaq proxy data.
4. Trigger module checks intraday drawdown.
5. If the threshold is not met, no LLM call is made.
6. If the threshold is met, gather module searches market news and retrieves relevant sources.
7. Analyze module calls the market analyst with the evidence and asks for likely drivers, uncertainty, and relevance.
8. Notify module sends a Telegram explanation.
9. Lifecycle module applies cooldown or completes the process according to policy.

LLM role:

- Explain likely market drivers after a deterministic stress condition.
- Avoid overclaiming causality.
- No broker action.

### `trade_setup_monitor`

Purpose:

- Watch for a setup, gather context when it appears, reason about quality, and optionally create a pending order proposal for explicit user approval.

Typical execution mode:

- `llm_assisted` or bounded `llm_planned`

Expected modules:

- `schedule`: polling, recurring, or one-shot.
- `trigger`: deterministic market setup condition.
- `gather`: market data, search, market signals, broker portfolio context, and risk context.
- `analyze`: trading setup evaluation.
- `act`: notify-only by default; pending order proposal only when explicitly configured.
- `lifecycle`: complete on first proposal, cooldown after notifications, or keep running.

Example flow:

1. User asks: "If NVDA pulls back 5% from today's high, analyze whether it is a buy-the-dip setup and prepare an order proposal if the risk/reward looks good."
2. Scheduler agent converts this into a `trade_setup_monitor`.
3. Validator confirms order execution is not allowed and only pending proposal creation is possible.
4. Worker monitors deterministic pullback condition.
5. On match, gather module retrieves market data, relevant news, market signals, and portfolio exposure.
6. Analyze module evaluates setup quality and risk.
7. If criteria are met and the spec allows it, act module creates a pending order proposal requiring Telegram approval.
8. Notify module sends the rationale and approval request.
9. Lifecycle module completes, pauses, or applies cooldown according to policy.

LLM role:

- Reason about setup quality and explain trade rationale.
- It may recommend or prepare a proposal only inside the configured pending-action workflow.
- It must not execute an order.

### `market_signal_capture`

Purpose:

- Periodically scan configured themes, symbols, or sectors and save durable insights into the market signal store.

Typical execution mode:

- `llm_assisted`

Expected modules:

- `schedule`: recurring.
- `gather`: search, market data, Reddit/community, filings, and existing market signals.
- `analyze`: identify durable future-impact-oriented insights.
- `act`: create compact `market_signals` rows.
- `notify`: optional summary of saved signals.
- `lifecycle`: keep running or expire after campaign end.

Example flow:

1. User asks: "Every evening, scan AI infrastructure news and save durable market signals."
2. Scheduler agent creates a recurring `market_signal_capture` process.
3. Worker gathers broad sources for configured tags/sectors.
4. Analyze module filters noisy news into concise durable insights.
5. Act module writes validated market signals.
6. Notify module optionally reports what was saved.

LLM role:

- Convert noisy evidence into compact future-impact-oriented signals.
- Use market signal creation rules.
- Avoid raw search dumps.

## Proposed Runtime Flow

Creation flow:

1. User sends a natural-language scheduling request through Telegram or another interface.
2. Main orchestrator recognizes scheduler intent.
3. Orchestrator calls a broad scheduler delegation tool with the natural-language request.
4. Scheduler agent converts the request into a typed process spec.
5. Deterministic validator checks supported kind, schedule, timezone, lifecycle, capabilities, and safety policy.
6. `ScheduledProcessService` stores the process in SQL and computes `next_run_at`.
7. Scheduler agent returns a natural-language result to the invoking agent, including next run time or validation issues.

Execution flow:

1. Scheduler worker wakes on an interval.
2. Worker loads active due processes or polling processes eligible for evaluation.
3. Process adapter gathers deterministic inputs and evaluates triggers.
4. If no trigger matches, the run is recorded and the process remains active.
5. If the process is due or a trigger matches, the adapter gathers required context.
6. If the process is LLM-assisted, the bounded sub-agent or specialist prompt analyzes the gathered context.
7. Notification text is generated deterministically or by LLM according to the spec.
8. Telegram notification is sent.
9. Run/event outcome is persisted.
10. Lifecycle policy updates process status, computes the next run, or completes/expires the process.

## Safety Boundaries

Initial scheduler workflows should be advisory and notification-oriented.

Broker execution must not be available to scheduled subprocesses by default. Order-related scheduled processes may create pending order proposals only when explicitly configured and only through the existing approval flow.

The scheduler should include:

- Typed process schemas instead of arbitrary agent prompts.
- Explicit allowed capabilities per process kind.
- Max steps, timeouts, and rate limits for LLM-assisted runs.
- Cooldowns and deduplication for notifications.
- Timezone normalization with UTC storage for `next_run_at`.
- Audit records for process creation, runs, trigger matches, notifications, failures, and lifecycle transitions.
- Clear rejection messages when a user request cannot be safely represented by a supported process spec.

## Tooling Interfaces And Agent Access

The scheduler needs multiple tooling surfaces. A single toolbox is too coarse because different LLM calls have different responsibilities and risk profiles.

### Orchestrator-facing scheduler tool

Tool:

- `scheduler_delegate`

Purpose:

- Let the main orchestrator pass a natural-language scheduling or process-management request to the scheduler agent.
- Return a clear response the orchestrator can relay to the user or use to adjust its next step.

Access:

- The main orchestrator sees this broad scheduler delegation tool.
- The main orchestrator should not receive the scheduler's internal management tools by default.

Expected behavior:

- Create, explain, list, pause, resume, archive, or reject scheduler requests.
- Ask for missing details if guessing would create an unsafe or useless process.
- Return structured failure reasons and safe alternatives.

### Scheduler-agent internal tools

Tools:

- `scheduler_create_process`
- `scheduler_validate_process`
- `scheduler_list_processes`
- `scheduler_get_process`
- `scheduler_pause_process`
- `scheduler_resume_process`
- `scheduler_archive_process`

Purpose:

- Give the scheduler agent a narrow deterministic API for process management.

Access:

- Scheduler agent only.
- Not exposed directly to market analyst, order agent, or general chat orchestration unless there is a specific admin/debug flow.

Expected behavior:

- Accept typed process specs.
- Return verbose structured validation errors when a spec is incomplete, unsupported, or unsafe.
- Never run broker side effects.

### Process-adapter service access

The worker and process adapters should call Python services directly, not LLM tools, for deterministic execution.

Allowed services are injected from `AppRuntime` according to configuration:

- `MarketDataService`
- `MarketIntelligenceService`
- `SearchService`
- scrape page service/tooling where available
- `DisclosureService`
- `CommunityResearchService`
- `MarketSignalService`
- `BrokerReadService` only for process kinds that need portfolio or position context
- `PendingActionService` and `ProposalService` only for explicitly order-adjacent process kinds
- Telegram scheduler notifier

### LLM call toolbox matrix

Different LLM calls should receive different tools:

| LLM call | Tool access | Notes |
| --- | --- | --- |
| Main orchestrator | `scheduler_delegate`, existing specialist routing tools, approval routing | No direct scheduler CRUD tools. |
| Scheduler agent | scheduler management tools only | No market data, broker execution, or broad research tools by default. |
| Company/event analysis | market/company research toolbox | Search, scrape, disclosure, market data, market signals. No order action tools. |
| Market regime analysis | market analyst toolbox | Market data, search/scrape, market signals, configured research sources. No broker action tools. |
| Instrument notification writer | no tools or notification-format-only context | Trigger was already evaluated deterministically. |
| Market signal capture analysis | research toolbox plus market signal create action through adapter | Writes signals through deterministic adapter/service validation. |
| Trade setup analysis | market research plus broker read context when configured | May produce a rationale and candidate proposal. No direct broker execution. |
| Order proposal action | pending-action/proposal service via deterministic adapter or order specialist | Creates pending approval only when process spec explicitly allows it. |

The general rule is: gather/analyze may read configured context; act may write only through explicit process actions; broker execution is not exposed to scheduled subprocesses.

## Structured Tool Errors

Scheduler tools and sub-agent-facing tools should return verbose, structured errors so the calling agent can repair the request or explain the issue.

Recommended error shape:

```json
{
  "status": "error",
  "code": "unsupported_trigger",
  "message": "The requested trigger is not supported for instrument_monitor.",
  "retryable": true,
  "missingFields": [],
  "invalidFields": ["trigger.type"],
  "capabilityGaps": [],
  "suggestedFixes": [
    "Use below_price, above_price, percent_move, intraday_drawdown, or volume_spike."
  ],
  "clarifyingQuestions": [
    "Should this alert fire once, or keep running after every match?"
  ],
  "safeAlternatives": [
    {
      "kind": "instrument_monitor",
      "trigger": {"type": "below_price"}
    }
  ],
  "details": {}
}
```

The scheduler agent should use these fields to revise its process spec before failing. If it still cannot proceed, it should return a clear user-facing explanation with the safest alternative.

Important error categories:

- `missing_required_field`
- `unsupported_process_kind`
- `unsupported_schedule`
- `unsupported_trigger`
- `capability_unavailable`
- `unsafe_action`
- `ambiguous_target`
- `invalid_timezone`
- `market_data_unavailable`
- `llm_budget_exceeded`
- `notification_unavailable`
- `order_proposal_not_allowed`

## Gather, Analyze, And Act Boundaries

### Gather access

Gather modules may read from configured services only. They should not write state except run/evidence audit records.

Allowed read context by default:

- Market data
- Search and scrape results
- SEC/disclosure data
- Reddit/community context
- Market intelligence data
- Market signal memory
- Broker portfolio/position context only when the process kind explicitly needs it

Gather output should be an evidence packet with source references, timestamps, freshness notes, and capability gaps.

### Analyze access

Analyze modules may call specialist agents or prompts with a bounded evidence packet.

Expected analyzer access:

- `company_event_analyst`: company analyst or market analyst prompt, with market/company research context.
- `market_regime_monitor`: market analyst prompt, with broad market and news context.
- `market_signal_capture`: market analyst or dedicated signal-capture prompt, with market signal creation guidance.
- `trade_setup_monitor`: market analyst for setup context and order specialist only for proposal shaping.

Analyze modules must receive:

- process ID and run ID
- original user instruction
- process spec summary
- configured task guidelines
- gathered evidence
- known capability gaps
- allowed output schema
- explicit prohibited actions

### Act access

Act modules are the only place where scheduler runs can write to other services.

Allowed actions:

- Send notification.
- Save market signal.
- Create follow-up scheduled process.
- Pause, complete, expire, or archive the current process.
- Create a pending order proposal only when explicitly allowed by the process spec.

Disallowed actions:

- Direct broker order execution.
- Direct broker cancellation.
- Expanding the process action beyond the stored spec.
- Writing market signals or proposals from raw LLM prose without deterministic validation.

## Sub-Agent Invocation Contract

When a process adapter invokes another agent, it must provide clear operating instructions. Sub-agents should not infer their authority from the general application context.

Each sub-agent invocation should include:

- `process_id`
- `run_id`
- `process_kind`
- `execution_mode`
- `invocation_reason`
- `original_user_request`
- `process_spec_summary`
- `task_guidelines`
- `allowed_tools`
- `prohibited_tools`
- `allowed_actions`
- `prohibited_actions`
- `evidence_packet`
- `source_refs`
- `data_freshness`
- `capability_gaps`
- `required_output_schema`
- `max_tool_calls`
- `max_llm_calls`
- `token_budget`
- `timeout_seconds`

Sub-agent prompts should explicitly say:

- Use only the provided evidence unless the adapter grants specific tools.
- Ask for missing required inputs or return a structured inability reason.
- Do not execute or imply broker side effects.
- For order-related work, produce rationale and proposal metadata only.
- Include uncertainty and source limitations.

## Scheduler History And Context

Scheduler subprocesses need history, but not unbounded chat history.

Recommended context layers:

- Original user request that created the process.
- Current stored process spec.
- Current run evidence packet.
- Prior run summaries for the same process.
- Last notification summary and timestamp.
- Prior trigger matches and lifecycle events.
- Relevant market signals retrieved by symbol, sector, or tags.
- Optional recent Telegram context when the process was created from a chat.

Storage approach:

- Store full process specs, run records, and event metadata in SQL.
- Store compact run summaries rather than full LLM transcripts by default.
- For repeated LLM-assisted jobs, pass a bounded process history summary into sub-agent calls.
- Preserve enough context for auditability, but rely on the GenAI context manager for prompt compaction when calls approach provider limits.

History should help sub-agents avoid repeating stale conclusions, duplicate alerts, or contradictory recommendations.

## LLM Spend And Token Guardrails

LLM-based subprocesses need explicit cost and loop controls.

Required guardrails:

- Max LLM calls per process run.
- Max tool calls per sub-agent invocation.
- Max wall-clock timeout per run.
- Max retry count, usually one retry after recoverable provider/context errors.
- Per-process cooldown after notifications or failures.
- No LLM call on deterministic no-match paths.
- Context budget checks through the GenAI context manager.
- Summary-first context compaction for long process histories.
- Structured output schemas where possible.
- Failure recorded as a run event instead of silent retry loops.

Optional later guardrails:

- Daily provider spend estimate.
- Per-process LLM budget.
- Global scheduler LLM budget.
- Priority queue when many jobs are due.

## Order Proposal And Approval Context

Order-adjacent scheduler processes need richer approval messages than a bare order summary. If an LLM spots a trading opportunity and prepares a proposal, the Telegram approval message must include the reason and evidence before the user presses Approve.

Recommended structured context:

```json
{
  "processId": "sched_...",
  "runId": "run_...",
  "setupTitle": "NVDA pullback setup",
  "triggerEvidence": {
    "condition": "5% pullback from intraday high",
    "observedValue": "-5.2%",
    "timestamp": "2026-05-07T15:42:00Z"
  },
  "order": {
    "side": "buy",
    "symbol": "NVDA",
    "quantity": 1,
    "orderType": "market"
  },
  "rationale": "The pullback condition fired after strong earnings-related momentum, but volatility is elevated.",
  "riskNotes": [
    "Market data freshness must be checked.",
    "No automatic execution occurs without Telegram approval."
  ],
  "sourceRefs": [],
  "dataFreshness": "latest quote timestamp ..."
}
```

The final Telegram approval message should be assembled deterministically from structured fields:

- process and run reference
- trigger condition and observed evidence
- proposed order details
- LLM rationale
- risk notes
- data freshness
- source references when available
- expiration time
- clear statement that Approve submits the broker action

This likely requires extending pending-action/proposal metadata beyond the current `summary_text` path so scheduler-generated proposals can preserve rationale, evidence, and source references.

## Autonomous Order Submission Policy

For scheduler v1, autonomous broker execution should be out of scope.

Allowed:

- Autonomous monitoring.
- Autonomous analysis.
- Autonomous notification.
- Autonomous market-signal creation if configured.
- Autonomous pending order proposal creation only if the process spec explicitly allows it.

Disallowed:

- Autonomous order submission.
- Autonomous order cancellation.
- Any scheduled process calling broker execution tools directly.

If true autonomous execution is ever considered later, it should require a separate explicit policy layer with user-configured limits:

- allowed accounts/environments
- allowed symbols
- maximum notional/order size
- maximum daily notional
- allowed order types
- allowed time windows
- required data freshness
- required confidence/evidence rules
- kill switch
- mandatory audit trail
- dry-run mode

That policy should be separate from the scheduler and should fail closed by default.

## Multi-Wave Integration Plan

The scheduler should be shipped in waves. Each wave should produce usable code, tests, and a clear operational boundary. The design should favor composition over inheritance: process adapters can share a small abstract base or protocol if useful, but most behavior should live in services, dataclass specs, validators, and injected runtime dependencies.

### Wave 0: Domain Contracts And Storage Foundation

Scope:

- Define the scheduler domain package, likely `src/t212ai/scheduler`.
- Add enums and dataclasses for process kind, execution mode, schedule type, lifecycle status, trigger type, action type, and notification mode.
- Add SQLAlchemy rows for scheduled processes, runs, and events.
- Add `ScheduledProcessService` for deterministic creation, validation, lookup, pause, resume, archive, due-process selection, run recording, and lifecycle transitions.
- Add schedule and lifecycle calculators that can be tested without LLMs or external services.

Design details:

- Use compact JSON text columns for typed specs in v1, similar to the market signals approach.
- Keep process identity and audit fields as first-class columns.
- Store `next_run_at` in UTC and store the configured timezone separately.
- Validate schedule, lifecycle, trigger, action, and safety policy before persistence.
- Do not implement arbitrary executable prompts.
- Prefer `Protocol` or a small `ScheduledProcessAdapter` interface over deep inheritance.

Expected outputs:

- `ScheduledProcessService`
- ORM rows such as `ScheduledProcessRow`, `ScheduledProcessRunRow`, and `ScheduledProcessEventRow`
- Domain models for process specs and run outcomes
- Unit tests for create/list/archive/pause/resume, due selection, recurrence, expiry, cooldown, and completion policies

Integrations:

- Register scheduler ORM models with the existing `Base.metadata.create_all(...)` flow.
- Reuse `DATABASE_URL` and the existing SQLAlchemy session factory.
- No Telegram, LLM, broker, or market-data dependency in this wave.

Shipping criteria:

- The service can create and manage scheduled process definitions from Python tests.
- A process can move through lifecycle states deterministically.
- No background worker is required yet.

### Wave 1: Runtime Wiring And Worker Skeleton

Scope:

- Wire the scheduler service into `AppRuntime`.
- Add a `scheduled_processes` capability binding based on database availability.
- Add one-shot and loop runner functions for the scheduler worker.
- Add CLI commands similar to reconciliation, for example `brokerai run scheduler-once` and `brokerai run scheduler --poll-every 1m`.

Design details:

- The worker should not execute LLM workflows yet.
- The worker should load due processes, select the matching adapter, record a run, and handle unsupported adapters safely.
- The worker should be idempotent enough for local use and avoid duplicate execution within a single polling cycle.
- Failures should be recorded as run events, not just printed.

Expected outputs:

- `SchedulerWorker` or equivalent runner function
- CLI commands and preflight checks
- Runtime capability display in doctor/config output
- Tests for runtime wiring and CLI invocation

Integrations:

- `AppRuntime`
- Existing logging configuration
- Existing `parse_duration_to_seconds`
- Existing database service stack

Shipping criteria:

- A local worker can start, find due processes, record skipped/unsupported runs, and exit cleanly for one-shot mode.
- This wave proves the operational loop before real process adapters are added.

### Wave 2: Notification And Management Surface

Scope:

- Add deterministic scheduler management tools for create/list/pause/resume/archive where direct typed input is available.
- Add outbound notification infrastructure for scheduler worker notifications.
- Add Telegram notification support for configured allowed chat targets.

Design details:

- The worker cannot rely on Telegram update context, so outbound Telegram notification needs a small service that can create a bot client from settings and send to configured chat IDs.
- Notifications should be persisted before and after send attempts, including failure metadata.
- Management tools should be narrow and deterministic; natural-language delegation comes in a later wave.
- Archive should never delete process records.

Expected outputs:

- `SchedulerNotificationService`
- `TelegramSchedulerNotifier` or equivalent adapter
- Scheduler management service methods and optional admin/debug tools
- Tests for notification formatting, send-failure recording, and management operations

Integrations:

- Existing Telegram settings, bot token, and allowed chat ID configuration
- Existing `TelegramMessenger` formatting behavior where reusable
- Existing capability/preflight reporting

Shipping criteria:

- A scheduler run can create a notification event and send a basic Telegram message without being triggered by an inbound Telegram update.
- Processes can be stopped or archived safely.

### Wave 3: First Deterministic Adapter, `instrument_monitor`

Scope:

- Implement the first real process adapter for deterministic market-data conditions.
- Support price above/below, percentage move, and simple intraday expiry.
- Optionally support low/high conditions only if the configured market-data service can provide the required historical range reliably.

Design details:

- Trigger evaluation must be deterministic.
- Use configured market data services from `AppRuntime`, not direct provider construction inside the adapter.
- If market data is unavailable, record a skipped/failed run with a clear reason.
- LLM use is optional and limited to notification wording, not trigger evaluation.
- Lifecycle should support `complete_on_first_match`, `keep_running`, `expires_at`, `max_matches`, and cooldown.

Expected outputs:

- `InstrumentMonitorAdapter`
- Trigger evaluator for market-data conditions
- Compact deterministic notification template
- Tests for match/no-match, stale or missing data, lifecycle completion, expiry, and cooldown

Integrations:

- `MarketDataService`
- Scheduler worker adapter registry
- Scheduler notification service
- Runtime capability registry

Shipping criteria:

- User can create a typed `instrument_monitor` process and receive a Telegram alert when the condition matches.
- No LLM is required for the first successful end-to-end alert.

### Wave 4: Scheduler Agent And Natural-Language Delegation

Scope:

- Add a scheduler specialist agent or bounded scheduler delegate.
- Expose one broad orchestrator-facing tool, for example `scheduler_delegate(request: str, context: dict | None = None)`.
- Let the scheduler agent translate natural language into supported process specs and management actions.
- Add high-quality tool descriptions and prompt guidance.

Design details:

- The main orchestrator should not receive the full internal scheduler toolbox by default.
- The scheduler agent can use narrow internal tools such as create/list/pause/resume/archive, but the higher-level interface remains a natural-language delegation tool.
- The scheduler agent must explain unsupported requests and suggest safe alternatives.
- The scheduler agent must ask for missing required details when guessing would create a bad or unsafe process.
- Context manager guardrails already added in the GenAI client should apply to scheduler-agent calls.

Expected outputs:

- Scheduler agent prompt/profile
- `scheduler_delegate` tool definition and handler
- Internal scheduler tool mapping
- Orchestrator integration
- Tests for create, reject, list, pause/archive, ambiguous input handling, and tool availability based on capability

Integrations:

- Main orchestrator
- GenAI client and context manager
- `ScheduledProcessService`
- Runtime capability registry
- Existing agent/toolbox infrastructure

Shipping criteria:

- From Telegram, the user can ask in natural language to create or stop an instrument monitor.
- The invoking orchestrator receives a clear scheduler-agent response it can return to the user.

### Wave 5: LLM-Assisted Research Adapter, `company_event_analyst`

Scope:

- Implement the first LLM-assisted process adapter.
- Support one-shot or recurring company event research, with a focus on quarterly reports, earnings, guidance, filings, and major company news.

Design details:

- Data gathering should use configured services from `AppRuntime`: search, scrape page, SEC/disclosure, market data, market signals, and optionally broker portfolio context.
- The adapter should gather evidence deterministically first, then call an LLM with a dedicated scope.
- LLM guidelines should be stored in the process spec as `llm_scope.task_guidelines`.
- Dedicated system prompt IDs can be introduced as stable named prompt profiles.
- Output should be structured before being rendered into Telegram text.

Expected outputs:

- `CompanyEventAnalystAdapter`
- Company-event prompt/profile
- Evidence packet builder
- LLM analysis output schema
- Tests with fake gatherers and fake LLM responses

Integrations:

- Existing search service
- Scrape page tool/service if available
- SEC/disclosure service when configured
- Market data service
- Market signal service
- Market analyst or dedicated company-event analyst prompt
- Scheduler notification service

Shipping criteria:

- User can schedule a company-event analysis and receive a concise Telegram brief at the scheduled time.
- Missing optional services degrade gracefully with explicit caveats.

Implementation notes:

- Implemented as `CompanyEventAnalystAdapter`, registered under `company_event_analyst`.
- Scheduler-agent creation is private through `scheduler_company_event_analyst_create`; the main orchestrator only delegates to the scheduler agent.
- Runtime registry passes configured company/market agents and optional evidence services into the adapter.
- Output is normalized through a reusable structured synthesis helper and the `CompanyEventAnalysis` schema.
- The process is notify-only; broker/order actions remain unavailable for this wave.

### Wave 6: Conditional LLM Escalation, `market_regime_monitor`

Scope:

- Add a hybrid process where deterministic market stress triggers LLM-based explanation.
- Support broad index or proxy monitoring with polling schedules and cooldowns.

Design details:

- Do not call the LLM unless the deterministic trigger matches.
- Start with simple drawdown or percentage-move triggers.
- Gather market news only after trigger match.
- Use the market analyst agent or a dedicated regime prompt with clear uncertainty requirements.

Expected outputs:

- `MarketRegimeMonitorAdapter`
- Index/proxy trigger evaluator
- Conditional gather and analysis flow
- Tests for no-trigger no-LLM behavior, trigger escalation, cooldown, and notification

Integrations:

- Market data service
- Search/scrape services
- Market analyst agent
- Scheduler notification service

Shipping criteria:

- User can ask the system to monitor broad market stress for a day and receive an LLM-written explanation only if the condition is met.

Implementation notes:

- Implemented as `MarketRegimeMonitorAdapter`, registered under `market_regime_monitor`.
- V1 monitors one proxy symbol per process and supports OR-style `percent_change_below` and `drawdown_from_high_pct` stress conditions.
- Scheduler-agent creation is private through `scheduler_market_regime_monitor_create`; the main orchestrator still only delegates to the scheduler agent.
- Broad labels map to ETF proxies: market/S&P -> SPY, Nasdaq -> QQQ, Dow -> DIA, Russell/small caps -> IWM.
- Vague stress requests default to SPY, `percent_change_below=-3`, `drawdown_from_high_pct=5`, 1mo/1d lookback, and end-of-day expiry.
- The adapter does not call search or the LLM on no-match runs; matched runs call the market analyst and synthesize `MarketRegimeAnalysis`.
- The process is notify-only; broker/order actions remain unavailable for this wave.

### Wave 7: Market Signal Capture And Memory Integration

Scope:

- Add recurring or polling scans that can save durable insights into the market signal store.
- Use this as the first scheduler process that writes to another memory service.
- Expose creation only through the private scheduler agent toolbox.

Design details:

- `MarketSignalCaptureAdapter` gathers compact research evidence from search, community, or disclosure services, with market data as optional context only.
- The process is `kind=market_signal_capture`, `execution_mode=llm_assisted`, notify-only, and `safety.brokerActionsAllowed=false`.
- The adapter writes compact market signals only when the market analyst identifies durable future-impact-oriented insights.
- Avoid raw search dumps, noisy restatements, arbitrary prompts, broker actions, and order proposals.
- Require at least one scan scope field: `query`, `symbols`, `sectors`, or `tags`.
- Require at least one usable research evidence source before calling the LLM; market data alone cannot drive capture.
- Use structured output with at most three proposed signals per run.
- Before writing, suppress near-duplicates by normalized title, overlapping source refs, or overlapping topical fields plus identical normalized summary prefix.
- Write through `MarketSignalService` using `source=scheduled_job`, existing validation, and advisory-only semantics.
- Notify only when at least one new signal is saved and notifications are enabled.

Expected outputs:

- `MarketSignalCaptureAdapter`
- `MarketSignalCaptureAnalysis` and `CapturedMarketSignal` structured schemas
- Private scheduler tool `scheduler_market_signal_capture_create`
- Capability `scheduler_market_signal_capture`
- Evidence-to-signal analysis guidance
- Safe write path to `MarketSignalService`
- Tests for signal creation, duplicate/noisy result handling, and advisory-only behavior

Integrations:

- Search/scrape services
- Market data service
- Reddit/community service if configured
- SEC/disclosure service if configured
- `MarketSignalService`
- Scheduler agent private toolbox
- Scheduler worker adapter registry
- Doctor/capability display

Shipping criteria:

- A recurring or polling scan can save validated, non-duplicate market signals and optionally notify the user of saved insights.
- The scheduler agent asks for clarification when scan scope or schedule is missing.
- Captured signals remain advisory context only; fresh market data and broker state still come from authoritative tools.

### Wave 8: Trade Setup Monitor With Pending Proposals

Scope:

- Add an advanced process that watches deterministic setup conditions and may create pending order proposals for explicit approval.
- This wave should come after notification, lifecycle, scheduler-agent delegation, and at least one LLM-assisted adapter are stable.

Design details:

- Broker execution remains unavailable to the scheduler.
- The only order-adjacent action is creating a pending proposal through existing guarded services.
- The process spec must explicitly allow proposal creation.
- The adapter should include position/portfolio context and risk context when available.
- The LLM may reason about setup quality, but deterministic services create and enforce pending-action state.

Expected outputs:

- `TradeSetupMonitorAdapter`
- Setup trigger evaluator
- Proposal creation action through existing pending action/proposal services
- Telegram approval notification integration
- Tests for no-proposal default, explicit proposal creation, approval flow compatibility, and safety rejection

Integrations:

- Market data service
- Broker read service
- Pending action service
- Proposal service
- Market signal service
- Order specialist or order-planning prompt
- Telegram approval flow

Shipping criteria:

- User can configure a setup monitor that creates a pending order proposal only after a deterministic trigger and LLM-assisted rationale, with explicit Telegram approval still required.

### Wave 9: Hardening, Operations, And Process Catalog

Scope:

- Stabilize the scheduler for long-running local use.
- Add process catalog documentation and operational commands.
- Add richer cleanup and observability.

Design details:

- Add stale-run recovery if a worker dies mid-run.
- Add run locking if concurrent workers become possible.
- Add process export/import or doctor display if useful.
- Add cleanup commands for archived/old run records.
- Add rate limits and provider spend controls for LLM-assisted adapters.

Expected outputs:

- Operational docs
- CLI management commands
- Doctor report improvements
- Cleanup/maintenance services
- Regression tests for concurrency and recovery where feasible

Integrations:

- Existing CLI and doctor
- Logging and tracing metadata
- Database maintenance patterns

Shipping criteria:

- Scheduler can run locally for extended periods with understandable logs, predictable costs, and recoverable state.

## Implementation Direction

The scheduler should extend the existing runtime pattern:

- Add SQL-backed scheduler models and `ScheduledProcessService`.
- Register scheduler schema with the existing database creation flow.
- Wire scheduler capability/service into `AppRuntime`.
- Add scheduler worker commands similar to the reconciliation worker.
- Add a scheduler delegation tool to the main orchestrator.
- Reuse existing market data, search, market signal, specialist agent, and Telegram layers where possible.

The first implementation should not try to solve every process type. It should establish the service, schema, lifecycle, worker, notification path, and one deterministic adapter well enough that later process types are modular additions.
