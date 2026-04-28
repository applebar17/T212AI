# T212AI

Telegram-first AI investment agent for Trading 212.

The project is currently in baseline-shaping mode. The intended first build is:

- Python package under `src/t212ai`
- Trading 212 demo environment first
- Telegram natural-language interface
- manual approval for live side effects
- lightweight SQLite/Alembic persistence for operational state
- reusable GenAI/tool orchestration under `t212ai.genai`

See `docs/PLAN.md`, `docs/AGENT_DESIGN.md`, and `docs/REPO_STRUCTURE.md` for the current design direction.

## Development

Run the current smoke tests:

```powershell
$env:PYTHONPATH='src'; python -m pytest -q
```

Run the baseline package entrypoint:

```powershell
$env:PYTHONPATH='src'; python -m t212ai
```

Build the baseline container:

```powershell
docker compose build
```

`docker compose build` / `docker compose up` now fail fast for the app service if
these minimum bot variables are empty in `.env`:

- `LLM_PROVIDER`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_CHAT_ID`

Provider-specific LLM credentials such as `OPENAI_API_KEY` or Azure OpenAI
settings are still validated by the Python preflight at container startup.
