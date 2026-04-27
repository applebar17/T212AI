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
    RT --> GENAI[GenAI Client]
    RT --> REASON[Agent Reasoner]
    RT --> JUDGE[Agent Judge]
    RT --> ORCH[Main Orchestrator Agent]
    RT --> PACT[Pending Action Service]

    ORCH --> PORT[Portfolio Analyst Agent]
    ORCH --> ORDER[Order Agent]
    ORCH --> MARKET[Market Analyst Agent]
    ORCH --> COMPANY[Company Analyst Agent]
    ORCH --> MEMORY[Guideline Memory Agent]

    RT --> T212[Trading 212 Service]
    RT --> YAHOO[Yahoo Client]
    RT --> ALPHA[Alpha Vantage Client]
    RT --> REDDIT[Reddit Research Service]

    CLI --> BOT[Telegram Bot]
    BOT --> TG[Telegram Bridge]
    TG --> HIST
    TG --> ORCH
    TG --> PACT
```

## 2. Current Wiring Reality

```mermaid
flowchart LR
    CLI[brokerai configure / doctor / run bot] --> SETTINGS[AppSettings]
    SETTINGS --> ASSESS[assess_settings + preflight]
    SETTINGS --> RT[build_runtime]

    RT --> GDOC[Guideline Document Store]
    RT --> GSVC[Guideline Memory Service]
    RT --> HIST[Chat History Manager]
    RT --> DB[DB Engine and Session Factory]
    RT --> PACT[Pending Action Service]
    RT --> GENAI[GenAI Client]
    RT --> REASON[Agent Reasoner]
    RT --> JUDGE[Agent Judge]
    RT --> ORCH[Main Orchestrator Agent]

    RT --> T212[Trading 212 Client and Service]
    RT --> Y[Yahoo Client]
    RT --> A[Alpha Vantage Client]
    RT --> RD[Reddit Client and Service]
    RT --> W1[Portfolio Summary Workflow]
    RT --> W2[Pending Orders Review Workflow]

    BOT[TelegramBotService] --> TG[Telegram Bridge]
    TG --> ORCH
    TG --> HIST
    TG --> PACT

    APPROVAL[Telegram Approval Flow]
    PROPOSAL[Proposal Lifecycle]
    RECON[Execution Reconciliation]

    classDef wired fill:#dff3e4,stroke:#2d6a4f,color:#1b4332;
    classDef partial fill:#fff3cd,stroke:#b08900,color:#5f3b00;
    classDef missing fill:#f8d7da,stroke:#842029,color:#58151c;

    class CLI,SETTINGS,ASSESS,RT,GDOC,GSVC,HIST,DB,PACT,GENAI,REASON,JUDGE,ORCH,T212,Y,A,RD,BOT,TG,W1,W2 wired;
    class APPROVAL partial;
    class PROPOSAL,RECON missing;
```

## 3. Current Startup Flow

```mermaid
sequenceDiagram
    participant User
    participant CLI as brokerai run bot
    participant Settings
    participant Runtime
    participant Telegram

    User->>CLI: Start bot
    CLI->>Settings: Load .env / parse config
    CLI->>Settings: Assess providers and preflight
    CLI->>Runtime: build_runtime(settings)
    Runtime->>Runtime: Build memory, history, GenAI, agents, providers
    CLI->>Telegram: TelegramBotService.from_settings(settings, runtime)
    Telegram-->>User: Bot starts in polling mode
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

## 6. Current Limitation

```mermaid
flowchart TB
    A[Runtime is now composed] --> B[Agents can route and plan]
    B --> C[Providers are available as building blocks]
    C --> D[Thin read flows now exist for portfolio summary and pending orders review]
    D --> E[Thin execution safety flow exists for prepared actions]
    E --> F[But proposal lifecycle persistence is still missing]
    F --> G[Execution reconciliation and audit depth are still missing]
```

## 7. V1 Execution Safety Model

```mermaid
sequenceDiagram
    participant User
    participant Telegram
    participant OrderAgent
    participant PendingAction as Pending Prepared Action
    participant Broker

    User->>Telegram: "Buy TSLA for 200 dollars"
    Telegram->>OrderAgent: Delegated order request
    OrderAgent->>Broker: prepare_order
    Broker-->>OrderAgent: Prepared order details
    OrderAgent->>PendingAction: Persist exact prepared action
    OrderAgent-->>Telegram: Approval request with buttons and chat fallback
    Telegram-->>User: Approve / Reject
    User->>Telegram: Button click or yes/no fallback
    Telegram->>PendingAction: Resolve exact stored pending action
    PendingAction->>Broker: submit exact prepared action
    Broker-->>Telegram: Execution result
    Telegram->>PendingAction: Persist final state
    Telegram-->>User: Submitted or failed
```

## 8. Target Architecture

```mermaid
flowchart TD
    U[User] --> CLI[brokerai CLI]
    CLI --> RT[AppRuntime]
    CLI --> BOT[Telegram Bot]

    RT --> GUIDE[Guideline Memory]
    RT --> HIST[Chat History]
    RT --> ORCH[Main Orchestrator Agent]
    RT --> JUDGE[Agent Judge]
    RT --> T212[Trading 212 Service]
    RT --> YAHOO[Yahoo]
    RT --> ALPHA[Alpha Vantage]
    RT --> REDDIT[Reddit]
    RT --> DB[SQLite and Alembic]

    BOT --> TG[Telegram Bridge]
    TG --> ORCH

    ORCH --> PORT[Portfolio Analyst]
    ORCH --> ORDER[Order Agent]
    ORCH --> MARKET[Market Analyst]
    ORCH --> COMPANY[Company Analyst]
    ORCH --> MEMORY[Guideline Memory Agent]

    PORT --> WF1[Portfolio Summary Workflow]
    ORDER --> WF2[Pending Orders or Execution Workflow]
    MARKET --> WF3[Market Snapshot Workflow]
    COMPANY --> WF4[Company Snapshot Workflow]
    MEMORY --> WF5[Guideline CRUD Workflow]

    WF1 --> T212
    WF2 --> T212
    WF3 --> YAHOO
    WF3 --> ALPHA
    WF3 --> REDDIT
    WF4 --> YAHOO
    WF4 --> ALPHA
    WF4 --> REDDIT
    WF5 --> GUIDE

    ORDER --> PROPOSAL[Proposal Service]
    PROPOSAL --> DB
    ORDER --> APPROVAL[Telegram Approval Flow]
    APPROVAL --> EXEC[Demo Execution and Reconciliation]
    EXEC --> T212
    EXEC --> DB
```

## 9. Execution Flow Target

```mermaid
sequenceDiagram
    participant User
    participant Telegram
    participant Orchestrator
    participant OrderAgent
    participant ProposalService
    participant ApprovalFlow
    participant Trading212
    participant DB

    User->>Telegram: "Buy X shares of NVDA"
    Telegram->>Orchestrator: Request
    Orchestrator->>OrderAgent: Delegated order request
    OrderAgent->>ProposalService: Create structured proposal
    ProposalService->>DB: Persist proposal
    ProposalService-->>Telegram: Proposal summary with risks
    Telegram-->>User: Approval request
    User->>Telegram: Approve proposal
    Telegram->>ApprovalFlow: Approval message
    ApprovalFlow->>DB: Persist approval
    ApprovalFlow->>Trading212: Submit prepared order
    Trading212-->>ApprovalFlow: Execution result
    ApprovalFlow->>DB: Persist execution and reconciliation
    ApprovalFlow-->>Telegram: Final outcome
    Telegram-->>User: Executed or failed result
```

## Suggested Use

Use this file together with:
- [ARCHITECTURE_STATUS.md](./ARCHITECTURE_STATUS.md) for the written summary
- [PLAN.md](./PLAN.md) for the roadmap

The next useful diagrams would be:
- one diagram per real workflow once implemented
- proposal lifecycle state transitions
- approval and reconciliation state transitions
