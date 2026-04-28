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
- `LANGSMITH_API_KEY=...`

Recommended:
- `LANGSMITH_PROJECT=t212ai-dev`

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
