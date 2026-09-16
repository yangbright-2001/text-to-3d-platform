# Progress

## Current Status

M1–M5 complete. The backend now exposes the full read/write surface the frontend will need: submit a prompt, poll one row, list history, and serve the downloaded GLB/thumbnail files back to browsers under `/files/...`. Manually verified against real Meshy (test-mode key) — end-to-end preview flow generates + downloads + serves correctly.

## Completed Features

- **M1 — Project scaffold**: repo layout, FastAPI app with `GET /api/health`, config via pydantic-settings, pinned deps, `.env.example`, root `.gitignore` and `README.md`.
- **M2 — Persistence layer**: SQLAlchemy 2.0 + SQLite; `Generation` model + `GenerationStatus` enum + `can_transition()`; `init_db()` in FastAPI lifespan; in-memory SQLite + `StaticPool` for test isolation.
- **M3 — Meshy client**: `backend/app/meshy.py` — async `MeshyClient`, `MeshyTask`, `MeshyError`; policy constants (`meshy-6-lite`, GLB-only, PBR off, 2k textures). 7 respx-mocked tests.
- **M4 — Preview generation flow**: `POST /api/generations` in `routes.py`; async `watch_preview` in `watcher.py`; shared `MeshyClient`/session factory/background-task registry on `app.state`; `FakeMeshyClient` in `conftest.py`; `GenerationCreate`/`GenerationRead` in `schemas.py` (internal fields hidden); `deps.get_meshy_client`.
- **M5 — Read endpoints and file serving**: `GET /api/generations` (list, newest-first) and `GET /api/generations/{id}` (detail, 404 on missing); `GET /files/{path}` in `main.py` reads from `app.state.models_dir` with path-traversal defense; `GenerationRead.from_generation()` translates DB `_path` columns into public `/files/...` `_url` fields (raw paths never leak); MIME types registered for `.glb`/`.gltf`.
- Non-code: architecture plan in `PLAN.md`; workflow rules in `.cursor/rules/project.mdc`.

## Current Feature

- None in progress. M5 done and validated; awaiting go-ahead for **M6 — Frontend scaffold and 3D viewer**.

## Next Steps

1. M6: Vite + React + TypeScript + React Three Fiber scaffold rendering a sample GLB — first frontend milestone.
2. M7: wire the frontend prompt form + status polling to the backend endpoints M4/M5 shipped — first end-to-end interactive demo.
3. Continue milestone by milestone (M8–M10) per `PLAN.md`.

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

- `pytest` in `backend/`: **30 tests passing** — 1 health + 5 model + 7 Meshy client + 5 watcher + 9 generation-endpoint (M4 + M5 list/detail/URL-fields/404/null-URL) + 3 file-serving (bytes served, 404, path-traversal blocked).
- Manual live smoke test with Meshy test-mode key: `POST /api/generations` → watcher → downloaded a real 720KB glTF v2 GLB + 512×512 PNG thumbnail; `GET /api/generations` and `GET /api/generations/{id}` return the row with `/files/...` URLs (no `_path` or `preview_task_id` fields leak); `GET /files/<id>/preview.glb` returns 200 with `Content-Type: model/gltf-binary` and the exact bytes.
- Zero real Meshy calls in the automated suite (unit: `respx`; integration: `FakeMeshyClient`).
- Verified `.env`, `data/`, and `.venv/` are git-ignored.

## Known Issues / Risks

- Meshy 3-day asset retention: a generation whose backend was offline for >3 days after task completion could lose its model file (download window missed). Mitigation: watcher downloads immediately on success; reconciliation on startup.
- Meshy URL/schema details (e.g., exact test-mode behavior) to be verified against the live API during M3/M4.
- Single-process design means in-flight watcher state is memory-held between DB writes; acceptable given startup reconciliation, but a crash mid-download requires re-fetching from Meshy (fine within retention window).
