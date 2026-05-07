# T212AI

T212AI is a Telegram-first trading copilot: a focused, Clawbot-like bot vertical
for portfolio monitoring, market research, trade proposal preparation, and
approval-gated broker execution.

The goal is not to build a black-box autonomous trader. The useful v1 is a
personal trading assistant that can gather context, reason over holdings and
market signals, propose actions, and execute broker actions only after explicit
Telegram button approval.

## What It Does

- Reads broker-authoritative account state: cash, positions, pending orders,
  historical orders, and instrument metadata.
- Runs specialist agents for portfolio review, market analysis, company
  research, order preparation, calculator workflows, and persistent memory.
- Pulls market and research context from configured providers such as Yahoo,
  Alpaca market data, Alpha Vantage, SEC EDGAR, Reddit, and SearXNG.
- Stores compact market signals in the local SQL database so later analysis can
  reuse relevant trading notes without needing a vector database.
- Prepares broker orders and cancellation requests with deterministic validation.
- Uses Telegram inline buttons for approve/reject. Typed text such as "yes" or
  "approve" does not execute pending broker actions.
- Reconciles local pending actions and proposals against broker state through
  one-shot or worker commands.

## Safety Model

Broker execution is intentionally constrained.

- Demo/paper environments are the default development path.
- Live trading requires explicit configuration.
- Broker state comes from broker tools, not market-data providers or saved notes.
- Market signals are advisory context only; they are not execution authority.
- Order preparation validates broker-native instrument identifiers before
  approval.
- State-changing actions are prepared first, persisted as pending actions, and
  executed only through deterministic Telegram callback buttons.

This project is software infrastructure for personal research and execution
workflows. It is not financial advice.

## Architecture

The runtime is capability-first and provider-aware:

- `brokerai` / `t212ai` CLI for configuration, diagnostics, bot startup, and
  reconciliation workers.
- `AppRuntime` composes settings, provider clients, services, toolboxes,
  persistence, agents, and workflows.
- `MainOrchestratorAgent` manages conversation and delegates to specialists.
- Specialist agents use narrow toolboxes and structured planning/execution.
- SQLite stores pending actions, proposals, execution attempts, reconciliation
  metadata, and market signals.
- File-backed guideline memory stores durable user preferences and operating
  rules.

See the current architecture notes:

- [Architecture status](docs/ARCHITECTURE_STATUS.md)
- [Agentic flow](docs/AGENTIC_FLOW.md)
- [Development guidelines](docs/DEV_GUIDELINES.md)
- [Feature direction](docs/FEATURES.md)

## Providers

Broker providers:

- Trading 212 demo/live
- Alpaca paper/live

Market and research providers:

- Yahoo Finance
- Alpaca market data
- Alpha Vantage
- SEC EDGAR
- Reddit
- SearXNG plus page scraping

Observability:

- Optional LangSmith tracing

## Local Setup

Create an environment and install the package with useful extras:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[db,telegram,research,dev]"
```

Create local configuration:

```powershell
Copy-Item .env.example .env
brokerai configure --env-file .env
brokerai doctor --env-file .env
```

Run the Telegram bot:

```powershell
brokerai run bot --env-file .env
```

Run reconciliation once:

```powershell
brokerai run reconcile-once --env-file .env
```

Run the reconciliation worker:

```powershell
brokerai run worker --env-file .env --reconcile-every 15m
```

## Docker

Build and run with Docker Compose:

```powershell
docker compose build
docker compose up
```

The app service fails fast when these minimum bot variables are empty:

- `LLM_PROVIDER`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_CHAT_ID`

Provider-specific credentials are validated by the Python preflight at startup.

## Development

Run tests:

```powershell
python -m pytest
```

Run a fast smoke check:

```powershell
python -m pytest -q
```

Run the package entrypoint:

```powershell
python -m t212ai
```

## Current Direction

Near-term work is focused on making the trading bot more operationally useful:

- scheduled processes for digests, scans, and alerts
- richer market-signal read/write flows
- token context management for long tool-heavy LLM conversations
- stronger reason-plan-execute-judge loops across specialists
- more deterministic thin workflows where safety or repeatability matters
