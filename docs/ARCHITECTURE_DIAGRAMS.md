# Architecture Diagrams

These diagrams complement [ARCHITECTURE_STATUS.md](./ARCHITECTURE_STATUS.md).

Mermaid fits this repo well because it stays plain-text, version-controlled, and readable inside Markdown.

## 1. Current High-Level Architecture

```mermaid
flowchart TD
    U[User] --> CLI[brokerai CLI]
    CLI --> CFG[.env Configuration]
    CLI --> RT[AppRuntime]

    RT --> ASSESS[Capability Assessment and Preflight]
    RT --> GUIDE[Guideline Memory]
    RT --> HIST[Chat History Manager]
    RT --> DB[SQLite Runtime DB]
    RT --> PACT[Pending Action Service]
    RT --> PROP[Proposal Service]
    RT --> RECON[Reconciliation Service]
    RT --> CALCSVC[Calculator Service]
    RT --> GENAI[GenAI Client]
    RT --> REASON[Agent Reasoner]
    RT --> JUDGE[Agent Judge]
    RT --> ORCH[Main Orchestrator Agent]
    RT --> CALCAGENT[Calculator Agent]

    ORCH --> PORT[Portfolio Analyst Agent]
    ORCH --> ORDER[Order Agent]
    ORCH --> MARKET[Market Analyst Agent]
    ORCH --> COMPANY[Company Analyst Agent]
    ORCH --> MEMORY[Guideline Memory Agent]

    RT --> T212[Trading 212 Service]
    RT --> ALPACA[Alpaca Market Data and Broker Services]
    RT --> YAHOO[Yahoo Client]
    RT --> ALPHA[Alpha Vantage Client]
    RT --> REDDIT[Reddit Research Service]

    CLI --> BOT[Telegram Bot]
    CLI --> R1[run reconcile-once]
    CLI --> R2[run worker]
    BOT --> TG[Telegram Bridge]
    TG --> HIST
    TG --> ORCH
    TG --> PACT

    R1 --> RECON
    R2 --> RECON
```

## 2. Current Wiring Reality

```mermaid
flowchart LR
    CLI[brokerai CLI] --> SETTINGS[AppSettings]
    SETTINGS --> ASSESS[assess_settings + preflight]
    SETTINGS --> RT[build_runtime]

    RT --> GDOC[Guideline Document Store]
    RT --> GSVC[Guideline Memory Service]
    RT --> HIST[Chat History Manager]
    RT --> DB[DB Engine and Session Factory]
    RT --> PACT[Pending Action Service]
    RT --> PROP[Proposal Service]
    RT --> RECON[Reconciliation Service]
    RT --> CALCSVC[Calculator Service]
    RT --> GENAI[GenAI Client]
    RT --> REASON[Agent Reasoner]
    RT --> JUDGE[Agent Judge]
    RT --> ORCH[Main Orchestrator Agent]
    RT --> CALCAGENT[Standalone Calculator Agent]

    RT --> T212[Trading 212 Client and Service]
    RT --> AB[Alpaca Broker Client and Service]
    RT --> Y[Yahoo Client]
    RT --> AM[Alpaca Market Data Client]
    RT --> A[Alpha Vantage Client]
    RT --> RD[Reddit Client and Service]
    RT --> W1[Portfolio Summary Workflow]
    RT --> W2[Pending Orders Review Workflow]

    BOT[TelegramBotService] --> TG[Telegram Bridge]
    TG --> ORCH
    TG --> HIST
    TG --> PACT
    TG --> PROP

    classDef wired fill:#dff3e4,stroke:#2d6a4f,color:#1b4332;
    classDef partial fill:#fff3cd,stroke:#b08900,color:#5f3b00;

    class CLI,SETTINGS,ASSESS,RT,GDOC,GSVC,HIST,DB,PACT,PROP,RECON,CALCSVC,GENAI,REASON,JUDGE,ORCH,CALCAGENT,T212,AB,Y,AM,A,RD,BOT,TG,W1,W2 wired;
```

## 3. Current Startup And Worker Surfaces

```mermaid
sequenceDiagram
    participant User
    participant CLI as brokerai
    participant Settings
    participant Runtime
    participant Telegram
    participant Reconcile

    User->>CLI: run bot
    CLI->>Settings: Load .env / parse config
    CLI->>Runtime: build_runtime(settings)
    CLI->>Telegram: TelegramBotService.from_settings(settings, runtime)
    Telegram-->>User: Polling bot starts

    User->>CLI: run reconcile-once or run worker
    CLI->>Settings: Load .env / parse config
    CLI->>Runtime: build_runtime(settings)
    CLI->>Reconcile: ReconciliationService
```

## 4. Current Request Flow

```mermaid
sequenceDiagram
    participant User
    participant Telegram
    participant History
    participant Orchestrator
    participant Specialist
    participant Workflow

    User->>Telegram: Natural-language request
    Telegram->>History: Load recent chat window
    Telegram->>Orchestrator: AgentRequest
    Orchestrator->>Orchestrator: Classify intent and route
    Orchestrator->>Specialist: Delegated request
    Specialist->>Specialist: Build plan
    Specialist->>Workflow: Optional thin deterministic flow
    Workflow-->>Specialist: Structured result
    Specialist-->>Orchestrator: AgentResponse
    Orchestrator-->>Telegram: Final answer
    Telegram->>History: Store user and assistant messages
    Telegram-->>User: Response
```

## 5. V1 Delivery Strategy

```mermaid
flowchart LR
    A[Micro tools first] --> B[Specialist agents use tools dynamically]
    B --> C[Observe repeated patterns]
    C --> D[Promote only stable patterns]
    D --> E[Add thin deterministic flows]
    E --> F[Design heavier workflows later]
```

## 6. Current Execution And Reconciliation Flow

```mermaid
sequenceDiagram
    participant User
    participant Telegram
    participant OrderAgent
    participant PendingAction
    participant Proposal
    participant Broker
    participant Reconcile
    participant DB

    User->>Telegram: "Buy TSLA for 200"
    Telegram->>OrderAgent: Delegated order request
    OrderAgent->>Proposal: Create proposal
    OrderAgent->>PendingAction: Persist exact prepared action
    OrderAgent-->>Telegram: Approval request
    Telegram-->>User: Approve / Reject
    User->>Telegram: Button click or yes/no fallback
    Telegram->>PendingAction: Resolve exact stored action
    PendingAction->>Broker: submit exact prepared action
    Broker-->>Telegram: Immediate broker response
    Telegram->>DB: Persist pending action / proposal / execution attempt

    Reconcile->>Broker: Read pending orders + recent history
    Reconcile->>DB: Sync local state with remote status
```

## 7. Current Limitation

```mermaid
flowchart TB
    A[Runtime is composed] --> B[Agents can route and plan]
    B --> C[Execution safety baseline is in place]
    C --> D[Proposal persistence and broker-aware reconciliation baseline are in place]
    D --> E[Calculator baseline exists as a standalone specialist]
    E --> F[But market context is still not unified]
    F --> G[Company and market thin flows are still missing]
    G --> H[Watchlist and broader scheduled jobs are still open]
```

## 8. Current Vs Near-Term Direction

```mermaid
flowchart TD
    NOW[Current repo] --> A[Runtime-owned app graph]
    NOW --> B[Approval-safe order flow for Trading 212 and Alpaca]
    NOW --> C[Proposal and execution journaling]
    NOW --> D[Broker-provider-aware reconciliation worker baseline]
    NOW --> E[Standalone calculator agent]

    A --> NEXT1[Unified market-context layer]
    B --> NEXT2[Better reconciliation UX]
    C --> NEXT3[More thin read flows]
    D --> NEXT4[Broader scheduled jobs]
    E --> NEXT5[Optional calculator routing later]
```

## Suggested Use

Use this file together with:
- [ARCHITECTURE_STATUS.md](./ARCHITECTURE_STATUS.md) for the written summary
- [PLAN.md](./PLAN.md) for the roadmap

The next useful diagrams would be:
- one diagram per real workflow once implemented
- market-context provider arbitration
- watchlist and scheduled-job flows
