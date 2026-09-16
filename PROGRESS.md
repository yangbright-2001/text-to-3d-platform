# Progress

## Current Status

M1 + M2 + M3 + M4 complete. Backend now accepts `POST /api/generations`, creates the Meshy preview task, spawns an in-process asyncio watcher that polls Meshy, downloads the GLB + thumbnail, and drives the app-level state machine to `PREVIEW_SUCCEEDED`. All tests run against a `FakeMeshyClient` — no real Meshy credits consumed. **The backend's end-to-end preview flow is functional** and can be exercised with curl once a Meshy API key is provided.

## Completed Features

- **M1 — Project scaffold**: repo layout, FastAPI app with `GET /api/health`, config via pydantic-settings, pinned deps, `.env.example`, root `.gitignore` and `README.md`.
- **M2 — Persistence layer**: SQLAlchemy 2.0 + SQLite; `Generation` model + `GenerationStatus` enum + `can_transition()`; `init_db()` in FastAPI lifespan; in-memory SQLite + `StaticPool` for test isolation.
- **M3 — Meshy client**: `backend/app/meshy.py` exposes async `MeshyClient`, `MeshyTask`, `MeshyError`, plus policy constants (`meshy-6-lite`, GLB-only, PBR off, 2k textures). 7 respx-mocked tests.
- **M4 — Preview generation flow**: `POST /api/generations` in `backend/app/routes.py`; async `watch_preview` in `backend/app/watcher.py` (polling + GLB/thumbnail download + state-machine advance + `PREVIEW_FAILED` policies); shared `MeshyClient` + session factory + background-task registry live on `app.state`; `FakeMeshyClient` in `tests/conftest.py`; Pydantic `GenerationCreate`/`GenerationRead` in `schemas.py` (internal fields like `preview_task_id` are NOT exposed on the wire); `deps.get_meshy_client` returns the app-scoped client.
- Non-code: architecture plan in `PLAN.md`; workflow rules in `.cursor/rules/project.mdc`.

## Current Feature

- None in progress. M4 done and validated; awaiting go-ahead for **M5 — Read endpoints and file serving**.

## Next Steps

1. **You can now create a Meshy API key** to manually exercise the backend if you want (via `curl`). Optional — automated tests need no key.
2. M5: `GET /api/generations` list + `GET /api/generations/{id}` detail + static serving of `data/models/` under `/files/...`.
3. Continue milestone by milestone (M6–M10) per `PLAN.md`.

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

- `pytest` in `backend/`: **22 tests passing** — 1 health + 5 model + 7 Meshy client + 5 watcher (full success incl. disk downloads, Meshy FAILED, SUCCEEDED without GLB URL, MeshyError during poll, PENDING→IN_PROGRESS advance) + 4 endpoint (immediate response, end-to-end watcher completion incl. file on disk, Meshy-create-failure recorded as PREVIEW_FAILED, empty prompt 422).
- Zero real Meshy calls anywhere (unit: respx; integration: `FakeMeshyClient`).
- Verified `.env`, `data/`, and `.venv/` are git-ignored; production `data/app.db` untouched by pytest.

## Known Issues / Risks

- Meshy 3-day asset retention: a generation whose backend was offline for >3 days after task completion could lose its model file (download window missed). Mitigation: watcher downloads immediately on success; reconciliation on startup.
- Meshy URL/schema details (e.g., exact test-mode behavior) to be verified against the live API during M3/M4.
- Single-process design means in-flight watcher state is memory-held between DB writes; acceptable given startup reconciliation, but a crash mid-download requires re-fetching from Meshy (fine within retention window).
