# Trading 212 Telegram Agent Features

Status: design reference.

## Product Position

This should start as an investment copilot, not a black-box autonomous trader.
The first useful version is an agent that can:

- understand your portfolio and Trading 212 account state
- pull external market context
- turn that context into trade proposals
- ask for approval in Telegram
- execute approved orders safely through the Trading 212 API

If this becomes fully autonomous later, that should be a separate mode with much stricter controls.

## Confirmed Baseline

- personal-use only
- Telegram is the main interface
- free text is preferred; commands are fallbacks and automation shortcuts
- Python is the first implementation target
- local development first, then containerization, then cloud deployment later
- Trading 212 demo is the first execution environment
- every live trading decision requires your confirmation in Telegram
- persistence should stay lightweight and local at first

## Operating Modes

### 1. Read-only analyst

The agent can:

- summarize cash, positions, pending orders, and recent activity
- answer portfolio questions in Telegram
- explain exposure, concentration, and PnL
- monitor watchlists and notify you
- generate buy/sell ideas without executing anything

This is the safest and most useful starting point.

### 2. Approval-based execution

The agent can:

- create a structured trade proposal
- show rationale, supporting data, and risks
- ask for explicit approval in Telegram
- place or cancel the order only after approval

This should be the first execution-capable mode.

### 3. Guarded automation

The agent can execute without manual approval, but only inside user-defined guardrails such as:

- allowed instruments
- max order size
- max daily turnover
- max position size
- max portfolio drawdown before stop
- approved strategy template

This should not exist in v1.

## Interaction Model

The primary interface should be natural language in Telegram.

Commands are still useful, but only as shortcuts for common tasks. The core product should be:

- user expresses an intent in plain language
- the agent maps that intent to available tools and data sources
- the agent gathers context dynamically
- the agent explains, proposes, or executes based on policy

This matters because the useful requests will not always fit into a fixed command list.

Examples of the actual target experience:

- "Cancel my oldest pending buy order if it is still open."
- "Check whether any of my pending orders should be cancelled based on current price and news."
- "Look at my portfolio and tell me what needs attention today."
- "Compare my current allocation with my target and propose the smallest rebalance."
- "If my largest position is above 15%, propose how to trim it."
- "Explain what changed since yesterday and whether I should act."

## Core User Jobs

- "What is my current portfolio state?"
- "Why is my portfolio up or down today?"
- "What changed in my holdings, pending orders, and cash?"
- "Give me trade ideas for my watchlist based on fresh data."
- "Propose a rebalance based on my target allocation."
- "Place a limit or market order after I approve it."
- "Warn me when risk, concentration, or event exposure gets too high."
- "Send me a daily digest before market open and after market close."

## MVP Feature Set

### Portfolio and account visibility

- account summary sync from Trading 212
- positions sync
- pending orders sync
- historical orders and transactions sync
- Telegram commands for summary, positions, orders, and recent history

### LLM-assisted analysis

- natural-language portfolio Q&A in Telegram
- structured market, portfolio, company, or ETF analysis on request
- trade proposal generation with rationale, confidence, catalysts, and risks
- concise explanations of why the agent is suggesting an action
- cited summaries from recent news and web research

### External data ingestion

The Trading 212 API is not enough for decision-making on its own, so the agent should ingest:

- market prices and recent performance
- broad market context first
- instrument metadata and exchange session status
- news and event feeds
- earnings and macro calendars
- company fundamentals and ETF composition later where relevant
- optional sentiment or community signals later

Recommended source roles:

- Trading 212 for broker-authoritative account state, positions, orders, and execution only
- one pluggable price feed for almost-real-time market context, with free options preferred at the start
- Alpha Vantage or similar enrichment providers for fundamentals, indicators, macro and broader context
- news feeds and web search for catalysts, discovery, and supporting evidence
- Yahoo Finance only for non-critical enrichment, cross-checking, or convenience features unless a more official integration path is chosen later
- Reddit or similar community sources only as informational signals, never as execution-grade truth

The main design rule is that execution-critical decisions should not depend on a weak or unofficial source.

### Safe execution

- Trading 212 demo and live environment support
- proposal-to-order workflow
- Telegram approval flow with natural-language confirmation as the baseline
- limit, market, stop, and stop-limit order support
- cancel pending order support
- post-submit reconciliation and status reporting

### Monitoring and notifications

- price and percentage move alerts
- portfolio concentration alerts
- earnings and macro event reminders
- order state change notifications
- daily or weekly portfolio digest
- ticker-specific news digest and catalyst alerts

## Important Constraints From Trading 212

- order placement endpoints are beta and non-idempotent
- sell orders require negative quantity
- orders execute only in the main account currency
- API use is limited to Invest and Stocks ISA accounts
- rate limits vary by endpoint and need explicit throttling
- the Pies API is deprecated and should not be a design center

These constraints should shape the architecture, especially around execution safety.

## Recommended v1 Telegram UX

The first version can support both:

- natural-language chat as the main interface
- slash commands as fast paths for repeatable tasks

### Commands

- `/help`
- `/summary`
- `/positions`
- `/orders`
- `/history`
- `/watchlist`
- `/analyze <ticker>`
- `/proposal <buy|sell> <ticker> ...`
- `/approve <proposal_id>`
- `/reject <proposal_id>`
- `/cancel_order <order_id>`
- `/digest now`

### Natural-language examples

- "Why is my portfolio down today?"
- "Analyze VWCE and tell me if it fits my current allocation."
- "Propose a limit order to add 300 EUR to AAPL."
- "Show the risks before placing anything."
- "Cancel the oldest pending order for Tesla if it is still unfilled."
- "Should I cancel any pending orders before the market opens?"
- "Use the latest news and my current positions to tell me what needs attention."
- "Approve the last proposal for AAPL if it still fits my policy."

## Strongly Recommended Non-Goals For v1

- fully autonomous trading in live mode
- opaque LLM-only execution without deterministic checks
- high-frequency or intraday scalping
- strategies that require tick-level or ultra-low-latency data
- multi-user platform concerns
- deposits, withdrawals, or account administration
- support for deprecated Pies workflows
- heavyweight audit/compliance infrastructure

## Good v2 Candidates

- strategy templates such as DCA, rebalance, value screen, trend follow
- watchlist scoring and ranking
- portfolio journal and trade review notes
- personalized investment policy statement
- paper-vs-live performance comparison
- scenario analysis and stress testing
- news-driven idea discovery with source citations
- on-demand deep company research specialists
