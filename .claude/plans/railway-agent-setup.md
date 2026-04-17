# Railway and CI setup for agent eval and observability

## Railway (backend service)

1. **PostgreSQL**: Add the Railway PostgreSQL plugin and link it to the backend service. Railway injects `DATABASE_URL`.
   - If SQLAlchemy fails to connect, normalize the URL for SQLAlchemy 2 + psycopg2 (e.g. `postgresql+psycopg2://...`).

2. **Required environment variables**
   - `ANTHROPIC_API_KEY` — required for the staffing agent (Claude Agent SDK).
   - `SECRET_KEY` — JWT signing; use a long random string in production.
   - `ADMIN_USERNAME` / `ADMIN_PASSWORD` — optional; `bootstrap_admin` in `main.py` creates or promotes an admin user on startup.

3. **Optional**
   - `TAVILY_API_KEY` — enables Tavily MCP tools when set.
   - `AGENT_WORKSPACE_DIR` — directory for Claude Code cwd; defaults to a temp path with `git init` if unset.
   - `EVAL_USERNAME` / `EVAL_USER_PASSWORD` — for the offline eval runner user (defaults: `eval_runner` / `eval-change-me`).

4. **Observability**
   - **HTTP**: Each response gets `X-Request-ID`; logs include JSON lines with `"http_request": true` (path, status, duration_ms).
   - **Agent**: Logs include JSON lines with `"agent_trace": true`, `trace_id`, `span_type` (`run_start`, `tool_call_start`, `run_done`, `error`, etc.). Filter these in Railway log search.
   - Optional Langfuse or OTLP can be added later by forwarding logs or wiring OpenTelemetry; the app does not require a Langfuse package for production.

5. **Why not run offline eval on Railway**: Eval jobs call the real model and reset DB fixtures; run them in **GitHub Actions** (`workflow_dispatch` workflow) or locally with `cd backend && python -m evals --all` to avoid load and cost on production.

## GitHub Actions

- **backend-ci.yml**: Runs `pytest` on push/PR with a Postgres service container and `DATABASE_URL` set. Fast tests only (no live agent by default).
- **agent-eval-scheduled.yml**: **Manual** workflow only. Add repository secret `ANTHROPIC_API_KEY`. Requires a successful `pip install -r requirements.txt` including `claude-agent-sdk` (your private index if applicable) and a Claude Code–compatible runtime in the runner.

## Local eval

- Set `DATABASE_URL` to a dedicated local database.
- From `backend/`: `pip install -r requirements.txt` then `python -m evals --case evals/cases/example_smoke.yaml`.
