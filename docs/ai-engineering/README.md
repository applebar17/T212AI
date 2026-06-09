# AI Engineering Principles

## Purpose

These principles guide how AI features should be designed and implemented in My Digital Brain. The project should stay agentic and dynamic, but graph writes, source handling, privacy, and tool execution must remain structured and guarded.

The goal is not to make every flow deterministic. The goal is to use model reasoning where it is valuable, while keeping enough structure around it to make the system reliable, debuggable, and safe.

## Core Principles

### 1. Structure Unstructured Input Explicitly

Information is extracted from unstructured text, transcripts, media-derived text, and chat history through structurization processes.

When asking a model to extract information, the request should include the expected structured output contract, preferably as a Pydantic object or equivalent schema. The model should produce structured proposals, not direct database mutations.

LLM-facing extraction contracts must be semantic draft contracts. The model
extracts meaning, local candidate refs, graph aliases, evidence text/spans, and
property suggestions. Backend code deterministically enriches those drafts into
records with source IDs, generated IDs, evidence refs, status fields, timestamps,
metadata, and persistence-ready provenance.

Rules:

- Use `*Draft` schemas for provider structured outputs.
- Use enriched backend records for validation, resolution, write plans, storage,
  and audit.
- Do not ask the model to echo `source_id`, generated IDs, raw UUIDs,
  `EvidenceRef`, `source_refs`, or backend metadata.
- Let the model use only scoped local refs such as `CANDIDATE_PERSON_001` and
  provided graph aliases such as `NODE_000001`.
- Represent arbitrary metadata as typed property suggestions in model-facing
  schemas; backend decides whether they become typed fields or metadata.

Ingestion uses two freedom tiers:

- High-freedom semantic planning: the planner organizes the source narrative
  into ordered semantic actions, goals, evidence spans, dependencies,
  ambiguity/context gaps, and clarification needs. It must not choose graph
  labels, relationship types, write-plan operations, persistence fields, or
  backend-owned IDs.
- Low-freedom backend-facing extraction: focused extractors return enum-bound
  candidate drafts using only ontology values and refs/aliases supplied in the
  current step. Backend code compiles semantic actions into these constrained
  calls, injects deterministic IDs/provenance, validates refs and ontology
  values, and owns graph writes.

The ingestion reasoning refinement adds a stricter baseline for memory-writing
work:

- Whole-source hybrid graph retrieval builds compact context before reasoning.
- A structured reasoning checkpoint interprets entities, aliases,
  relationships, user/owner involvement, salience, ambiguity, and storage
  cautions before planning.
- Entity planning and relationship planning are separate model steps.
- Entity candidates are prepared and validated before relationship planning.
- Relationship planning receives a resolved entity map and must not invent
  unresolved endpoints.
- Durable writes happen only after backend validation and write-plan assembly.

The model may use local refs only when the process goal requires orchestration
between objects. A ref-consuming extraction step may use only refs created by
earlier steps or graph aliases explicitly provided by the backend.

The backend must guarantee executable ordering. In the refined ingestion
baseline, relationship planning starts only after entity validation has produced
a resolved entity map. If a relationship step discovers that a required endpoint
is missing, it must emit `missing_entity_required` and loop back through
supplemental entity handling before any relationship candidate is accepted.

Reasoning checkpoints are allowed before important downstream steps when the
process needs richer context interpretation. A reasoning checkpoint receives
purpose-specific guidelines, usable history, compact graph context, and caller
input, then returns structured context augmentations. It may recommend
clarifications, node-versus-metadata handling, owner/user interpretation,
profile/perception/relationship treatment, context gaps, and guardrails. It does
not own graph mutation, write-plan construction, validation, or ontology
compilation.

Reasoning outputs should be structured decision notes and interpretations, not
hidden chain-of-thought. Their purpose is to reduce later ambiguity, such as
clarifying that `Merc` is an alias for Matteo Mercoldi instead of a separate
person.

Reasoning and planning should both be treated as reusable LLM-backed
information transforms. The baseline package shape is:

```text
general system prompt template
  + dedicated purpose/guidelines
  + dedicated context information
  + usable history when relevant
  + optional prior compact tool outputs
  + selected model route
  + dedicated structured output model
  -> structured artifact
```

The existing reasoning checkpoint already follows this shape through purpose
guidelines, caller input context, optional conversation and graph context, prior
tool outputs, model routing, and caller-selected output schemas. Planning should
mirror the same pattern: a generalized planning primitive should convert a
goal, context, reasoning artifact, and constraints into ordered process actions.
It should not extract candidates, validate candidates, resolve duplicates, build
write plans, or mutate storage.

If a state needs a structured artifact as its final useful result, that artifact
should be the state's validated structured output, not a fake "submit" tool
used only to smuggle the schema back to the backend. Tools may still be used
inside the state for support actions such as context expansion or contradiction
review. After the structured output is returned, backend code deterministically
routes the next process step from that schema.

Examples:

- Candidate entities.
- Candidate relationships.
- Candidate claims.
- Candidate metadata patches.
- Candidate clarification questions.
- Candidate tool calls.

### 2. Schemas And Tool Descriptions Are Prompt Surface

Pydantic field descriptions, JSON schema descriptions, tool names, tool descriptions, enum values, and parameter descriptions are part of the prompt.

They must be:

- Clear.
- Unambiguous.
- Domain-specific.
- Short enough to avoid noise.
- Explicit about constraints and expected behavior.

Bad schema descriptions can confuse the model as much as bad prompt text.

### 3. Prefer Modular Model Calls Over Heavy Requests

Large overloaded prompts increase hallucination risk and make failures harder to debug.

Prefer modular steps when useful:

- Whole-source hybrid context retrieval.
- Compact context packaging.
- Structured reasoning checkpoints.
- Entity planning.
- Entity extraction.
- Entity resolution support.
- Relationship planning.
- Relationship extraction.
- Contradiction detection.
- Answer generation.
- Tool selection.

Contradiction handling should prefer a specialized judge call when there is meaningful doubt. The memory-writing agent should not rely on brittle deterministic contradiction rules; it should inspect retrieved graph context and invoke the judge when it can explain the suspected conflict.

Modularity should reduce cognitive load for the model, but it should not add unnecessary latency or cost for trivial tasks.

For ingestion, complexity is decided after lightweight context retrieval. Raw text alone is not enough to know whether a memory is simple or ambiguous. The expected sequence is:

1. Whole-source hybrid graph retrieval for wave-1 ingestion context.
2. Compact Graph Context Pack construction.
3. Structured reasoning checkpoint.
4. Entity-only planning.
5. Entity candidate preparation.
6. Deterministic entity validation and duplicate handling.
7. Relationship-only planning from the resolved entity map.
8. Relationship candidate preparation.
9. Deterministic relationship validation.
10. Backend write-plan assembly and execution.

Generated natural-language graph query fan-out may be explored later. It is not
required for the wave-1 ingestion refinement baseline.

### 4. Use AI Dynamically Where It Adds Value

LLM-based systems should not be designed like purely deterministic software. A good agent can use context, tools, and reasoning to handle cases that would otherwise require many brittle branches.

For each problem, decide whether it is better solved by:

- Deterministic code.
- A constrained model call.
- An agent with tools.
- A hybrid approach.

The tradeoff is cost, latency, reliability, and implementation complexity. If a deterministic solution is simple and reliable, use it. If the problem is contextual, ambiguous, or language-heavy, use the model.

### 5. Context Building Is Fundamental

Every model step needs the right context for the job. Context should be intentionally built, not dumped.

Context may include:

- Current user message.
- Relevant interaction history.
- Pending ingestion state.
- Retrieved graph entities.
- Source evidence.
- User profile memory.
- Privacy and trust constraints.
- Tool results.
- Previous extraction candidates.
- Nearby graph context for proposed writes.
- Current state plus relevant history when checking for contradiction risk.

The context builder should ask: what information does this model call need to do this job well, and what information would distract or bias it?

For memory-writing calls, context should include enough nearby graph state for the agent to notice possible contradictions: similar entities, current facts, historical states, related sources, relationship contexts, perceptions, time context, and place context. This context enables agentic suspicion before a contradiction judge is invoked.

For the wave-1 ingestion refinement, the first graph context strategy is
whole-source hybrid retrieval. The resulting context must be compacted before it
is injected into reasoning, so later model steps receive useful aliases,
relationships, duplicate hints, and memory summaries instead of noisy graph
payloads.

### 6. Tooling Enables Dynamic Processes

Actions, intent handling, and process management can be dynamic when the AI Manager has well-defined tools and proper context.

The model can infer which tool or pipeline is appropriate, but tools must have clear contracts.

The LLM chooses actions and proposes parameters. Backend services validate parameters and execute state changes. Tools are command surfaces, not authority surfaces.

The default `conversation_entry` tool surface should stay small:

- `start_memory_ingestion`
- `query_memory_context`
- `propose_memory_correction`

Default answering is a non-tool path. Resume, pause, cancel, expire,
clarification handling, validation, and write execution are not broad
conversation-entry tools. Resume, pause, and cancel are state-specific tools for
`pending_process_review`, where compact pending context exists and the model can
infer the user's intent naturally.

Good tools should:

- Have narrow responsibilities.
- Use clear input schemas.
- Return structured outputs.
- Be auditable when they change state.
- Fail explicitly.
- Avoid hidden side effects.

### 7. Define Agent Behavior Before Plugging Tools

In agentic development, define the behavioral protocol of the agent before adding many tools.

The protocol should clarify:

- What the agent is responsible for.
- What it must never do.
- When it should ask the user.
- When it should call tools.
- Which tool calls require confirmation.
- How it handles uncertainty.
- How it recovers from invalid tool output.

Tools should then be added to support that behavior, not to let the agent improvise without boundaries.

For contradiction handling, the behavioral protocol is:

- Memory-writing agents may raise a contradiction doubt when retrieved context conflicts with a proposed write.
- The doubt must include a short explanation grounded in provided context.
- A contradiction judge tool reviews the doubt and may inspect more graph context through read-only tools.
- The judge returns a structured decision and recommended action.
- The judge does not mutate the graph directly.

For correction, maintenance, contradiction, and profile-memory flows, risky model
outputs are proposals or review results, not authority to mutate persistent
state. The backend must convert approved proposals into validated graph service
calls, and confirmation-aware contexts must make the required user approval
explicit.

### 8. Guardrails Protect Against Bad Loops

Agentic flows need deterministic guardrails to prevent unstable behavior.

Guardrails may include:

- Max tool-call iterations.
- Allowed tool sets per task.
- Required structured output validation.
- Confirmation before risky graph writes.
- Privacy checks before provider calls.
- Expiration for pending processes.
- Retry limits.
- Fallback behavior.
- Read-only tool scopes for judge investigation.
- Mandatory structured outputs for judge decisions.

The agent can be dynamic inside the guardrails. The guardrails prevent runaway loops, accidental writes, and confusing user experiences.

### 9. Manage Context Size Deliberately

Token budget is a product and engineering constraint.

The system should:

- Keep full usable conversation history available to top-level conversational
  states, including user messages, assistant messages, tool calls, and tool
  outputs.
- Summarize or compact older history when the message sequence becomes too long.
- Retrieve only relevant graph/source evidence.
- Avoid stuffing entire histories into prompts.
- Preserve durable facts in graph/profile memory instead of relying on chat history.
- Track which summaries are model-generated and when they were generated.

Summaries should preserve decisions, unresolved questions, entity references, and important user preferences.

### 10. Propagate History Down, Compact Tool Traces Up

Agentic history should preserve continuity without polluting later states with
noisy internal tool details.

When an agentic state calls a tool or subprocess, the callee receives the parent
history plus the tool-call context it needs. As the execution moves deeper,
internal steps may append tool calls, tool outputs, diagnostics, and intermediate
results to the local trace.

When control returns to the caller, the caller's future model-facing history
should receive one compact tool output summary, not the full internal trace.

Rules:

- Moving deeper: pass the relevant parent history and append local tool status as
  needed.
- Moving upward: compact internal activity into a concise tool output result.
- Persist full internal traces for audit, debugging, and replay when useful.
- Local UAT trace reports may render prompts, inputs, outputs, candidates, and
  missing-entity handling for human review; they are diagnostic artifacts, not
  model-facing history or production API contracts.
- Do not expose noisy nested tool chatter to future top-level prompts unless a
  state explicitly needs it.
- Tool output summaries must preserve the achieved result, unresolved questions,
  important errors, created/updated refs, and recommended next action.

This gives the model enough state to reason while avoiding history bloat and
hallucination pressure from irrelevant implementation details.

### 11. Pass Minimum Sufficient Context Per State

Every LLM-related state or procedure should receive the minimum collectable
context required to achieve its purpose.

This does not mean "little context." It means complete context for the task and
aggressive filtering of noise.

Each state configuration should define:

- Required context.
- Optional context.
- Forbidden or noisy context.
- History policy.
- Tool-trace policy.
- Prompt guidelines.
- Tool-call or structured-output contract.

For example, the ingestion reasoning checkpoint needs the user source text,
usable conversation history when relevant, the compact Graph Context Pack,
current time/timezone, and a pending clarification answer when resuming. It
should not receive raw database records, unrelated metadata blobs, or internal
transport details.

### 12. Separate Pending Summaries From Resumable Snapshots

Pending processes have two context layers:

- Model-facing summaries explain what is waiting in compact terms:
  `process_id`, `kind`, `status`, `question`, `compact_summary`, and
  `unresolved_targets`.
- Backend-only snapshots preserve resumable state: source refs, ingestion ids,
  resume step, checkpoint schema version, pending question, and
  process-specific snapshot refs.

The model should never receive the raw backend snapshot. It should choose
between resume, pause, cancel, a new memory, a query, a correction, or normal
chat from the compact summary plus current conversation history.

Resume does not pass a `user_reply` tool argument. The current user message and
recent history are already part of runtime context and must be used from there.
Before any resumed memory write, the backend must refresh graph context and rerun
validation/resolution so stale checkpoints do not duplicate memories created by
another process.

Structured clarification is a user-interaction contract, not a graph mutation.
Allowed states may call `request_user_clarification` with a small packet of
questions, candidate answers, and free-text allowance. The chat UI renders that
packet as a question box. When the user submits answers, the backend validates
the selected options, stores a user-visible answer summary, and resumes the
originating process from a compact clarification-answer summary. Model-facing
history should receive the answer summary, not raw widget state or backend-only
snapshots.

### 13. Keep Channel Metadata Backend-Owned By Default

Channel and session metadata should be modeled, stored, and available to backend
runtime code, but it should not be passed directly to the LLM by default.

The agent should receive only a minimal projection when the metadata changes its
behavior.

Potentially useful projections:

- Current time and timezone.
- Modality: text, voice transcript, image-derived text, or other source type.
- Transcript uncertainty when voice or media was involved.
- Rendering constraints such as short Telegram-style response versus richer web
  chat response.
- Source or attachment references when relevant.

Usually noisy or forbidden:

- Raw chat IDs.
- Webhook payloads.
- HTTP headers.
- Internal session identifiers.
- Transport-specific debug fields.

The backend can keep a `ChannelSessionMetadata` object for routing, auditing,
storage, and UI behavior. The context builder decides whether any projected
field belongs in a model prompt.

### 14. Route Tasks To Appropriate Models

Model choice should depend on task difficulty.

Use cheaper, faster models for:

- Simple classification.
- Format conversion.
- Basic extraction.
- Short summarization.
- Tool argument drafting with low risk.

Use stronger models for:

- Ambiguous entity resolution.
- Complex memory extraction.
- Contradiction reasoning.
- Multi-step planning.
- Sensitive or high-impact graph updates.
- Final answers requiring careful synthesis.

The AI Manager should eventually support model routing by task type, expected difficulty, privacy level, latency budget, and cost budget.

### 15. Prompt Guardrails Should Be Restrictive But Natural

Prompts should restrict hallucination and unsafe behavior without making the model rigid or unnatural.

Good guardrails:

- Tell the model what it can and cannot infer.
- Require uncertainty to be represented explicitly.
- Require evidence references when available.
- Forbid direct graph mutation outside tools.
- Encourage clarification when needed.
- Allow graceful "unknown" answers.

Overly rigid prompts can make the agent brittle. Under-specified prompts invite hallucination.

### 16. Simplify IDs In Model Context

Long opaque database IDs are bad prompt material. They increase token usage, are hard for humans to inspect, and are easy for models to copy incorrectly.

When passing graph context to a model, the context builder should map internal persistent IDs to short temporary aliases.

Example:

```text
Internal UUID 8f1f7c3a-... becomes NODE_000001.
Internal UUID 17dc7a91-... becomes CLAIM_000001.
Internal UUID 72ad38f4-... becomes SOURCE_000001.
```

The model should use the aliases in structured outputs and tool arguments. The backend must resolve aliases back to internal IDs before validation and execution.

Rules:

- Aliases are scoped to a single model context or process step.
- Aliases are not canonical IDs.
- Alias maps should be explicit in the context.
- Failed alias resolution should fail validation.
- The model should never invent aliases that were not provided.

### 17. Build Low-Noise Context Packages

LLM context should be prepared as a task-specific package, not as a raw dump of
database records.

The context package should provide the information needed to answer, reason, or
choose tools, while excluding noisy metadata that can lower answer quality or
encourage hallucination.

Prefer including:

- Display names and short descriptions.
- Current facts.
- Relevant history.
- Temporal summaries.
- Relationship context.
- Affective summaries and original user words.
- Source evidence summaries.
- Contradiction or merge notes when relevant.
- LLM-facing aliases.

Avoid including:

- Raw UUIDs when aliases are available.
- Large metadata blobs.
- Internal storage fields.
- Full unrelated relationship lists.
- Debug data unless the task is debugging.

The question is not "what can we fit in the prompt?" The question is "what does
the model need to produce the best grounded output for this task?"

### 18. Tool Errors Must Guide The Model

Tool errors are part of the agent loop. The LLM will see them, so they should be
verbose enough to redirect the model toward a valid next action.

Good tool errors should explain:

- What failed.
- Which field or constraint caused the failure.
- Which values were accepted when useful.
- Whether the model should retry, ask the user, or stop.
- How to adjust the tool call.

Bad tool errors are vague messages such as `invalid input`, `bad request`, or
`failed`.

Example:

```text
Invalid relationship type: FRIEND.
Use one of: KNOWS, RELATED_TO, HAS_RELATIONSHIP_CONTEXT.
If the relationship has emotional or temporal history, create a RelationshipContext instead.
```

Verbose errors are not only for humans. They are a control surface for agentic
behavior.

### 19. Embeddings Are Backend-Derived Retrieval Artifacts

Vector embeddings are not memory truth and they are not model-authored memory
summaries by default.

For Graph-RAG, Neo4j remains authoritative. Backend code builds deterministic,
typed embedding documents from stored graph records, then Chroma stores semantic
lookup vectors that point back to Neo4j targets.

Rules:

- Embed low-noise informative text, not raw graph payloads.
- Do not embed raw UUIDs, metadata blobs, provider traces, prompts, logs, or
  tool-call payloads.
- Prefer typed builders per graph label over generic property dumps.
- Store exactly one primary graph target per vector record and optional related
  targets for multi-node memories.
- Use `builder_version` plus `document_checksum` to decide whether an embedding
  is stale.
- If vectorization fails after a successful graph write, preserve the graph
  write and record vectorization diagnostics. Do not make Chroma availability the
  authority for whether a memory was stored.
- Answer generation must hydrate graph targets from Neo4j after vector search.
  Chroma hits alone are never enough grounding for user-visible answers.
- Semantic search must ignore orphan Chroma hits that do not have a matching
  relational vector record. Vector hits become usable only after backend
  hydration through the operational vector record and Neo4j.
- Retrieval responses should expose frontend/LLM-safe summaries, context
  packages, and debug traces, not raw graph records or raw Chroma payloads.
- Chat memory queries should use hybrid retrieval when available, then hydrate
  and answer from `GraphContextPackage`. The final user-visible response is
  graph-grounded; retrieval hits and traces are support metadata for tooling,
  debugging, and UI exploration.
- Exact/property search remains useful as a fallback and as an explicit graph
  workspace mode, but it should not be confused with semantic memory retrieval.

## Practical Development Rules

- Treat schemas, tools, and prompts as one design surface.
- Keep model outputs structured when they affect memory state.
- Let the AI Manager be dynamic, but keep graph writes validated.
- Prefer context engineering over larger prompts.
- Build low-noise context packages for LLM answer generation and tool use.
- Build low-noise embedding documents for semantic retrieval; do not embed raw
  graph records or model/tool traces.
- Hydrate and rank vector hits through backend services before using them in
  prompts or UI responses.
- Prefer a small strong toolbox over many vague tools.
- Add deterministic code where it is clearly cheaper, faster, and more reliable.
- Add model calls where language, ambiguity, or contextual judgment matters.
- Use short LLM-facing aliases instead of raw database IDs in prompts and tool schemas.
- Make tool errors actionable enough for the model to repair invalid calls.
- Record model inputs, outputs, prompt versions, schema versions, and tool calls when they affect persistent memory.

## Design Checklist For New AI Features

Before implementing a new AI behavior, answer:

- What is the agent trying to achieve?
- Which model is appropriate for the task difficulty?
- What structured output is expected?
- Which context is necessary?
- Which context should be excluded?
- Which internal IDs need LLM-facing aliases?
- What context package shape should be sent to the model?
- Which tools are available?
- What tool errors should guide invalid or unsafe calls?
- What are the deterministic guardrails?
- What happens if the model is uncertain?
- What happens if validation fails?
- What state changes must be auditable?
- What privacy or provider constraints apply?

## Relationship To The MVP

For the MVP, these principles imply:

- Use Pydantic objects for extraction and tool contracts.
- Keep the AI Manager responsible for dynamic conversation and process control.
- Keep the Network API responsible for structured graph operations.
- Use cloud AI services initially, with provider boundaries documented.
- Support voice transcription as a first-class ingestion path.
- Use LLM-facing ID aliases for graph context and tool calls.
- Keep pending ingestion state compact, expiring, and split between
  model-facing summaries and backend-only resumable snapshots.
- Add richer deterministic handling only when real usage shows the need.
