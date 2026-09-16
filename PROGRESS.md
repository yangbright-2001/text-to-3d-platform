# Progress

## Current Status

M1 + M2 + M3 complete. Backend boots with SQLite persistence and a fully-tested Meshy HTTP client (`MeshyClient`, async, `httpx.AsyncClient`-based). Automated tests mock Meshy via `respx` and use isolated in-memory SQLite; no real Meshy credits consumed and the production DB stays untouched.

## Completed Features

- **M1 — Project scaffold**: repo layout (`backend/`, `frontend/` placeholder); FastAPI app with `GET /api/health`; config via pydantic-settings reading `backend/.env`; pinned `requirements.txt`; `.env.example`; root `.gitignore` and `README.md` with setup/run instructions.
- **M2 — Persistence layer**: SQLAlchemy 2.0 + SQLite via `backend/app/db.py`; `Generation` model + `GenerationStatus` enum + `can_transition()` helper in `backend/app/models.py`; FastAPI `lifespan` runs `init_db()` on startup; test fixtures use in-memory SQLite + `StaticPool` for isolation.
- **M3 — Meshy client**: `backend/app/meshy.py` exposes `MeshyClient` (async), `MeshyTask` dataclass, `MeshyError`, plus module-level policy constants (`DEFAULT_PREVIEW_AI_MODEL="meshy-6-lite"`, GLB-only, PBR off, 2k textures). Covers create preview/refine, get task (in-progress/succeeded/failed), streamed file download (auth header omitted for presigned URLs), and error handling. `get_meshy_client()` factory ready for M4 DI wiring.
- Non-code: architecture plan in `PLAN.md`; project workflow rules in `.cursor/rules/project.mdc`.

## Current Feature

- None in progress. M3 done and validated; awaiting go-ahead for **M4 — Preview generation flow**.

## Next Steps

1. M4: `POST /api/generations`, background asyncio watcher, GLB + thumbnail download on success, full lifecycle tests against an injected fake `MeshyClient`.
2. Then proceed milestone by milestone (M5–M10) per `PLAN.md`, one feature at a time with tests and a commit per milestone.
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

- `pytest` in `backend/`: **13 tests passing** — 1 health + 5 model + 7 Meshy client (payloads, task parsing across statuses, 4xx → `MeshyError`, streamed download bytes + no auth header on presigned URLs).
- Manual sanity check: FastAPI lifespan creates `data/app.db` and `data/models/` on startup; automated tests never trigger lifespan and never write to production `data/`.
- Verified `.env`, `data/`, and `.venv/` are git-ignored.
- Zero real Meshy calls in the test suite (all mocked via `respx`).

## Known Issues / Risks

- Meshy 3-day asset retention: a generation whose backend was offline for >3 days after task completion could lose its model file (download window missed). Mitigation: watcher downloads immediately on success; reconciliation on startup.
- Meshy URL/schema details (e.g., exact test-mode behavior) to be verified against the live API during M3/M4.
- Single-process design means in-flight watcher state is memory-held between DB writes; acceptable given startup reconciliation, but a crash mid-download requires re-fetching from Meshy (fine within retention window).
