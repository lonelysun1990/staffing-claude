# Agent evaluation and observability implementation plan

Copy of the approved plan (see also project todos). Implementation lives in `backend/app/agent/trace_context.py`, `backend/evals/`, `.github/workflows/`, and `.claude/plans/railway-agent-setup.md`.

## Current integration points (facts from the repo)

- The agent entrypoint is `run_agent_stream` (`backend/app/agent/loop.py`) → consumed by `POST /agent/chat/stream` (`backend/app/main.py`) (auth required via `require_auth`).
- The loop already emits structured phases you can record: `tool_call_start` (name + args), `tool_result`, `text_delta`, `done` / `error`. It persists messages via `chat_storage`.
- Production stack: FastAPI + PostgreSQL (`DATABASE_URL` in `database.py`), Railway starts with `uvicorn app.main:app` (`backend/railway.toml`). No Dockerfiles in-repo (Nixpacks).

## Framework choices

| Concern | Recommendation |
|--------|----------------|
| Unit / deterministic tests | pytest |
| Offline agent eval | Custom `backend/evals/` (YAML cases + runner) |
| Trace storage + dashboards | Optional Langfuse (env-gated) |
| APM / infra | Railway metrics + optional OTLP later |

## Rollout order

1. Structured trace logging in `loop.py` + log-based metrics.
2. Eval harness with YAML cases + fixtures.
3. Optional Langfuse once JSON reports are stable.
4. CI workflow for scheduled eval; PR gate only for fast tests.

## Security notes

- Eval runner uses a real DB user via `ensure_eval_user`; never commit API keys.
- Prefer running heavy eval in CI, not on production Railway.

## Implemented (this repo)

- `backend/app/agent/trace_context.py` — `trace_id`, `emit_agent_span`, SSE payload enrichment.
- `backend/app/agent/loop.py` — `_sse_with_trace`, structured spans on run/tool/error/done.
- `backend/app/main.py` — HTTP middleware with `X-Request-ID` and JSON request logs.
- `backend/evals/` — YAML cases, `runner.py`, `expectations.py`, `sse_parse.py`, `stats.py`, `fixtures/mini_store.json`.
- `backend/tests/test_sse_parse.py`, `backend/tests/test_agent_eval_smoke.py`, `backend/pytest.ini`.
- `.github/workflows/backend-ci.yml`, `.github/workflows/agent-eval-scheduled.yml` (manual).
- `.claude/plans/railway-agent-setup.md` — deployment and env notes.
