# Open Questions

Status: answered design reference.

## Product And Strategy

- Is the first version strictly for your own account, or should multi-user support exist later?
    Personal use just for me
- Do you want the agent to be portfolio-centric, watchlist-centric, or strategy-centric?
    TBD - no idea yet - strategy centric i guess
- What style of investing matters most: long-term accumulation, swing trading, rebalancing, event-driven, or mixed?
    i guess a mixed approach between rebalancing, with focus on speculation and intra-day trading
- Should the first execution mode be demo-only until a checklist is passed?
    we develop and test on the `https://demo.trading212.com/api/v0` - when we pass to prod or live stage, we move to real trading service

## Execution Policy

- Which order types do you actually want to support first: market and limit only, or all four supported types?
    all supported
- Should live orders always require Telegram approval?
    each decision will pass by my own confirmation through telegram
- Do you want ticker allowlists or blocklists from day one?
    we set up the infrastructure
- What should the max order size and max position size be?
    tbd - configurable
- Should extended-hours trading be disabled by default?
    yes

## Data Sources

- Which external datasets are essential for you at the beginning: prices, news, fundamentals, earnings calendar, macro calendar?
    prices and news for sure, then calendars i guess
- Do you care more about broad market context or deep company-level research?
    broad market first, then we can set up deep company level search agents when needed
- Do you want near-real-time data, delayed data, or end-of-day data at first?
    (almost) real time data
- Are you willing to pay for an execution-adjacent real-time feed, or should v1 stay on delayed data plus broker state?
    no, we can rely on free feeds when needed, for example we my include reddit as external data source + trading 212 feed as well
- Should Yahoo be treated as a convenience-only source from day one?
    yes

- Do you want a formal news feed, web search, or both?
    we can design both and then evaluate what to plug in
- How important are citations and source traceability in Telegram responses?
    medium

## User Experience

- Do you prefer slash commands, free text, or both in Telegram?
    we use both, but free text managed by llms is the preferred way. we design commands as fallbacks + easy automation (i want to be able to cancel an order both through request as well through command - include /help command for commands recap)
- Should the bot send scheduled daily digests automatically?
    yes
- Do you want inline approve/reject buttons or command-based approvals only?
    we can design both, but approval will likely be text-based (natural language)

## Technical Foundation

- What baseline code already exists for your LLM and tooling stack, and where is it? 
    ./genai : there's a lot of dedupes from the other projects, we need to clean up the stuff
- Do you already have a preferred runtime such as Python or TypeScript?
    python first
- Do you want a simple local deployment first or a cloud-hosted bot from the start?
    we'll go containerization-based approach. we'll locally dev first - containerize then and eventually deploy to cloud in the end
- Do you want SQLite first for speed, or a network database immediately?
    Do we need a db? for storing what information

## Governance

- How much of the agent's reasoning do you want stored for audit?+
    no audit needed so far
- Should the system keep a permanent journal of proposals, approvals, and outcomes?
    tbd, maybe a monday highlight of interesting intra-day investments
- What conditions should force the system into read-only mode automatically?
    command i guess for now - we can make a command for switching between paper and real as well
