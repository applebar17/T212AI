# Todo

1. Create tooling for scheduling a process.
2. Improve the reasoning pipeline to include additional reasoning and action adjustments at each plan step.
3. Add a GenAI token context manager service for long conversations and tool-heavy flows: before LLM calls, estimate context tokens and invoke a summarization flow when usage approaches a configurable threshold such as `max_context_tokens * 0.95`; after provider failures, inspect the error for context-length/token-limit signals and retry with summarized context. The summarizer should preserve the system prompt and the most recent interactions as-is, summarize an older configurable slice of messages into one compact context message, then continue appending new messages normally.
