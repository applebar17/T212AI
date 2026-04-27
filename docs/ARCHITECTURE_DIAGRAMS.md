# Architecture Diagrams

These diagrams are meant to complement [ARCHITECTURE_STATUS.md](./ARCHITECTURE_STATUS.md).

Mermaid is a good fit here:
- it works well for flowcharts
- it supports sequence diagrams
- it stays version-controlled as plain text inside Markdown

## 1. Current High-Level Architecture

```mermaid
flowchart TD
    U[User on Telegram] --> TG[Telegram Bridge]
    TG --> HIST[Chat History Manager]
    TG --> ORCH[Main Orchestrator Agent]

    ORCH --> PORT[Portfolio Analyst Agent]
    ORCH --> ORDER[Order Agent]
    ORCH --> MARKET[Market Analyst Agent]
    ORCH --> COMPANY[Company Analyst Agent]
    ORCH --> MEMORY[Guideline Memory Agent]

    ORCH --> REASON[Agent Reasoner]
    PORT --> REASON
    ORDER --> REASON
    MARKET --> REASON
    COMPANY --> REASON
    MEMORY --> REASON

    MEMORY --> GUIDE[Persistent Guideline Memory JSON]
    ORCH --> GUIDE
    PORT --> GUIDE
    ORDER --> GUIDE
    MARKET --> GUIDE
    COMPANY --> GUIDE

    ORDER --> T212[Trading 212 Service and Tools]
    PORT --> T212
    MARKET --> YAHOO[Yahoo Data Source]
    MARKET --> ALPHA[Alpha Vantage Data Source]
    MARKET --> REDDIT[Reddit Research Data Source]
    COMPANY --> YAHOO
    COMPANY --> ALPHA
    COMPANY --> REDDIT

    classDef implemented fill:#dff3e4,stroke:#2d6a4f,color:#1b4332;
    classDef partial fill:#fff3cd,stroke:#b08900,color:#5f3b00;

    class U,TG,HIST,ORCH,PORT,ORDER,MARKET,COMPANY,MEMORY,REASON,GUIDE,T212,YAHOO,ALPHA,REDDIT implemented;
```

## 2. Current Wiring Reality

```mermaid
flowchart LR
    RUNTIME[AppRuntime] --> GS[Guideline Memory Service]
    RUNTIME --> GDS[Guideline Document Store]

    TG[Telegram Bridge] --> ORCH[Main Orchestrator Agent]
    ORCH --> AGENTS[Specialist Agents]
    AGENTS --> GS

    T212[Trading 212 Integration]
    Y[Yahoo Integration]
    A[Alpha Vantage Integration]
    RD[Reddit Integration]
    WF[Workflow Layer]
    DB[SQLite and Alembic]
    APPROVAL[Approval and Proposal Flow]

    classDef wired fill:#dff3e4,stroke:#2d6a4f,color:#1b4332;
    classDef partial fill:#fff3cd,stroke:#b08900,color:#5f3b00;
    classDef missing fill:#f8d7da,stroke:#842029,color:#58151c;

    class RUNTIME,GS,GDS,TG,ORCH,AGENTS wired;
    class T212,Y,A,RD partial;
    class WF,DB,APPROVAL missing;
```

## 3. Target Architecture

```mermaid
flowchart TD
    U[User on Telegram] --> TG[Telegram Bridge]
    TG --> HIST[Chat History Manager]
    TG --> ORCH[Main Orchestrator Agent]

    ORCH --> PORT[Portfolio Analyst Agent]
    ORCH --> ORDER[Order Agent]
    ORCH --> MARKET[Market Analyst Agent]
    ORCH --> COMPANY[Company Analyst Agent]
    ORCH --> MEMORY[Guideline Memory Agent]

    ORCH --> JUDGE[Judge or Critic]

    PORT --> WF1[Portfolio Summary Workflow]
    ORDER --> WF2[Pending Orders or Execution Workflow]
    MARKET --> WF3[Market Snapshot Workflow]
    COMPANY --> WF4[Company Snapshot Workflow]
    MEMORY --> WF5[Guideline CRUD Workflow]

    WF1 --> T212[Trading 212 Service]
    WF2 --> T212
    WF3 --> YAHOO[Yahoo]
    WF3 --> ALPHA[Alpha Vantage]
    WF3 --> REDDIT[Reddit]
    WF4 --> YAHOO
    WF4 --> ALPHA
    WF4 --> REDDIT
    WF5 --> GUIDE[Persistent Guideline Memory]

    ORCH --> PROPOSAL[Proposal Service]
    ORDER --> PROPOSAL
    PROPOSAL --> DB[SQLite and Alembic Persistence]
    ORDER --> APPROVAL[Telegram Approval Flow]
    APPROVAL --> EXEC[Demo Execution and Reconciliation]
    EXEC --> T212
    EXEC --> DB
```

## 4. Target Request Flow

```mermaid
sequenceDiagram
    participant User
    participant Telegram
    participant History
    participant Orchestrator
    participant Specialist
    participant Workflow
    participant Provider
    participant DB

    User->>Telegram: Natural-language request
    Telegram->>History: Load recent chat window
    Telegram->>Orchestrator: AgentRequest
    Orchestrator->>Orchestrator: Classify intent and select agent
    Orchestrator->>Specialist: Delegated request
    Specialist->>Specialist: Build plan
    Specialist->>Workflow: Execute deterministic workflow
    Workflow->>Provider: Fetch broker or market data
    Provider-->>Workflow: Normalized data
    Workflow->>DB: Persist proposal or audit data if needed
    Workflow-->>Specialist: Structured result
    Specialist-->>Orchestrator: Final result
    Orchestrator-->>Telegram: Final answer
    Telegram->>History: Store user and assistant messages
    Telegram-->>User: Response
```

## 5. Execution Flow Target

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

## 6. Main Gaps

```mermaid
flowchart TB
    A[Current State] --> B[Runtime is too thin]
    B --> C[Providers are not composed centrally]
    C --> D[Agents mostly plan but do not run workflows]
    D --> E[Workflows are still placeholders]
    E --> F[No proposal lifecycle persistence]
    F --> G[No approval or execution pipeline]
    G --> H[No scheduled automation yet]
```

## Suggested Use

Use this file together with:
- [ARCHITECTURE_STATUS.md](./ARCHITECTURE_STATUS.md) for the written summary
- [PLAN.md](./PLAN.md) for the target roadmap

If useful, the next step can be a more operational set of diagrams:
- one diagram per workflow
- one diagram per runtime service
- one diagram for proposal and approval state transitions
