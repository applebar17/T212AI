# Agent Interpolation Map

Status: current architecture overview for how agents invoke, wrap, and reuse one another.

This document is a visual map of the agent graph. It focuses on invocation
paths: who can call whom, through which boundary, and which flows pass through
the orchestrator versus app-managed processes such as the scheduler worker.

## Mental Model

```text
Telegram request
  -> chat history window
  -> main_orchestrator
  -> optional specialist delegation tool
  -> specialist-local flow
  -> final response
  -> chat history append

Scheduler worker tick
  -> due scheduled process
  -> scheduler adapter
  -> optional specialist agent call
  -> notification
  -> chat history append
```

The main rule is that normal user-facing agent work enters through
`main_orchestrator`. Scheduled processes are different: they are app-owned
workers that may call selected specialists directly because there is no new user
message to route.

## Runtime Agent Graph

```mermaid
flowchart TD
    RT[AppRuntime] --> GENAI[GenAIClient]
    GENAI --> AR[AgentReasoner]
    GENAI --> CR[ConfigurableReasonerAgent]
    GENAI --> CP[ConfigurablePlannerAgent]
    GENAI --> GPE[GroupedPlanExecutor]
    AR --> J[AgentJudge]

    RT --> ORCH[main_orchestrator]
    RT --> SPEC[SpecialistAgents registry]

    SPEC --> PORT[portfolio_analyst]
    SPEC --> ORDER[order_agent]
    SPEC --> MARKET[market_analyst]
    SPEC --> COMPANY[company_analyst]
    SPEC --> MEMORY[guideline_memory_agent]
    SPEC --> CALC[calculator_agent]
    SPEC -. if scheduler DB configured .-> SCHED[scheduler_agent]
    SPEC -. if LOG_DIAGNOSTIC_AGENT_ENABLED .-> LOGS[log_diagnostic_agent]

    ORCH --> SPEC

    ORDER --> CR
    ORDER --> CP
    ORDER --> GPE
    MARKET --> CR
    MARKET --> CP
    MARKET --> GPE

    PORT --> AR
    COMPANY --> AR
    MEMORY --> AR
    CALC --> AR
    SCHED --> AR
    LOGS --> AR

    classDef root fill:#e8f1ff,stroke:#2b5fab,color:#123;
    classDef specialist fill:#e9f7ef,stroke:#2d6a4f,color:#123;
    classDef shared fill:#fff5d6,stroke:#9a6b00,color:#123;
    classDef optional fill:#f4e8ff,stroke:#7b3fb2,color:#123;

    class RT,ORCH root;
    class PORT,ORDER,MARKET,COMPANY,MEMORY,CALC specialist;
    class GENAI,AR,CR,CP,GPE,J shared;
    class SCHED,LOGS optional;
```

Important distinction:

- `main_orchestrator`, `portfolio_analyst`, `order_agent`, `market_analyst`,
  `company_analyst`, `guideline_memory_agent`, `calculator_agent`,
  `scheduler_agent`, and `log_diagnostic_agent` are callable agents.
- `AgentReasoner`, `ConfigurableReasonerAgent`, `ConfigurablePlannerAgent`,
  `GroupedPlanExecutor`, and `AgentJudge` are shared agentic components. They
  are not normally delegated to by the orchestrator; specialists use them inside
  their own execution loops.

## Normal Telegram Request Flow

```mermaid
sequenceDiagram
    participant User
    participant TG as TelegramUpdateRouter
    participant HIST as ChatHistoryManager
    participant ORCH as main_orchestrator
    participant LLM as AgentReasoner + GenAIClient
    participant SPEC as Specialist Agent
    participant TOOL as Specialist Toolbox

    User->>TG: message
    TG->>HIST: get_context_window(chat_id)
    TG->>ORCH: AgentRequest(user_message, history, metadata)
    ORCH->>LLM: orchestrate_with_tools(orchestrator_routing)

    alt direct answer
        LLM-->>ORCH: assistant text
    else specialist delegation
        LLM->>ORCH: tool call delegate_to_*
        ORCH->>SPEC: handle(delegated AgentRequest, intent hint)
        SPEC->>LLM: plan / reason / execute depending on specialist
        SPEC->>TOOL: optional tool calls
        TOOL-->>SPEC: ToolResult
        SPEC-->>ORCH: AgentResponse
        ORCH-->>LLM: delegation tool result
        LLM-->>ORCH: final synthesis
    end

    ORCH-->>TG: AgentResponse.final_answer
    TG->>HIST: record user + assistant messages
    TG-->>User: Telegram response
```

The orchestrator sees delegation as tool calls. Each delegation tool receives:

- `task_brief`
- `expected_output`
- `intent_kind`
- `entities`

The specialist receives the same current `AgentRequest`, plus
`orchestrator_guidance` derived from the delegation payload.

## Orchestrator Delegation Surface

```mermaid
flowchart LR
    ORCH[main_orchestrator] -->|delegate_to_portfolio_analyst| PORT[portfolio_analyst]
    ORCH -->|delegate_to_order_agent| ORDER[order_agent]
    ORCH -->|delegate_to_market_analyst| MARKET[market_analyst]
    ORCH -->|delegate_to_company_analyst| COMPANY[company_analyst]
    ORCH -->|delegate_to_guideline_memory_agent| MEMORY[guideline_memory_agent]
    ORCH -->|delegate_to_calculator_agent| CALC[calculator_agent]
    ORCH -. delegate_to_scheduler_agent .-> SCHED[scheduler_agent]
    ORCH -. delegate_to_log_diagnostic_agent .-> LOGS[log_diagnostic_agent]

    PORT --- PI[portfolio_summary<br/>portfolio_attention_scan<br/>rebalance]
    ORDER --- OI[place_order<br/>cancel_order<br/>review_pending_orders<br/>propose_trade]
    MARKET --- MI[unknown / market-domain work]
    COMPANY --- CI[analyze_instrument]
    MEMORY --- GI[manage_guidelines]
    CALC --- CA[calculate]
    SCHED --- SI[manage_scheduled_processes]
    LOGS --- LI[debug_logs]
```

Optional delegation tools only exist when the matching specialist exists:

- `delegate_to_scheduler_agent` requires a configured scheduled process service.
- `delegate_to_log_diagnostic_agent` requires
  `LOG_DIAGNOSTIC_AGENT_ENABLED=true` and a readable app log path.

## Invocation Matrix

| Caller | Invoked target | Boundary | Current purpose |
| --- | --- | --- | --- |
| `TelegramUpdateRouter` | `main_orchestrator` | Python method call with `AgentRequest` | User-facing request handling |
| `main_orchestrator` | specialists | LLM tool calls named `delegate_to_*` | Dynamic routing and final answer synthesis |
| `order_agent` | `ConfigurableReasonerAgent` | Python method call | No-tool broker-order reasoning context |
| `order_agent` | `ConfigurablePlannerAgent` | Python method call | Grouped broker-order action plan |
| `order_agent` | `GroupedPlanExecutor` | Python method call | Execute planned actions with broker toolbox |
| `market_analyst` | `ConfigurableReasonerAgent` | Python method call | No-tool market-analysis reasoning context |
| `market_analyst` | `ConfigurablePlannerAgent` | Python method call | Grouped market action plan |
| `market_analyst` | `GroupedPlanExecutor` | Python method call | Execute planned actions with market toolbox |
| `scheduler_agent` | scheduler management tools | LLM tool calls | Create/list/pause/resume/archive scheduled processes |
| `log_diagnostic_agent` | diagnostic log tools | LLM tool calls with cap | Read-only operational log investigation |
| `SchedulerWorker` | scheduler adapters | Python adapter registry | Run due scheduled processes |
| scheduler adapters | `market_analyst` / `company_analyst` | Direct specialist `handle()` call | Scheduled LLM-assisted analysis |
| `SchedulerNotificationService` | chat history journal | Python method call | Store scheduler outbound messages as assistant history |

## Specialist Internal Loops

### Base Specialist Loop

Most simple specialists inherit the base flow.

```mermaid
flowchart TD
    A[BaseAgent.handle] --> B[resolve intent and complexity]
    B --> C[AgentReasoner.build_plan]
    C --> D[agent.execute]
    D -->|handled| E[AgentResponse with workflow artifacts]
    D -->|not handled| F[plan-summary response]

    C -. no tools attached .-> LLM1[structured plan LLM call]
```

Used by:

- `portfolio_analyst` for portfolio summary workflow planning and execution
- `company_analyst` currently mostly as planning/profile response
- `guideline_memory_agent` with guideline-specific behavior
- fallback paths for specialists without a richer configured loop

### Configurable Agentic Loop

`market_analyst` and supported `order_agent` flows use the richer loop when the
runtime provides the shared components and the specialist has a toolbox.

```mermaid
flowchart TD
    REQ[AgentRequest + history + orchestrator guidance] --> INV[AgentInvocationContext]
    INV --> R[ConfigurableReasonerAgent.reason]
    R -->|can_proceed=false| Q[Return concise clarification]
    R -->|can_proceed=true| P[ConfigurablePlannerAgent.plan]
    P --> E[GroupedPlanExecutor.execute]
    E --> A1[Plan action LLM call]
    A1 --> T[Specialist toolbox]
    T --> A1
    A1 --> A2[Compact action summary]
    A2 --> N{more action groups?}
    N -->|yes| A1
    N -->|no| S[Final synthesis / return]
    S --> RESP[AgentResponse]
```

Execution semantics:

- Reasoning and planning receive toolbox descriptions, but no tools.
- Execution attaches the specialist toolbox.
- Action groups run sequentially.
- Actions inside a parallel group may use parallel tool calls only for read-only,
  non-broker actions.
- Broker/state-changing work remains sequential and approval-gated.

### Tool-Orchestration Loop

Some specialists use direct tool-enabled orchestration rather than the grouped
reason/plan/execute loop.

```mermaid
flowchart TD
    A[Specialist handle] --> B[AgentReasoner.orchestrate_with_tools]
    B --> C[GenAIClient.call_openai with toolbox]
    C --> D{LLM tool call?}
    D -->|yes| E[execute tool]
    E --> C
    D -->|no| F[assistant final answer]
```

Used by:

- `scheduler_agent` with private scheduler tools
- `log_diagnostic_agent` with read-only diagnostic log tools
- `market_analyst` fallback when the configurable loop is unavailable

## Scheduler Interpolation

The scheduler has two different roles:

1. `scheduler_agent` is a chat-invoked specialist that creates or manages
   scheduled process definitions.
2. `SchedulerWorker` is an app/runtime worker that periodically claims due jobs
   from the database and runs adapters.

```mermaid
sequenceDiagram
    participant User
    participant ORCH as main_orchestrator
    participant SA as scheduler_agent
    participant DB as ScheduledProcessService
    participant WORKER as Embedded SchedulerWorker
    participant ADAPT as Scheduler Adapter
    participant MA as market_analyst
    participant CA as company_analyst
    participant NOTIF as SchedulerNotificationService
    participant HIST as ChatHistoryJournal

    User->>ORCH: schedule a process
    ORCH->>SA: delegate_to_scheduler_agent
    SA->>DB: scheduler_*_create/list/pause/resume/archive tool
    DB-->>SA: process_id / status
    SA-->>ORCH: scheduler result
    ORCH-->>User: confirmation

    loop every poll interval
        WORKER->>DB: claim_due_processes
        DB-->>WORKER: claimed process
        WORKER->>ADAPT: run(process)
        alt LLM-assisted process
            ADAPT->>MA: optional market_agent.handle()
            ADAPT->>CA: optional company_agent.handle()
        else deterministic process
            ADAPT->>ADAPT: evaluate trigger with services
        end
        ADAPT-->>WORKER: adapter result
        WORKER->>DB: record run outcome
        WORKER->>NOTIF: send notification
        NOTIF->>HIST: record outbound assistant message
    end
```

Scheduler adapters currently call specialists directly rather than routing
through `main_orchestrator`, because a scheduled run is already scoped by its
stored process definition. The notification is still written into chat history
so the next user message gives the orchestrator the full conversation context.

## Scheduled Process To Agent Map

```mermaid
flowchart LR
    SW[SchedulerWorker] --> IM[instrument_monitor]
    SW --> CEA[company_event_analyst]
    SW --> MRM[market_regime_monitor]
    SW --> MSC[market_signal_capture]
    SW --> TSM[trade_setup_monitor]

    IM --> MDS[MarketDataService only]
    CEA -->|optional context| MARKET[market_analyst]
    CEA --> COMPANY[company_analyst]
    MRM --> MARKET
    MSC --> MARKET
    TSM --> MARKET
    TSM --> PAS[PendingAction/Proposal services<br/>only if proposal creation is configured]
```

No scheduled process submits broker orders directly. Trade setup monitors may
prepare proposals/pending actions only when explicitly configured; future
execution still requires Telegram button approval.

## Approval And Side-Effect Boundary

```mermaid
flowchart TD
    USER[User text] --> ORCH[main_orchestrator]
    ORCH --> ORDER[order_agent]
    ORDER --> PREP[Prepare exact pending action]
    PREP --> PA[PendingActionService]
    PA --> TG[Telegram approval buttons]
    TG -->|pa:approve:action_id| EXEC[Execute stored action]
    TG -->|pa:reject:action_id| REJ[Reject stored action]

    USER -. typed yes/proceed/approve .-> ORCH
    ORCH -. ordinary conversation .-> ORDER

    classDef effect fill:#ffe6e6,stroke:#b83232,color:#123;
    class PREP,PA,TG,EXEC,REJ effect;
```

Natural-language messages can request or revise a side effect. They do not
approve or reject a pending side effect. Approval and rejection happen through
Telegram callback payloads only.

## Context Interpolation

```mermaid
flowchart TD
    HIST[Recent chat history] --> ORCH[main_orchestrator prompt]
    GUIDE[Guideline memory] --> ORCH
    TIME[Timezone/current time context] --> ORCH
    USER[Latest user request] --> ORCH

    ORCH -->|delegation guidance| SPEC[Specialist prompt]
    HIST --> SPEC
    GUIDE --> SPEC
    TIME --> SPEC

    SCHEDMSG[Scheduler notification] --> JOURNAL[ChatHistoryJournal]
    JOURNAL --> HIST
```

Every specialist receives the recent chat history from the request. Scheduler
notifications bypass the orchestrator at send time, but they are appended as
assistant history so later orchestrator turns can see them.

## Current Limitations To Keep Visible

- The full `reason -> plan -> execute -> judge -> return` loop is implemented
  only partially. `market_analyst` and key `order_agent` paths use the reusable
  reasoner, planner, and grouped executor; the judge step is not yet wired into
  that loop by default.
- `portfolio_analyst`, `company_analyst`, and some specialist fallback paths
  still use the older base `plan -> execute` shape.
- `scheduler_agent` and `log_diagnostic_agent` use bounded tool orchestration,
  not the grouped reason/plan executor.
- Scheduler worker invocations intentionally bypass the orchestrator, so they
  must keep writing outbound results to chat history for later context.
- Optional agents are absent from the orchestrator toolbox when their backing
  runtime components are unavailable.

## Reading The Graph

Use this map together with:

- [AGENTIC_FLOW.md](./AGENTIC_FLOW.md) for the target step model.
- [ARCHITECTURE_DIAGRAMS.md](./ARCHITECTURE_DIAGRAMS.md) for broader runtime
  architecture.
- [DEV_GUIDELINES.md](./DEV_GUIDELINES.md) for implementation rules and
  tracing/logging expectations.
