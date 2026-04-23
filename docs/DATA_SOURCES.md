# Data Source Strategy

Status: design reference.

## Goal

Separate broker-authoritative data, execution-adjacent market data, and research enrichment so the agent can make better decisions without confusing convenience data with execution-critical facts.

The current baseline is to prefer free or low-friction data sources first and keep every provider pluggable.

## Proposed Provider Roles

## 1. Trading 212

Primary role:

- broker state
- order execution
- pending order lookup
- historical account activity

Use it for:

- account summary
- positions
- orders
- transactions
- final execution state

Do not use it as the only decision data source. Its API is focused on brokerage operations, not rich market intelligence.

## 2. Alpaca

Primary role:

- real-time and historical market data
- streaming or event-driven price monitoring

Good fit for:

- live watchlist monitoring
- price alerts
- intraday bars and latest trade context
- execution-adjacent market awareness

Why it matters in this design:

- if you want Telegram alerts that react to market movement quickly, a real-time capable feed belongs here
- it reduces pressure on the LLM because price-based triggers can stay deterministic

In this project, Alpaca should be treated as one candidate price-feed provider, not a mandatory dependency.

## 3. Alpha Vantage

Primary role:

- enrichment and research data
- fundamentals
- economic indicators
- technical indicators
- slower-moving screening inputs
- Alpha Intelligence context such as news sentiment, earnings transcripts,
  institutional holdings, insider transactions, and cross-symbol analytics
- commodities context for macro and input-cost awareness

Good fit for:

- portfolio context
- factor or indicator calculations
- macro-aware commentary
- watchlist scoring
- ticker research packets that combine company fundamentals, news, and analytics
- commodity-aware sector or macro context

Why it matters in this design:

- it is useful for analysis features even if it is not the main real-time source

Current implementation boundary:

- client methods cover Time Series Stock Data APIs, Alpha Intelligence,
  Fundamental Data, and Commodities
- LLM tools are currently exposed only for Alpha Intelligence
- future agent/flow toolboxes should compose these raw methods into compact
  research packets rather than exposing every Alpha Vantage endpoint directly
- treat Alpha Vantage as third-party research context, not broker state

## 3A. News APIs And Event Feeds

Primary role:

- structured event awareness
- company, sector, and macro headlines
- catalyst and risk detection

Good fit for:

- daily digests
- ticker news summaries
- event-driven watchlist alerts
- adding context to trade proposals

Design rule:

- news should enrich decisions, but should not directly trigger execution without other confirming evidence

## 3B. Calendar Sources

Primary role:

- earnings awareness
- macro-event awareness
- scheduling market-sensitive digests

Good fit for:

- daily briefings
- event reminders
- risk-aware proposal generation

## 4. Yahoo Finance

Primary role:

- convenience and informational enrichment
- cross-checking
- non-critical summaries

Good fit for:

- quick lookup features
- convenience metadata
- optional news or calendar augmentation
- symbol search and ticker disambiguation
- quote snapshots and recent price analytics
- options-chain context for liquidity/skew awareness
- analyst-context enrichment where Yahoo quote-summary data is available

Caution:

- it should not become a hard dependency for execution or authoritative pricing
- use it only where a missing or changed response would not put the order workflow at risk
- Yahoo endpoints are unofficial/public and can change or require cookie/crumb
  handling, so tools must return actionable failure hints and the agent should
  pivot to another provider when Yahoo is unavailable

Current implementation boundary:

- `t212ai.data_sources.yahoo` owns the client and Yahoo-specific models
- the historical `t212ai.genai.tools.yahoo_finance` path remains as a
  compatibility re-export
- initial tools cover symbol search, quote snapshot, price analytics, market
  snapshot, options snapshot, and analyst snapshot
- outputs are intentionally verbose because they are consumed by the LLM as
  context packets

## 4A. Web Search

Primary role:

- discovery
- source expansion
- surfacing primary documents

Good fit for:

- finding recent filings, press releases, or macro releases
- broadening research beyond one data vendor
- retrieving supporting evidence for a thesis

Caution:

- search results are not evidence on their own
- the fetched pages still need source-quality checks and citations

## 4B. Community Sources

Primary role:

- sentiment hints
- theme discovery
- early signal exploration

Examples:

- Reddit
- community forums

Caution:

- these are informational-only inputs
- they can help discovery, but they should not justify execution by themselves

## Recommended Source Priority

Use the lowest tier that is strong enough for the job:

1. Trading 212 for anything account- or order-related
2. one designated price feed for live price context and intraday monitoring
3. news feeds and calendar sources for catalysts and event context
4. enrichment providers for indicators, fundamentals, and macro context
5. web search for discovery and source expansion
6. Yahoo and community sources for convenience or informational augmentation

## Usage Classes

Every data field used by the agent should be tagged with one of these classes:

- `broker_authoritative`
- `execution_adjacent`
- `research_enrichment`
- `informational_only`

This allows the policy engine to reason about data quality before approving a trade.

## Provider Abstraction

Create a provider interface instead of hardcoding vendor logic into the agent:

```ts
interface PriceFeedProvider {
  getLatestPrice(symbol: string): Promise<MarketDataPoint>;
  getBars(symbol: string, timeframe: string): Promise<MarketDataPoint[]>;
  getSessionStatus(symbol: string): Promise<MarketDataPoint>;
}

interface FundamentalsProvider {
  getCompanyProfile(symbol: string): Promise<MarketDataPoint[]>;
  getFundamentals(symbol: string): Promise<MarketDataPoint[]>;
}

interface EventProvider {
  getNews(symbol: string): Promise<EvidenceItem[]>;
  getCalendar(symbol: string): Promise<EvidenceItem[]>;
}
```

This keeps the agent portable if one provider changes pricing, coverage, or terms later.

## Data Fusion Rules

- normalize symbols into one internal canonical format
- keep the raw provider symbol alongside the canonical symbol
- attach timezone and `asOf` timestamps to every record
- never merge records without source provenance
- if price data is stale, mark downstream proposals as degraded
- if provider responses conflict materially, block execution or require manual review

## Suggested Feature Mapping

### Read-only bot features

- Trading 212 + one price feed + a news layer is enough for many portfolio and research features

### Real-time alerts

- Trading 212 + one designated price feed is the better pairing

### Proposal engine

- Trading 212 + one price feed + optional enrichment + a cited research layer is the strongest baseline

### Convenience research

- Yahoo can help, but only as an optional layer

## Recommended v1 Provider Strategy

If you want to keep the first build disciplined:

1. Trading 212 for account and order flows
2. One execution-adjacent market data provider
3. One cited news or event source
4. One calendar source
5. Web search only as a discovery layer
6. One enrichment provider only if it materially improves the first workflows
7. Yahoo and community sources only if a non-critical feature clearly benefits from them

That avoids building an overly messy source stack too early.
