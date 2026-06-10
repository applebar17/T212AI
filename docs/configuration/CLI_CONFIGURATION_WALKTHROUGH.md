# CLI Configuration Walkthrough

Status: operator setup reference.

This document explains where each value prompted by `brokerai configure` or
`brokerai onboard` comes from. Use it while running the wizard, then validate
the result with:

```bash
brokerai doctor --env-file .env
brokerai doctor --env-file .env --smoke
```

Keep all API keys, secrets, `.env` files, logs, databases, and guideline memory
files out of source control.

## Prompt Flow

The interactive wizard walks through these sections:

1. LLM configuration
2. Observability
3. Broker configuration
4. Telegram configuration
5. Market data configuration
6. Market intelligence
7. Symbol reference
8. Disclosure intelligence
9. Search integration
10. Local storage
11. Scheduler defaults

Some prompts only appear when you enable a provider or choose to customize an
optional section.

## LLM Configuration

### `LLM_PROVIDER`

Choose the reasoning provider:

- `openai`: use OpenAI platform API keys and OpenAI model ids.
- `azure_openai`: use an Azure OpenAI resource, API key, endpoint, and
  deployment names.
- `none`: disable LLM-backed bot behavior for storage, scheduler, or local-only
  work.

### OpenAI

Official setup links:

- [OpenAI API quickstart](https://developers.openai.com/api/docs/quickstart)
- [OpenAI API authentication](https://developers.openai.com/api/reference/overview#authentication)
- [OpenAI API keys](https://platform.openai.com/api-keys)

Walkthrough:

1. Sign in to the OpenAI platform.
2. Open the API keys page.
3. Create a project API key.
4. Copy the key once and store it securely.
5. Enter it as `OPENAI_API_KEY`.

Prompted variables:

- `OPENAI_API_KEY`: OpenAI platform API key.
- `OPENAI_CHAT_MODEL_DEFAULT`: baseline model for routine orchestration.
- `OPENAI_CHAT_MODEL_SMART`: optional stronger model for delicate analysis.
- `OPENAI_CHAT_MODEL_REASONING`: optional reasoning model for deeper planning.
- `OPENAI_EMBED_MODEL`: embedding model id.
- `OPENAI_EMBED_DIMENSIONS`: optional embedding dimension override.
- `GENAI_CONTEXT_TOKENS_DEFAULT`: context limit for the default model.
- `GENAI_CONTEXT_TOKENS_SMART`: context limit for the smart model.
- `GENAI_CONTEXT_TOKENS_REASONING`: context limit for the reasoning model.

For model prompts, prefer the wizard's listed choices. Use a custom model only
when it is already in the internal model context registry; otherwise the wizard
will reject it. For context-token prompts, accept the detected default unless
you know the deployment has a different context window.

### Azure OpenAI

Official setup links:

- [Create and deploy an Azure OpenAI resource](https://learn.microsoft.com/en-us/azure/cognitive-services/openai/how-to/create-resource)
- [Azure OpenAI key and endpoint quickstart](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/whisper-quickstart)

Walkthrough:

1. Create or select an Azure OpenAI resource in Azure.
2. In the Azure portal, open the resource's `Keys and Endpoint` area.
3. Copy the endpoint URL into `AZURE_OPENAI_ENDPOINT`.
4. Copy either key into `AZURE_OPENAI_API_KEY`.
5. Deploy the chat and embedding models you need.
6. Enter deployment names, not raw model ids, for the wizard's Azure model
   prompts.
7. Keep `AZURE_OPENAI_API_VERSION` at the default unless the deployed service
   requires a different API version.

Prompted variables:

- `AZURE_OPENAI_ENDPOINT`: resource endpoint, for example
  `https://example.openai.azure.com/`.
- `AZURE_OPENAI_API_KEY`: key from the Azure resource.
- `AZURE_OPENAI_API_VERSION`: Azure OpenAI API version used by the client.
- `OPENAI_CHAT_MODEL_DEFAULT`: Azure chat deployment for routine tasks.
- `OPENAI_CHAT_MODEL_SMART`: optional Azure chat deployment for delicate tasks.
- `OPENAI_CHAT_MODEL_REASONING`: optional Azure deployment for reasoning tasks.
- `AZURE_OPENAI_EMBED_DEPLOYMENT`: optional embedding deployment.
- `GENAI_CONTEXT_TOKENS_DEFAULT`: context limit for the default deployment.
- `GENAI_CONTEXT_TOKENS_SMART`: context limit for the smart deployment.
- `GENAI_CONTEXT_TOKENS_REASONING`: context limit for the reasoning deployment.

The Azure prompts reuse `OPENAI_CHAT_MODEL_*` names for compatibility, but the
values must be deployment names because Azure OpenAI calls deployments rather
than direct model ids.

## Observability

### LangSmith

Official setup link:

- [Create a LangSmith account and API key](https://docs.langchain.com/langsmith/create-account-api-key)

Walkthrough:

1. Sign in to LangSmith.
2. Open settings and create an API key.
3. Use a service key for deployed services, or a personal access token for local
   personal development.
4. Copy the key once and store it securely.
5. Keep the default endpoint unless your workspace uses a different LangSmith
   region.

Prompted variables:

- `LANGSMITH_TRACING`: `true` enables trace export.
- `LANGSMITH_ENDPOINT`: API endpoint, such as
  `https://eu.api.smith.langchain.com`.
- `LANGSMITH_API_KEY`: LangSmith key.
- `LANGSMITH_PROJECT`: project name used to group traces.

## Broker Configuration

### `BROKER_PROVIDER`

Choose the broker used for account-authoritative reads and order execution:

- `trading212`: Trading 212 broker adapter.
- `alpaca`: Alpaca broker adapter.
- `none`: research-only mode with no broker-authoritative account or execution
  provider.

### Trading 212

Official setup links:

- [Trading 212 API key help article](https://helpcentre.trading212.com/hc/en-us/articles/14584770928157-Trading-212-API-key)
- [Trading 212 public API documentation](https://docs.trading212.com/api/section/general-information/api-limitations)
- [Local Trading 212 API notes](../api/T212ApiDocs.md)

Walkthrough:

1. Open Trading 212 on web or mobile.
2. Go to `Settings`.
3. Open `API (Beta)`.
4. Accept the mandatory API risk warning.
5. Generate an API key pair.
6. Select the minimum permissions needed for the workflow you are testing.
7. Prefer IP restrictions when your deployment has a stable egress IP.
8. Copy both credentials. The secret is shown once; if you lose it, generate a
   new key pair.

Prompted variables:

- `T212_ENVIRONMENT`: `demo` for paper trading, `live` for real-money access.
- `T212_DEMO_API_KEY`: API key generated for the demo environment.
- `T212_DEMO_API_SECRET`: API secret generated for the demo environment.
- `T212_LIVE_API_KEY`: API key generated for the live environment.
- `T212_LIVE_API_SECRET`: API secret generated for the live environment.
- `T212_LIVE_TRADING_ENABLED`: explicit local safety switch for live order
  execution.

Start with `T212_ENVIRONMENT=demo`. Only switch to `live` after `brokerai
doctor --env-file .env --smoke` passes and you have reviewed the live-order
safety switch.

### Alpaca

Official setup links:

- [How to connect to Alpaca's Trading API](https://alpaca.markets/learn/connect-to-alpaca-api)
- [Alpaca paper trading documentation](https://docs.alpaca.markets/v1.4.2/docs/paper-trading)
- [Alpaca trading API getting started](https://docs.alpaca.markets/us/docs/getting-started-with-trading-api)

Walkthrough:

1. Create or sign in to an Alpaca account.
2. For development, select the paper trading account first.
3. Generate API credentials from the dashboard API keys panel.
4. Copy both the key and the secret. Store the secret immediately because it may
   only be visible at creation or regeneration time.
5. For live trading, open and qualify a live account, then generate the separate
   live key pair.
6. Keep paper and live credentials separate.

Prompted variables:

- `ALPACA_ENVIRONMENT`: `paper` for simulated trading, `live` for real-money
  access.
- `ALPACA_PAPER_API_KEY`: paper account key.
- `ALPACA_PAPER_API_SECRET`: paper account secret.
- `ALPACA_LIVE_API_KEY`: live account key.
- `ALPACA_LIVE_API_SECRET`: live account secret.

The wizard may ask for Alpaca credentials either when Alpaca is the broker or
when Alpaca is selected as the market-data provider.

## Telegram Configuration

Official setup links:

- [Telegram BotFather guide](https://core.telegram.org/bots/features#botfather)
- [Telegram Bot API reference](https://core.telegram.org/bots/api)

Walkthrough for `TELEGRAM_BOT_TOKEN`:

1. Open Telegram and message `@BotFather`.
2. Send `/newbot`.
3. Choose a display name.
4. Choose a username ending in `bot`.
5. Copy the token returned by BotFather.
6. Store it as `TELEGRAM_BOT_TOKEN`.

Walkthrough for allowed IDs:

1. Send a message to your new bot from the private chat or group you want to
   allow.
2. Open this URL in a browser, replacing the token:

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates
```

3. For a private chat, use the returned `message.chat.id` as
   `TELEGRAM_ALLOWED_CHAT_ID`.
4. For a group, add the bot to the group, send a message that the bot can see,
   then use that group's `message.chat.id`.
5. If you want user-level allow-listing too, use `message.from.id` as
   `TELEGRAM_ALLOWED_USER_ID`.

Prompted variables:

- `TELEGRAM_BOT_TOKEN`: BotFather token.
- `TELEGRAM_ALLOWED_CHAT_ID`: chat or group id allowed to interact with the bot.
- `TELEGRAM_ALLOWED_USER_ID`: optional user id allowed inside an allowed chat.

Treat the bot token like a password. Anyone with the token can control the bot.

## Market Data Configuration

### `MARKET_DATA_PROVIDER`

Choose the source used for quotes, bars, and chart context:

- `yahoo`: default local research baseline; no key is prompted by the wizard.
- `alpaca`: use Alpaca market data; the wizard will ask for Alpaca environment
  and credentials if Alpaca was not already configured as the broker.
- `none`: disable market-data lookup.

If you choose Alpaca here, follow the Alpaca credential walkthrough above and
keep paper/live credentials aligned with `ALPACA_ENVIRONMENT`.

## Market Intelligence

### Alpha Vantage

Official setup links:

- [Alpha Vantage API key page](https://www.alphavantage.co/support/#api-key)
- [Alpha Vantage documentation](https://www.alphavantage.co/documentation/)

Walkthrough:

1. Open the Alpha Vantage API key page.
2. Request a key using a real email address you can access.
3. Copy the generated key.
4. Enter it as `ALPHA_VANTAGE_API_KEY`.
5. Review current free and paid request limits before relying on it for frequent
   scheduler jobs.

Prompted variables:

- `MARKET_INTELLIGENCE_PROVIDER`: set to `alpha_vantage` when enabled.
- `ALPHA_VANTAGE_ENABLED`: `true` when Alpha Vantage is enabled.
- `ALPHA_VANTAGE_API_KEY`: Alpha Vantage API key.

Use Alpha Vantage as research enrichment, not broker-authoritative account or
order state.

## Symbol Reference

### EODHD

EODHD is the optional symbol-reference provider. It is used when the agent needs
help resolving ticker, company-name, ISIN, CUSIP, FIGI, LEI, or CIK ambiguity.
It is especially useful when a broker order flow cannot confidently map a public
symbol or company name to the broker-native instrument. EODHD is reference data
only: broker tools must still verify tradability, currency, broker-native
ticker, and order eligibility before any order action is prepared.

Official setup links:

- [EODHD financial APIs](https://eodhd.com/financial-apis/)
- [EODHD Search API](https://eodhd.com/financial-apis/search-api-for-stocks-etfs-mutual-funds-and-indices/)
- [EODHD ID Mapping API](https://eodhd.com/financial-apis/id-mapping-api-cusip-isin-figi-lei-cik-%E2%86%94-symbol)

What the service provides:

- `symbol_reference_search`: searches EODHD reference data by ticker, company
  name, or ISIN and returns instrument candidates. Results may include code,
  exchange, provider symbol, name, instrument type, country, currency, ISIN,
  previous close, previous close date, and primary-listing metadata.
- `symbol_reference_map_identifiers`: maps between EODHD symbols and identifiers
  such as ISIN, CUSIP, FIGI, LEI, and CIK.
- Broker order toolboxes expose only `symbol_reference_search`, and only when
  EODHD is configured. This gives the order agent a reference-only ISIN check
  during symbol-resolution complications without making EODHD execution
  authority.

Token walkthrough:

1. Create or sign in to an EODHD account.
2. Open the account dashboard or control panel.
3. Find the API token or API key area for your account.
4. Create or copy the active API token.
5. Store the token securely; treat it like a secret.
6. Enter it as `EODHD_API_TOKEN` in the wizard.
7. Keep `EODHD_BASE_URL` at `https://eodhd.com/api` unless you are testing a
   compatible endpoint.
8. Review the plan limits for Search and ID Mapping before using EODHD in
   frequent scheduler jobs.

Prompted variables:

- `SYMBOL_REFERENCE_PROVIDER`: set to `eodhd` when enabled.
- `EODHD_ENABLED`: `true` when EODHD is enabled.
- `EODHD_API_TOKEN`: EODHD API token from the account dashboard.
- `EODHD_BASE_URL`: base API URL, default `https://eodhd.com/api`.

Expected wizard interaction:

```text
Enable EODHD symbol reference? The configure smoke check consumes one API call. [y/N]: y
EODHD_API_TOKEN: eodhd-token
EODHD_BASE_URL [https://eodhd.com/api]:
```

Expected `.env` values:

```env
SYMBOL_REFERENCE_PROVIDER=eodhd
EODHD_ENABLED=true
EODHD_API_TOKEN=...
EODHD_BASE_URL=https://eodhd.com/api
```

`brokerai configure` and `brokerai doctor --smoke` run an EODHD smoke probe
when EODHD is enabled. The probe calls Search with `AAPL` and `limit=1`, so it
consumes one EODHD Search API call.

## Disclosure Intelligence

### SEC EDGAR

Official setup links:

- [SEC accessing EDGAR data](https://www.sec.gov/edgar/searchedgar/accessing-edgar-data.htm)
- [SEC company submissions API](https://data.sec.gov/)

Walkthrough:

1. Decide whether to enable SEC EDGAR filing intelligence.
2. Set `SEC_EDGAR_USER_AGENT` to identify your automated requests.
3. Use a value that includes a project, organization or personal name, and a
   working contact email.

Prompted variables:

- `DISCLOSURE_PROVIDER`: set to `sec_edgar` when enabled.
- `SEC_EDGAR_USER_AGENT`: optional but recommended request identification, for
  example `T212AI local research your.email@example.com`.

SEC EDGAR does not require an API key for the public data used here, but
automated clients should identify themselves and avoid abusive request patterns.

## Search Integration

The wizard currently displays this section but does not prompt for values.
SearXNG is expected to be configured by the deployment or Compose stack.

Related variables that may be edited manually later:

- `SEARCH_PROVIDER`: typically `searxng` or `none`.
- `SEARXNG_BASE_URL`: base URL for the SearXNG instance.
- `SEARXNG_ENABLED`: true/false feature switch.

## Local Storage

The wizard asks about these only when you choose to customize storage paths.
They do not come from an external provider.

Prompted variables:

- `APP_LOG_LEVEL`: application log level, for example `INFO` or `DEBUG`.
- `APP_LOG_FILE_PATH`: log file path.
- `APP_LOG_FORMAT`: `json` or text format, depending on configured support.
- `APP_LOG_RETENTION_DAYS`: log retention window.
- `APP_LOG_THIRD_PARTY_LEVEL`: log level for third-party libraries.
- `DATABASE_URL`: database URL; local default is SQLite.
- `GUIDELINE_MEMORY_PATH`: JSON file used for durable user guidelines.

Recommended local defaults:

```env
APP_LOG_LEVEL=INFO
APP_LOG_FILE_PATH=logs/t212ai.log
APP_LOG_FORMAT=json
DATABASE_URL=sqlite:///./data/t212ai.db
GUIDELINE_MEMORY_PATH=data/guidelines/guidelines.json
```

Use paths under persistent storage when running in containers. Never commit the
database, logs, or guideline memory if they can contain account, request, or
personal context.

## Scheduler Defaults

The wizard asks about these only when you choose to customize scheduler
behavior. They are local runtime policy values, not provider credentials.

Prompted variables:

- `SCHEDULER_DEFAULT_TIMEZONE`: IANA timezone used to interpret user schedule
  requests before UTC storage, for example `Europe/Rome` or `America/New_York`.
- `SCHEDULER_DEFAULT_POLL_EVERY_SECONDS`: default worker polling interval.
- `SCHEDULER_WORKER_ID`: optional stable identifier for a scheduler worker.
- `SCHEDULER_LEASE_SECONDS`: duration a claimed scheduler run is protected from
  other workers.
- `SCHEDULER_STALE_RUN_AFTER_SECONDS`: age after which started runs may be
  recovered as stale.
- `SCHEDULER_MAX_LLM_RUNS_PER_PASS`: throttle for LLM-assisted work; `0` means
  unlimited.
- `SCHEDULER_EMBEDDED_WORKER_ENABLED`: run scheduler inside the Telegram bot
  process.
- `SCHEDULER_EMBEDDED_WORKER_POLL_EVERY_SECONDS`: poll interval for embedded
  scheduler mode.
- `SCHEDULER_EMBEDDED_WORKER_LIMIT`: max jobs handled per embedded worker pass.
- `ALPACA_NEWS_STREAM_SUPERVISOR_ENABLED`: run Alpaca news stream monitors from
  the bot process.
- `ALPACA_NEWS_STREAM_SUPERVISOR_POLL_SECONDS`: supervisor poll interval.
- `ALPACA_NEWS_STREAM_LEASE_SECONDS`: news stream monitor lease duration.
- `ALPACA_NEWS_JUDGE_MAX_TOOL_CALLS`: max tool calls for news judging.

Recommended approach:

- Keep scheduler defaults unless you are actively operating background jobs.
- Use a real local IANA timezone for interactive schedule requests.
- Use a separate scheduler worker for production-like deployments.
- Keep embedded scheduler mode for simple local runs.

## Final Checks

After the wizard writes `.env`, run:

```bash
brokerai config validate --env-file .env
brokerai doctor --env-file .env
brokerai doctor --env-file .env --smoke
```

If smoke checks fail, confirm that:

- the selected provider matches the credential environment,
- demo/paper and live keys were not mixed,
- secrets were copied without extra spaces,
- live execution switches are intentionally set,
- Telegram chat and user ids came from the target chat,
- provider accounts are allowed in your country and account type.
