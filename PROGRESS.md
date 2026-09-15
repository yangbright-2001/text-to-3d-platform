# Progress

## Current Status

M1 (project scaffold) complete. Backend boots and its health endpoint is tested and passing. No Meshy integration or persistence yet. Architecture and roadmap live in `PLAN.md`.

## Completed Features

- **M1 — Project scaffold**: repo layout (`backend/`, `frontend/` placeholder); FastAPI app with `GET /api/health`; config via pydantic-settings reading `backend/.env`; pinned `requirements.txt`; `.env.example`; root `.gitignore` and `README.md` with setup/run instructions.
- Non-code: architecture plan in `PLAN.md`; project workflow rules in `.cursor/rules/project.mdc`.

## Current Feature

- None in progress. M1 done and validated; awaiting go-ahead for **M2 — Persistence layer**.

## Next Steps

1. M2: SQLite wiring + SQLAlchemy `Generation` model with the app-level status state machine, plus tests.
2. Then proceed milestone by milestone (M3–M10) per `PLAN.md`, one feature at a time with tests and a commit per milestone.
3. Obtain Meshy API key from the owner when reaching manual end-to-end testing (backend `.env` only; never committed).

## Key Engineering Decisions

- Single FastAPI process + SQLite file + local `data/models/` folder; no S3/Redis/Celery/queues/cloud services. Zero deployment or maintenance cost.
- Async tracking via in-process asyncio watcher tasks polling Meshy (~5s), with startup reconciliation from the DB after restarts; frontend polls our backend (~3s).
- One application-level generation row wraps both Meshy tasks (`preview_task_id`, `refine_task_id`); refine is strictly user-initiated.
- Generated GLBs/thumbnails must be downloaded locally: Meshy retains API assets max 3 days and its URLs expire, so metadata-only storage would break generation history.
- Lowest-cost model settings: `meshy-6-lite` preview, refine inherits model, `enable_pbr: false`, 2k textures, GLB-only output.
- Frontend: React + Vite + TypeScript + React Three Fiber.
- Meshy client is dependency-injected; automated tests mock it (no real credits consumed).
- Tests use a temporary SQLite per test via dependency override — never the production `data/app.db`.
- Reviewer flow: clone from GitHub (no secrets/models in repo), fill `backend/.env` with Meshy's test-mode key (free, fixed sample model) or the privately shared real key. No code changes needed for either mode.

## Validation

- `pytest` in `backend/`: 1 test passing (`test_health_ok`). Dependencies install cleanly into `backend/.venv` from pinned `requirements.txt` (Python 3.13).
- Verified `.env`, `data/`, and `.venv/` are git-ignored.
- Broader testing strategy defined in `PLAN.md`: fake Meshy client for lifecycle tests; `respx` for HTTP-level client tests.

## Known Issues / Risks

- Meshy 3-day asset retention: a generation whose backend was offline for >3 days after task completion could lose its model file (download window missed). Mitigation: watcher downloads immediately on success; reconciliation on startup.
- Meshy URL/schema details (e.g., exact test-mode behavior) to be verified against the live API during M3/M4.
- Single-process design means in-flight watcher state is memory-held between DB writes; acceptable given startup reconciliation, but a crash mid-download requires re-fetching from Meshy (fine within retention window).
