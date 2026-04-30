# Agentic Flow

Status: source of truth for the target agent execution model.

## Purpose

This document defines how agents in T212AI should reason, plan, execute, judge,
and return results. It is the reference for fixing the current agentic gaps and
for designing future specialist agents without turning each one into a bespoke
workflow.

The core rule is:

```text
reason -> plan -> execute -> judge -> return
```

Each step is configurable. A simple deterministic workflow may use only execute
and return. A complex advisory agent should normally use the full loop. A
state-changing flow must separate proposal/preparation from button approval and
final execution.

## Invocation Contract

An agent invocation should receive:

- recent chat history
- the latest user request
- an invocation reason from the orchestrator
- an optional structured intent from the orchestrator
- persistent guidance or user preferences when available
- the agent profile: purpose, guidelines, risk posture, and output contract
- descriptions of available tools, without necessarily attaching tools yet

The orchestrator may classify intent before delegation, but that classification
is a hint, not a hard dependency. The specialist agent must still be able to
reason over the user request and history.

## Step 1: Reason

The reason step builds task context before tools are available.

Inputs:

- chat history
- latest user request
- invocation reason
- optional orchestrator intent
- agent profile and persistent guidance
- available toolbox descriptions

Tools:

- none

Output:

- structured reasoning context
- task interpretation
- known facts
- assumptions
- ambiguities
- required evidence
- safety constraints

The reason step must not expose hidden chain-of-thought. Its output should be a
structured, auditable context packet that later steps can consume.

## Step 2: Plan

The plan step turns the reasoning context into an executable strategy.

Inputs:

- all reason-step inputs
- structured reasoning context
- available toolbox descriptions

Tools:

- none

Output:

- structured plan
- ordered action list
- action dependencies
- parallelization flags for independent steps
- required inputs
- missing inputs
- assumptions
- risks
- approval requirements
- expected final output shape

Plan actions should be explicit enough for the execution step to follow action
by action. Independent fetches, such as market snapshot plus news search, can be
marked as parallelizable. Dependent steps must declare their dependencies.

## Step 3: Execute

The execute step performs the plan with the agent's configured toolbox.

Inputs:

- chat history
- user request
- invocation reason
- optional intent
- reasoning context
- structured plan
- previous action outputs
- agent-specific toolbox

Tools:

- the narrow toolbox configured for this agent, flow, or process

Behavior:

- execute plan actions sequentially by default
- run actions in parallel only when the plan explicitly marks them independent
- pass previous action outputs into later actions
- keep tool outputs structured and traceable
- stop or ask a focused clarification when execution would otherwise guess
  dangerously

Execution must respect tool boundaries. Market analysis tools do not become
broker-state authority. Broker execution tools must not be called merely because
the user typed an approval-like phrase.

### Broker-State Dependent Values

Agent execution must resolve broker-state dependent values before calling a
state-changing broker preparation tool.

Example:

```text
User: prepare a market buy for COIN using half the available cash
```

Correct flow:

- reason that the order size depends on broker cash
- plan a broker portfolio/cash read before order preparation
- execute the cash read
- calculate half of the available cash from the tool output
- call the order preparation tool with a concrete decimal `notional_amount`
- if the user also asks for a protective stop/stop-limit after the buy, model it
  as a dependent action that requires the buy result, executed quantity, and a
  resolved reference price before preparing the sell-side protection

Incorrect flow:

- pass `"half available cash"`, `"50%"`, or another unresolved phrase/formula as
  `notional_amount`
- add deterministic natural-language parsing rules in application code for
  specific phrases such as "half", "all", or "quarter"

The model should be guided by typed structured fields and field descriptions.
Application code may validate that a tool argument is coherent, but it should not
replace the agent's reasoning with phrase-specific sizing logic.

## Step 4: Judge

The judge step reviews the draft result and execution trace.

Inputs:

- original request
- chat history
- invocation reason
- optional intent
- reasoning context
- plan
- tool outputs
- draft result

Tools:

- normally none
- optionally read-only verification tools for a configured verification flow

Output:

- structured critique
- pass/fail or confidence
- missing context
- grounding issues
- safety issues
- unclear approval requirements
- source-provenance concerns
- suggested repair if needed

The judge should be configurable in the same way across agents. It should not be
a one-off final check embedded inside a specialist.

## Step 5: Return

The return step packages the accepted result for the caller.

Inputs:

- execution output
- judge output
- relevant plan and trace metadata

Output:

- concise user-facing summary
- structured metadata for the orchestrator
- artifacts for Telegram, proposals, or downstream workflows
- approval payloads only when a side effect has been prepared
- caveats and next steps

The return step should preserve important facts from execution and judging
without dumping raw tool noise into Telegram.

## Approval Rule

Natural language can request, discuss, revise, or cancel the preparation of a
side effect. It must not approve or reject a pending side effect.

Approvals and rejections for pending broker actions are deterministic and
button-only:

```text
pa:approve:<action_id>
pa:reject:<action_id>
```

Typed text such as `yes`, `no`, `proceed`, `approve`, or `reject` goes through
the normal LLM/message path. It does not resolve a pending action.

## Configurable Agent Components

The target architecture should have reusable configurable components:

- Reasoner Agent: produces structured reasoning context from history, invocation
  reason, intent hints, guidance, and toolbox descriptions.
- Planner Agent: produces structured plans from reasoning context and toolbox
  descriptions.
- Executor: executes the plan with the selected toolbox, action by action.
- Judge Agent: reviews the result for completeness, grounding, safety, and
  clarity.
- Returner or response packager: turns the accepted result into a concise
  response and structured artifacts.

The Reasoner Agent and Planner Agent should be organized in the same spirit as
the current `AgentJudge`: reusable, configurable, and scalable across different
specialist agents. They should not be hardcoded inside each specialist.

## Current Implementation Status

### Orchestrator

Current status:

- `MainOrchestratorAgent` holds the user-facing conversation.
- It can answer directly or delegate to specialist tools.
- Delegation passes the current `AgentRequest`, chat history, and
  `orchestrator_guidance`.
- It can pass a structured intent to the specialist through the delegation
  request.

Gap:

- It does not yet package a formal invocation reason object.
- It does not coordinate a full reason-plan-execute-judge-return specialist loop.
- It does not run a shared judge over all specialist responses as a standard
  pipeline step.

### Base Specialist Agent

Current status:

- `BaseAgent.handle()` resolves intent and complexity.
- It calls `plan()`.
- It calls `execute()`.
- If `execute()` returns nothing, it returns a plan summary.

Gap:

- There is no separate reason step before planning.
- Planning is always coupled to `AgentReasoner.build_plan()`.
- Execution is not a generic plan-action runner.
- Judging is not part of the default specialist lifecycle.
- Return packaging is mostly ad hoc in each specialist response.

### AgentReasoner

Current status:

- `AgentReasoner` can build a structured plan.
- It can run a critique.
- It can run a tool-enabled chat completion through `orchestrate_with_tools()`.
- `ConfigurableReasonerAgent` now exists as the reusable no-tool reason step.
- `ConfigurablePlannerAgent` now exists as the reusable no-tool grouped planner.

Gap:

- The legacy `AgentReasoner` is still a mixed service/helper for existing flows.
- Live specialists do not yet use `ConfigurableReasonerAgent` by default.
- Live specialists do not yet use `ConfigurablePlannerAgent` by default.
- It mixes several responsibilities: planning, critique, and tool-enabled
  orchestration.
- The configurable reasoner/planner components are not yet wired into a full
  specialist loop.

### AgentJudge

Current status:

- `AgentJudge` exists as a reusable wrapper around critique.
- It has a clean interface: `review(request, response, guidelines=None)`.
- This is the right pattern for future shared components.

Gap:

- It is optional and not wired into the default specialist loop.
- It does not receive full execution traces or tool-output packages yet.

### Planner Schema

Current status:

- `AgentPlan` exists.
- `ToolStep` includes tool name, purpose, input summary, dependencies, risk
  class, and `can_run_parallel`.
- `GroupedAgentPlan` now exists for future execution-oriented plans.
- `PlanActionGroup` models sequential groups with parallel or sequential
  sub-actions.
- `PlanAction` includes stable action IDs, dependencies, expected output,
  output keys, risk class, and retry/stop policy fields.

Gap:

- Tool steps are not yet used by a generic executor.
- Grouped plan actions are not yet used by a generic executor.
- Parallelization is represented in the grouped schema, but not executed by a
  runtime.

### Portfolio Analyst

Current status:

- Uses the base `plan -> execute` pattern.
- Has deterministic portfolio-summary workflow support.

Gap:

- Attention scans do not yet run a full configurable LLM/tool loop.
- No dedicated reason step or judge step.
- Portfolio-specific return packaging is workflow-specific.

### Order Agent

Current status:

- Handles pending-order review workflow.
- Handles trade proposal / place order / cancel order preparation.
- Requires deterministic Telegram button approval for state-changing actions.
- Uses structured translation into broker action requests for order preparation.

Gap:

- The critical order flow is still custom inside `OrderAgent.execute()`.
- It does not use a shared reasoner/planner/executor pipeline.
- It does not run a standard judge before returning approval proposals.
- Some execution logic is deterministic and should remain so, but it should plug
  into the common loop as a configured execute step.

### Market Analyst

Current status:

- Has a configured market toolbox.
- Uses the configurable reasoner and grouped planner when the runtime provides
  those components and a non-empty market toolbox.
- Uses `GroupedPlanExecutor` to run planned market actions through the existing
  GenAI tool loop.
- Has guidance to proceed with reasonable defaults for broad scans instead of
  asking broker execution-risk questions.

Gap:

- It does not yet run the judge step as part of the default market-analysis
  loop.
- Company, portfolio attention, and order flows have not yet migrated to the
  shared grouped executor.

### Company Analyst

Current status:

- Has a profile and toolbox summary.
- It currently relies mostly on base planning behavior.

Gap:

- No dedicated company-analysis execution loop.
- No reason step, generic plan execution, or judge step.
- Needs a configurable research/tool flow for ticker resolution, market context,
  disclosures, news, and synthesis.

### Calculator Agent

Current status:

- Uses a deterministic structured request builder and deterministic calculator
  tools.
- This is appropriate for calculations.

Gap:

- It does not need the full loop for simple arithmetic.
- More complex finance calculations could still use reason/plan when there are
  multiple dependent calculations or ambiguous inputs.

## Required Architecture Work

The next agentic work should focus on these issues:

1. Wire `AgentJudge` into the configurable loop, with access to plan and
   execution traces.
2. Add loop configuration per specialist:
   - enabled steps
   - prompts per step
   - toolbox per execution step
   - judge policy
   - return contract
3. Migrate the remaining specialists incrementally:
   - Company Analyst next, because research flows benefit from planned
     evidence gathering.
   - Portfolio attention scan after company analysis.
   - Order Agent carefully, preserving deterministic approval and broker safety.

## Design Principles

- Tools attach at execution time, not reasoning or planning time.
- Tool descriptions are available to reason and plan steps.
- Side-effect tools require deterministic policy gates.
- Approval is button-only.
- Deterministic workflows can be plugged into the loop without becoming LLM
  tool calls.
- Agent-specific prompts should be step-specific: reason prompt, plan prompt,
  execute prompt, judge prompt, return prompt.
- Specialist responses should return the whole planning-execution package to the
  orchestrator through structured metadata and artifacts, while keeping
  user-facing text concise.
- Execution context should pass compact assistant summaries between actions, not
  raw tool transcripts or full provider payloads.
- The system should favor reusable loop components over bespoke specialist
  logic.
