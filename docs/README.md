# Documentation Index

Status: source map for repo documentation.

The docs are organized by operating concern so design notes, current-state
references, source API material, and active planning do not live in one flat
folder.

## Architecture

- [Architecture status](./architecture/ARCHITECTURE_STATUS.md): current runtime
  state and implemented capabilities.
- [Architecture diagrams](./architecture/ARCHITECTURE_DIAGRAMS.md): Mermaid
  diagrams for runtime, routing, scheduler, and approval flows.
- [Repository structure](./architecture/REPO_STRUCTURE.md): source tree and
  module ownership.
- [Agent design](./architecture/AGENT_DESIGN.md): broader Telegram agent design
  reference.

## Agents

- [Agentic flow](./agents/AGENTIC_FLOW.md): source of truth for
  reason-plan-execute-judge-return.
- [Agent interpolation map](./agents/AGENT_INTERPOLATION.md): how agents invoke
  and wrap one another.
- [Agentic logic](./agents/AGENTIC_LOGIC.md): product-facing agent behavior
  principles.
- [Agent patterns](./agents/AGENT_PATTERNS.md): selected reusable agentic
  patterns.

## Scheduler

- [Scheduler process catalog](./scheduler/SCHEDULER_PROCESS_CATALOG.md):
  currently supported process kinds and operator commands.
- [Scheduler design notes](./scheduler/SCHEDULER_DESIGN_NOTES.md): deeper
  design history and implementation notes.

## Data And Research

- [Data source strategy](./data/DATA_SOURCES.md): provider roles and authority
  boundaries.
- [News and web search](./data/NEWS_AND_WEBSEARCH.md): research/source hierarchy
  and execution boundaries.

## API Reference

- [Trading 212 API notes](./api/T212ApiDocs.md): markdown reference generated
  from the Trading 212 public API material.
- [Trading 212 OpenAPI JSON](./api/api.json): source API schema snapshot.

## Operations

- [Development guidelines](./operations/DEV_GUIDELINES.md): engineering rules,
  tracing, logging, and high-level interface decisions.

## Planning

- [Feature direction](./planning/FEATURES.md): product capability direction.
- [Historical plan](./planning/PLAN.md): early roadmap context, retained as
  history.
- [Todo](./planning/TODO.md): active implementation queue.
