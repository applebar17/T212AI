# News And Web Search Strategy

Status: design reference.

## Goal

Give the agent broader market awareness without letting headlines or random search results bypass execution controls.

The initial focus should be broad market and portfolio-relevant context first, then deeper company-level research later when needed.

## What This Layer Should Do

- collect recent company, ETF, sector, and macro news
- discover primary sources through web search
- summarize developments with citations
- detect catalysts, risks, and repeated themes
- feed structured evidence into trade proposals
- drive research alerts and daily digests

## What This Layer Should Not Do

- place trades directly
- treat a search result page as authoritative evidence
- rely on one article to justify a live trade
- hide the sources used in a recommendation

## Source Hierarchy

### Highest trust

- company investor relations pages
- regulatory filings
- exchange notices
- official central bank, inflation, jobs, or other macro releases

### Medium trust

- structured news providers
- well-known financial publishers
- earnings transcript sources

### Lower trust

- generic search results
- convenience aggregators
- secondary commentary and opinion pieces
- community and social sources

The system should always try to lift a thesis toward higher-trust evidence when possible.

## Suggested Research Pipeline

1. Start from a ticker, portfolio, watchlist, or macro topic.
2. Query the news provider for recent items.
3. Run web search only when deeper evidence or primary documents are needed.
4. Fetch source metadata:
   - publisher
   - URL
   - publish time
   - retrieval time
   - title
5. Deduplicate similar stories.
6. Classify each item:
   - earnings
   - guidance
   - regulation
   - M&A
   - analyst action
   - macro
   - product
   - litigation
   - sentiment
7. Score each item for relevance, freshness, novelty, and source quality.
8. Build a structured research packet for the LLM.
9. Let the LLM summarize only the already-retrieved evidence.

## Suggested News Features

- `/help`
- `/news <ticker>`
- `/briefing`
- `/why <ticker>`
- portfolio news digest
- macro morning note
- catalyst alerts for watchlist names
- "what changed since yesterday?" summaries

## Safety Rules

- at least one citation is required for any news-based explanation
- at least one high-trust or two independent medium-trust items are required for news-driven proposals
- single-headline decisions are blocked in live mode
- contradictory sources reduce confidence
- stale articles should not be presented as fresh catalysts

Citation detail can stay moderate in normal Telegram replies, but the system should still retain source traceability internally for research-backed proposals.

## Useful Output Shape

```ts
interface NewsItem {
  id: string;
  ticker?: string;
  title: string;
  publisher: string;
  url: string;
  publishedAt: string;
  retrievedAt: string;
  eventType: string;
  sentiment?: "positive" | "negative" | "mixed" | "neutral";
  relevance: number;
  sourceQuality: number;
}
```

## How It Connects To The Agent

- the Telegram bot asks for a briefing or an analysis
- the orchestrator gathers account and market context
- the research layer adds news and web evidence
- the policy engine decides whether that evidence is strong enough for suggestion-only or proposal mode
- the LLM explains the evidence in plain language with citations

## Recommended v1 Scope

Keep this disciplined:

1. One news source
2. One web search path
3. One optional community-signal path for discovery only
4. Citation-preserving summaries
5. No direct execution based on this layer alone

That gives you a strong research assistant without turning the system into a fragile headline trader.
