# Todo

Status: active implementation queue.

Completed or superseded setup tasks have been removed from this list. Keep this
file short; deeper design context belongs in the topic-specific docs.

1. Harden the Alpaca news-monitoring flow with live-stream volume tests,
   clearer worker/judge diagnostics, and notification behavior checks.
2. Improve compact Azure/OpenAI content-filter observability without logging raw
   prompts, chat content, account dumps, or secrets.
3. Continue broker order-resolution safety testing around broker-native tickers,
   ISIN metadata from broker instruments, and holdings-dependent sell orders.
4. Extend the log diagnostic agent later, if needed, to support rotated logs or
   container logs behind explicit debug configuration.
