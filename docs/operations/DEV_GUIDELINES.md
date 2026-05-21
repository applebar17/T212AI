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
- add trace metadata for routing, model choice, approval state, provider, and tool category

### Core Tracing Contract

Rules:
- add exactly one root `@traceable(..., run_type="chain")` span on each
  request or job entrypoint so all child runs nest under a single trace
- use the shared helpers in `t212ai.genai.tracing`; do not re-implement tracing
  utilities elsewhere
- construct OpenAI/Azure clients through `wrap_openai(...)` when tracing is
  enabled, and do not also wrap the same raw LLM provider call with
  `run_type="llm"`; avoid duplicate LLM spans
- do not add custom `process_inputs` or `process_outputs` functions unless the
  user explicitly approves that specific case; tracing must rely on the
  LangSmith SDK default capture plus lightweight metadata
- for chat sessions, attach `session_id` and any request identifiers with
  `set_trace_metadata(...)` on the root span
- every LLM-related step, method, or function must be traced with a name,
  `run_type`, and metadata that match the logic behind the step
- keep run names stable and operational, for example `order_agent.reason`,
  `order_agent.plan`, `order_agent.execute.<action_id>`, and
  `order_agent.return`

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

If remote traces are missing, first verify that `LANGSMITH_TRACING=true` is set
in the runtime environment. `@traceable` will not upload runs when tracing is
disabled.

### Repo Rule

Always import tracing helpers from `t212ai.genai.tracing`, not directly from `langsmith`.

Reason:
- `traceable` is the original LangSmith SDK decorator, re-exported without a
  custom wrapper
- it centralizes tiny metadata/name helpers
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

`run_type` must be one of:
- `tool`
- `chain`
- `llm`
- `retriever`
- `embedding`
- `prompt`
- `parser`

Use these conventions:
- `run_type="chain"`: request/job roots, orchestration, specialist agent steps,
  reason/plan/execute/return spans, critique, and workflow coordination
- `run_type="prompt"`: message/prompt construction and chat parameter assembly
- `run_type="tool"`: LLM-callable tool entrypoints and external action tools
- `run_type="parser"`: structured parsing, schema conversion, and structured
  response handling
- `run_type="embedding"`: embedding generation
- `run_type="retriever"`: retrieval/RAG flows
- `run_type="llm"`: direct raw model calls only when they are not already traced
  through `wrap_openai(...)`

### Input And Output Policy

Do not add repo-local input/output processing functions by default.

Current tracing policy:
- rely on LangSmith SDK default input/output capture
- add small metadata with `set_trace_metadata(...)` for operational filtering
- keep the traced method boundaries meaningful, so raw captured inputs/outputs
  are interpretable without additional processors
- if a payload is too large or sensitive, fix the method boundary or payload
  shape before adding custom processors

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

## Prompt Context Budget

Scope:
- agents
- prompts
- tools

Rules:
- build configurable reasoner and planner prompts from contextual, high-level
  information only
- reasoner/planner prompts should describe available capabilities by tool name
  and short purpose, not full JSON parameter schemas
- full tool schemas belong in the execution step where tools are attached to
  the model and exact arguments are required
- agent-specific guidelines should explain decision logic and ordering
  constraints, not duplicate every tool field or provider implementation detail
- examples should be few, targeted, and reusable across similar agents
- when adding prompt content, prefer a compact rule that changes behavior over a
  verbose description that merely repeats the tool schema

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
