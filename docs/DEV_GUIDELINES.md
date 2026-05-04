# Development Guidelines

This document is the canonical place for repo-level engineering guidelines.

Use it for rules that should stay consistent across features, agents, tools, and infrastructure. New guidelines should be added as peer sections in this file instead of creating many small single-topic docs unless a topic becomes large enough to justify its own deep-dive reference.

## How To Extend This Document

When adding a new guideline:
- keep it operational and repo-specific
- state what is required, not just what is preferred
- note the scope: agents, tools, infrastructure, tests, or docs
- include examples only when they clarify an implementation rule

## LangSmith Tracing And Observability

This project uses LangSmith tracing for execution-level observability across agent orchestration, planning, LLM calls, and tool execution.

The baseline follows LangSmith manual instrumentation guidance:
- prefer `@traceable` for application-level instrumentation
- use precise `run_type` values so LangSmith renders runs correctly
- keep traces compact and safe by summarizing inputs/outputs instead of logging full raw payloads
- add trace metadata for routing, model choice, approval state, provider, and tool category

Official references:
- Custom instrumentation: https://docs.langchain.com/langsmith/annotate-code
- Observability concepts: https://docs.langchain.com/langsmith/observability-concepts
- Distributed tracing: https://docs.langchain.com/langsmith/distributed-tracing

### Environment

Tracing is opt-in at runtime.

Required environment variables:
- `LANGSMITH_TRACING=true`
- `LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com`
- `LANGSMITH_API_KEY=...`

Recommended:
- `LANGSMITH_PROJECT=T212AI`

By design, our local tracing wrapper fails open. If LangSmith is not installed or tracing is disabled, the application still runs.

### Repo Rule

Always import tracing helpers from `t212ai.genai.tracing`, not directly from `langsmith`.

Reason:
- it keeps LangSmith optional
- it centralizes sanitization and summary logic
- it gives one place to evolve tracing behavior without touching all call sites

Use:

```python
from t212ai.genai.tracing import traceable, set_trace_metadata, set_trace_name
```

### What To Trace

Trace public execution boundaries, not every helper.

Trace these by default:
- agent entrypoints: orchestrator, specialist agent `handle`, judge `review`
- planning/reasoning boundaries: `build_plan`, `critique`
- public tool functions exposed to the LLM
- provider-level LLM calls and tool execution in `GenAIClient`

Usually do not trace:
- tiny pure helpers
- formatting-only functions
- high-frequency utility methods that add noise without diagnostic value
- anything that would log hidden reasoning or excessive raw payloads

### Run Types

Use these conventions:
- `run_type="chain"`: orchestrator steps, specialist agent steps, planning, critique
- `run_type="tool"`: LLM-callable tool entrypoints
- `run_type="llm"`: raw model calls
- `run_type="parser"`: structured parsing / schema conversion
- `run_type="embedding"`: embedding generation

Reserve `run_type="retriever"` for future retrieval/RAG flows so LangSmith can render retrieval traces properly.

### Input And Output Policy

Do not rely on default argument capture for agent and tool code. Use `process_inputs` and `process_outputs` to summarize payloads.

Current tracing policy:
- user requests: log length, sanitized preview, trigger type, chat id, history counts
- history: log counts and roles, not full conversation dumps
- plans: log counts for required context, risks, missing inputs, tool steps, and approval requirement
- agent responses: log selected agent, answer length, plan/critique presence
- tool runs: log sanitized arguments, status, output preview, error code, and top-level data keys

Never log:
- API keys, secrets, auth headers
- hidden reasoning or internal scratchpad text
- full broker/account dumps when a summary is sufficient

### Metadata Policy

Use `set_trace_metadata(...)` to enrich runs with lightweight routing context.

Typical metadata:
- `agent_name`
- `agent_kind`
- `intent_kind`
- `task_complexity`
- `route`
- `provider`
- `tool_name`
- `state_changing`

Use `set_trace_name(...)` when the runtime name should reflect the concrete agent or flow step, for example `OrderAgent.handle`.

### Agent Rules

Agent tracing should show:
- the inbound request summary
- the selected complexity/model tier
- the routed specialist when orchestration happens
- the structured plan shape
- optional critique outcome

Agent traces must not expose hidden reasoning. The plan and critique models are the observable artifacts.

## Orchestrator Model

Scope:
- agents
- prompts
- tools
- docs

Rules:
- treat `MainOrchestratorAgent` as an LLM-based conversation manager, not as a deterministic router
- the orchestrator must be able to answer directly, ask clarifying questions, or call specialist-routing tools
- specialist delegation should happen through an explicit toolbox plus tool:function mapping so the LLM sees the routing sequence and tool returns inside the same conversation
- when the orchestrator delegates, it should pass explicit specialist guidance about task focus and expected output rather than hiding delegation intent in ad hoc control flow
- deterministic logic should remain at sensitive execution boundaries such as broker actions, approvals, and calculator execution, even when orchestration is LLM-driven
- chat history and scoped persistent guidance should be available to both the orchestrator and delegated specialists unless a specific flow intentionally disables them

Current baseline:
- the orchestrator uses specialist-routing tools for portfolio, order, market, company, guideline-memory, and calculator delegation
- specialist outputs are returned to the orchestrator, which then decides whether to answer the user directly or continue with further tool calls
- specialist planning remains structured and auditable even when the top-level orchestration path is tool-driven

## Specialist Execution Packages

Scope:
- agents
- prompts
- tools
- docs

Rules:
- specialist flows that use reason/plan/execute should return the whole compact planning-execution package to the orchestrator through `AgentResponse.metadata` and `AgentResponse.artifacts`
- keep `final_answer` concise and user-facing; put reasoning context summaries, grouped plans, action summaries, execution traces, and final synthesis in artifacts
- pass compact assistant summaries between planned actions instead of raw tool transcripts or full provider payloads
- raw provider/tool details should stay summarized to status, tool names, top-level data keys, errors, and short previews unless a debugging path explicitly needs more
- deterministic execution boundaries such as broker actions, approvals, and calculator execution must keep their existing safety gates even when later migrated into the common loop

## LLM-Actionable Tool Results

Scope:
- tools
- agents
- prompts
- docs

Rules:
- LLM-facing tools must return verbose-enough `ToolResult.output` text for both success and error paths so the model can decide whether to retry, stop, or ask for clarification
- error results should include a machine-readable `ToolError.code`, a concrete `ToolError.hint`, and compact structured `details` when those details can guide the next tool call
- do not rely only on exception text for recoverable validation failures; translate provider/domain failures into deterministic codes and actionable hints
- avoid raw payload dumps; include only the fields the LLM needs to repair the next call, such as candidate broker-native tickers, required parameters, accepted enum values, or provider readiness context
- broker order tools must explicitly state whether an order was prepared, whether approval was created, and what corrected input is needed when validation fails before approval
- instrument-resolution failures should surface candidate broker-native tickers when available and must tell the agent not to guess when the result is ambiguous

## Telegram Error Diagnostics

Scope:
- agents
- telegram
- tools
- docs

Rules:
- Telegram-visible failures must be developer-useful, not just end-user-friendly
- when a request fails inside an agent or tool path, prefer returning a structured explanation with:
  - the human summary
  - the machine error code when available
  - a short hint for the next correction step
  - compact diagnostic details such as provider, operation, status code, or error type when those help debugging
- keep Telegram diagnostics compact enough to read in chat, but rich enough that a developer can understand where the failure happened without opening logs immediately
- never include secrets, auth headers, raw API keys, or full unredacted provider payloads in Telegram-visible error text
- for deterministic approval and broker flows, prefer errors that explain:
  - whether the failure happened during extraction, validation, position resolution, approval, or provider execution
  - which broker/provider was involved
  - what the user can retry with more explicitly

Implementation guidance:
- prefer rendering `ToolError` into multi-line Telegram-safe plain text instead of dropping to a single sentence
- preserve `code`, `hint`, and selected `details` fields when they materially improve diagnosis
- include the exception type in Telegram bridge safety-net errors
- for liquidation / close-position requests, error messages should explicitly say whether the runtime failed to:
  - identify the target position
  - resolve the live tradable quantity
  - load the broker portfolio snapshot

## No Legacy Interface Logic By Default

Scope:
- telegram
- agents
- high-level application interfaces
- tools
- docs

Rules:
- when a high-level interaction contract changes, remove the deprecated logic in
  favor of the new approach instead of keeping silent compatibility branches
- this is especially strict for Telegram, orchestration, approval, broker-facing,
  and other user-visible or state-changing interfaces
- do not keep word-based or heuristic fallbacks after the product decision has
  moved to a deterministic or structured flow
- do not leave "just in case" branches that preserve old behavior unless the
  user explicitly approves keeping them
- update tests and docs to assert the new contract, not the deprecated behavior
- remove old user-facing copy that advertises deprecated paths

If a deprecated path seems valuable to keep, stop and ask the user whether to
keep it or delete it. State the tradeoff plainly. The user decides.

Current example:
- Telegram pending-action approval is button-only. Text such as `yes`, `no`,
  `proceed`, `approve`, or `reject` must route through the normal
  natural-language/agent path and must not resolve a pending action.

### Tool Rules

Every public LLM tool should be decorated.

For tools:
- keep the decorator at the public entrypoint, not inside lower-level helpers
- mark all broker execution tools as `state_changing=True` in trace metadata
- return verbose `ToolResult` objects for the model, but keep trace output summarized

### Distributed Tracing

If we later split work across services, propagate LangSmith headers with `get_trace_parent_headers()` and continue the trace on the downstream service. This is the preferred baseline for cross-service agent flows.

### Current Baseline Coverage

Current tracing coverage includes:
- `GenAIClient` LLM/tool execution boundaries
- `MainOrchestratorAgent`
- specialist `BaseAgent` flow
- `AgentReasoner`
- `AgentJudge`
- Trading 212 public tools
- Alpha Vantage intelligence tools
- Yahoo public tools

If you add a new agent or tool and it changes execution flow, add tracing in the same PR.

## Capability-First Tool Surfaces

Scope:
- agents
- tools
- runtime
- docs

Rules:
- new agent-facing tools and toolboxes must be capability-first rather than provider-branded
- runtime code must use toolbox builders for live tool exposure instead of static provider/toolbox constants
- generic broker and market-data facades are the preferred live agent surfaces
- provider-specific tools belong in provider packages and should only be exposed to agents when the specialization is intentional and explicit
- top-level compatibility re-exports may exist, but they should not be treated as the primary recommended surface in docs or new runtime code
