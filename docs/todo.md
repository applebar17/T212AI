# Todo

1. Create tooling for scheduling a process.
2. Improve the reasoning pipeline to include additional reasoning and action adjustments at each plan step.
3. Improve application logging around Telegram requests, agent routing, LLM steps, tool calls, tool outputs, and provider errors so production debugging can reconstruct what happened without leaking secrets.
4. Create a read-only developer diagnostic agent that can be plugged into the orchestrator only on debug launch/env configuration, fetch bounded container/application logs, summarize the execution path, and explain under-the-hood failures for support/debugging.
