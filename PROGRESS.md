# Progress

## Current Status

M1–M6 complete. Backend exposes the full read/write surface (submit prompt, poll one row, list history, serve GLB/thumbnail files); frontend now has a Vite + React + TypeScript scaffold with a React Three Fiber viewer that renders a bundled sample GLB. Backend manually verified against real Meshy (test-mode key) end-to-end; frontend verified via production build.

## Completed Features

- **M1 — Project scaffold**: repo layout, FastAPI app with `GET /api/health`, config via pydantic-settings, pinned deps, `.env.example`, root `.gitignore` and `README.md`.
- **M2 — Persistence layer**: SQLAlchemy 2.0 + SQLite; `Generation` model + `GenerationStatus` enum + `can_transition()`; `init_db()` in FastAPI lifespan; in-memory SQLite + `StaticPool` for test isolation.
- **M3 — Meshy client**: `backend/app/meshy.py` — async `MeshyClient`, `MeshyTask`, `MeshyError`; policy constants (`meshy-6-lite`, GLB-only, PBR off, 2k textures). 7 respx-mocked tests.
- **M4 — Preview generation flow**: `POST /api/generations` in `routes.py`; async `watch_preview` in `watcher.py`; shared `MeshyClient`/session factory/background-task registry on `app.state`; `FakeMeshyClient` in `conftest.py`; `GenerationCreate`/`GenerationRead` in `schemas.py` (internal fields hidden); `deps.get_meshy_client`.
- **M5 — Read endpoints and file serving**: `GET /api/generations` (list, newest-first) and `GET /api/generations/{id}` (detail, 404 on missing); `GET /files/{path}` in `main.py` reads from `app.state.models_dir` with path-traversal defense; `GenerationRead.from_generation()` translates DB `_path` columns into public `/files/...` `_url` fields (raw paths never leak); MIME types registered for `.glb`/`.gltf`.
- **M6 — Frontend scaffold and 3D viewer**: Vite + React + TypeScript project in `frontend/` (pinned versions in `package.json`); `vite.config.ts` proxies `/api` and `/files` to `http://127.0.0.1:8000` in dev; `src/ModelViewer.tsx` uses `@react-three/fiber` + `@react-three/drei` (`useGLTF`, `Stage`, `OrbitControls`) inside a `<Suspense>` boundary; `src/App.tsx` reads an optional `?url=` query-string override and defaults to a bundled sample GLB (`public/sample.glb`, Khronos Box, ~1.7KB, CC-BY 4.0). Production build (`npm run build`) succeeds; no unit tests — scaffold validated by build check per project rule.
- Non-code: architecture plan in `PLAN.md`; workflow rules in `.cursor/rules/project.mdc`.

## Current Feature

- None in progress. M6 done and validated; awaiting go-ahead for **M7 — Generate flow end-to-end**.

## Next Steps

1. M7: prompt form + status polling wired to `POST /api/generations` and `GET /api/generations/{id}`; swap `ModelViewer` URL to the completed preview when status reaches `PREVIEW_SUCCEEDED` — first end-to-end interactive demo.
2. M8: explicit refine button + refine watcher reuse.
3. Continue milestone by milestone (M9–M10) per `PLAN.md`.

## Key Engineering Decisions

- Single FastAPI process + SQLite file + local `data/models/` folder; no S3/Redis/Celery/queues/cloud services. Zero deployment or maintenance cost.
- Async tracking via in-process asyncio watcher tasks polling Meshy (~5s), with startup reconciliation from the DB after restarts (M10); frontend polls our backend (~3s, added M7).
- One application-level generation row wraps both Meshy tasks (`preview_task_id`, `refine_task_id`); refine is strictly user-initiated.
- Generated GLBs/thumbnails must be downloaded locally: Meshy retains API assets max 3 days and its URLs expire, so metadata-only storage would break generation history.
- Lowest-cost model settings: `meshy-6-lite` preview, refine inherits model, `enable_pbr: false`, 2k textures, GLB-only output.
- Frontend: React 18 + Vite 5 + TypeScript 5 + React Three Fiber 8 + drei 9 + three 0.169; pinned exact versions to keep reviewer installs reproducible.
- Vite dev-server proxies `/api` and `/files` to the FastAPI backend so no CORS config is needed. Same-origin in prod once the SPA is served alongside the API.
- Viewer accepts a `?url=` override from the start so M6 can be pointed at real backend-served models without any code change — de-risks the M7 wiring.
- Meshy client is dependency-injected; automated tests mock it (no real credits consumed).
- Tests use a temporary SQLite per test via dependency override — never the production `data/app.db`.
- Reviewer flow: clone from GitHub (no secrets/models in repo), fill `backend/.env` with Meshy's test-mode key (free, fixed sample model) or the privately shared real key. No code changes needed for either mode.

## Validation

- `pytest` in `backend/`: **30 tests passing** — 1 health + 5 model + 7 Meshy client + 5 watcher + 9 generation-endpoint (M4 + M5 list/detail/URL-fields/404/null-URL) + 3 file-serving (bytes served, 404, path-traversal blocked).
- `npm run build` in `frontend/`: succeeds (`tsc -b && vite build`) — TypeScript strict-mode clean, production bundle emitted to `frontend/dist/`. Bundle size warning is expected for R3F + three.js and left as-is for the scaffold.
- Manual live smoke test with Meshy test-mode key (M5): `POST /api/generations` → watcher → downloaded a real 720KB glTF v2 GLB + 512×512 PNG thumbnail; `GET /api/generations` and `GET /api/generations/{id}` return the row with `/files/...` URLs (no `_path` or `preview_task_id` fields leak); `GET /files/<id>/preview.glb` returns 200 with `Content-Type: model/gltf-binary` and the exact bytes.
- Zero real Meshy calls in the automated suite (unit: `respx`; integration: `FakeMeshyClient`).
- Verified `.env`, `data/`, `.venv/`, `node_modules/`, `dist/`, and TypeScript build-info files are git-ignored.

## Known Issues / Risks

- Meshy 3-day asset retention: a generation whose backend was offline for >3 days after task completion could lose its model file (download window missed). Mitigation: watcher downloads immediately on success; reconciliation on startup (M10).
- Meshy URL/schema details (e.g., exact test-mode behavior) to be verified against the live API during M3/M4 — done in M5 manual smoke test.
- Single-process design means in-flight watcher state is memory-held between DB writes; acceptable given startup reconciliation, but a crash mid-download requires re-fetching from Meshy (fine within retention window).
- Frontend bundle size (~1.1 MB before gzip / 315 KB gzipped) is dominated by three.js + drei. Acceptable for an internal/demo app; code-splitting can be added later if needed.
