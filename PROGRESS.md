# Progress

## Current Status

M1 + M2 complete. Backend boots, creates `data/app.db` and `data/models/` on startup, exposes `/api/health`, and has a persisted `Generation` model with the app-level status state machine. Automated tests use an isolated in-memory SQLite; the production DB is never touched by pytest.

## Completed Features

- **M1 — Project scaffold**: repo layout (`backend/`, `frontend/` placeholder); FastAPI app with `GET /api/health`; config via pydantic-settings reading `backend/.env`; pinned `requirements.txt`; `.env.example`; root `.gitignore` and `README.md` with setup/run instructions.
- **M2 — Persistence layer**: SQLAlchemy 2.0 + SQLite via `backend/app/db.py` (engine, `SessionLocal`, `get_session()` dependency, idempotent `init_db()`); `Generation` model in `backend/app/models.py` with `GenerationStatus` enum and `can_transition()` state-machine helper; FastAPI `lifespan` runs `init_db()` on startup; test fixtures in `backend/tests/conftest.py` use in-memory SQLite + `StaticPool` for isolation.
- Non-code: architecture plan in `PLAN.md`; project workflow rules in `.cursor/rules/project.mdc`.

## Current Feature

- None in progress. M2 done and validated; awaiting go-ahead for **M3 — Meshy client**.

## Next Steps

1. M3: `MeshyClient` wrapping preview/refine/get-task/file-download with httpx; HTTP-level tests using `respx` (no real credits).
2. Then proceed milestone by milestone (M4–M10) per `PLAN.md`, one feature at a time with tests and a commit per milestone.
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

- `pytest` in `backend/`: **6 tests passing** — health endpoint + `Generation` defaults / `updated_at` on-update / JSON round-trip / allowed transitions / rejected transitions.
- Manual sanity check: FastAPI lifespan creates `data/app.db` and `data/models/` on startup; automated tests never trigger lifespan and never write to production `data/`.
- Verified `.env`, `data/`, and `.venv/` are git-ignored.
- Broader testing strategy defined in `PLAN.md`: fake Meshy client for lifecycle tests; `respx` for HTTP-level client tests.

## Known Issues / Risks

- Meshy 3-day asset retention: a generation whose backend was offline for >3 days after task completion could lose its model file (download window missed). Mitigation: watcher downloads immediately on success; reconciliation on startup.
- Meshy URL/schema details (e.g., exact test-mode behavior) to be verified against the live API during M3/M4.
- Single-process design means in-flight watcher state is memory-held between DB writes; acceptable given startup reconciliation, but a crash mid-download requires re-fetching from Meshy (fine within retention window).
