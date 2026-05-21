# Scheduler Process Catalog

This catalog summarizes the scheduled process types currently supported by the
local scheduler. The scheduler remains an audit-and-orchestration layer: broker
state, market data, research, approvals, and order preparation still come from
their configured authoritative services.

## Operational Commands

- `brokerai run scheduler-once --env-file .env` runs one worker pass.
- `brokerai run scheduler --env-file .env --poll-every 1m` runs the worker loop.
- `brokerai scheduler status --env-file .env` shows process counts, due work, active leases, stale run indicators, and operational defaults.
- `brokerai scheduler list --status active --kind instrument_monitor` lists process summaries.
- `brokerai scheduler show sched_... --runs 10 --events 20` shows one process plus recent audit rows.
- `brokerai scheduler recover-stale --older-than 1h --dry-run` previews stale-run recovery.
- `brokerai scheduler recover-stale --older-than 1h --apply` marks stale started runs as failed and recomputes lifecycle.
- `brokerai scheduler cleanup --archived-before 30d --dry-run` previews archived-record cleanup.
- `brokerai scheduler cleanup --archived-before 30d --apply` deletes archived process records plus associated runs/events.
- `brokerai scheduler export --output scheduler-export.json --include-runs --include-events` writes a read-only JSON audit/export file.

## Operational Defaults

- `SCHEDULER_WORKER_ID=` defaults to an auto-generated local worker id.
- `SCHEDULER_LEASE_SECONDS=1800` controls how long a claimed process is protected from other workers.
- `SCHEDULER_STALE_RUN_AFTER_SECONDS=3600` controls stale started-run recovery.
- `SCHEDULER_MAX_LLM_RUNS_PER_PASS=0` keeps LLM-assisted scheduler work unlimited by default. Positive values are operator-only throttles.

## Process Kinds

| Kind | Execution mode | Schedule support | Primary services | User-facing behavior |
| --- | --- | --- | --- | --- |
| `instrument_monitor` | deterministic | polling | market data | Sends a deterministic alert when a price, percent-change, or period high/low trigger matches. |
| `company_event_analyst` | llm_assisted | one-shot, recurring | company analyst, optional search/disclosure/market data | Produces scheduled company-event analysis and notification. |
| `market_regime_monitor` | llm_assisted after deterministic trigger | polling | market data, market analyst, optional search | Watches a broad-market proxy and calls the LLM only after stress conditions match. |
| `market_signal_capture` | llm_assisted | polling, recurring | market analyst, market signal memory, research evidence | Captures compact durable advisory market signals into local SQL memory. |
| `trade_setup_monitor` | llm_assisted after deterministic trigger | polling | market data, market analyst, broker read/preparation, proposals, pending actions, Telegram | Creates a pending order proposal only when explicitly enabled and risk caps validate the LLM-proposed terms. Nothing is submitted without Telegram button approval. |

## Safety Rules

- Direct broker execution is not representable in scheduler process specs.
- `safety.brokerActionsAllowed` must remain false.
- Trade setup monitors can prepare orders and create pending approval actions only when proposal creation is explicitly enabled.
- Cleanup commands are dry-run by default and mutate only with `--apply`.
- Export is read-only. Import is intentionally not implemented.
- LLM-assisted processes remain dynamic by default; optional LLM caps are operator guardrails, not product behavior defaults.
