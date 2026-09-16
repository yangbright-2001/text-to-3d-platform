# Progress

## Current Status

M1–M8 complete. The full user story now works end-to-end: submit a prompt → watch preview progress → view the untextured model → click "Refine with textures" → watch refine progress → view the textured model. Both stages tracked independently on one row, refine failure keeps preview viewable.

## Completed Features

- **M1 — Project scaffold**: repo layout, FastAPI app with `GET /api/health`, config via pydantic-settings, pinned deps, `.env.example`, root `.gitignore` and `README.md`.
- **M2 — Persistence layer**: SQLAlchemy 2.0 + SQLite; `Generation` model + `GenerationStatus` enum + `can_transition()`; `init_db()` in FastAPI lifespan; in-memory SQLite + `StaticPool` for test isolation.
- **M3 — Meshy client**: `backend/app/meshy.py` — async `MeshyClient`, `MeshyTask`, `MeshyError`; policy constants (`meshy-6-lite`, GLB-only, PBR off, 2k textures). 7 respx-mocked tests.
- **M4 — Preview generation flow**: `POST /api/generations` in `routes.py`; async `watch_preview` in `watcher.py`; shared `MeshyClient`/session factory/background-task registry on `app.state`; `FakeMeshyClient` in `conftest.py`; `GenerationCreate`/`GenerationRead` in `schemas.py` (internal fields hidden); `deps.get_meshy_client`.
- **M5 — Read endpoints and file serving**: `GET /api/generations` (list, newest-first) and `GET /api/generations/{id}` (detail, 404 on missing); `GET /files/{path}` in `main.py` reads from `app.state.models_dir` with path-traversal defense; `GenerationRead.from_generation()` translates DB `_path` columns into public `/files/...` `_url` fields; MIME types registered for `.glb`/`.gltf`.
- **M6 — Frontend scaffold and 3D viewer**: Vite + React + TypeScript + `@react-three/fiber` + `@react-three/drei` (`useGLTF`, `Stage`, `OrbitControls`) inside a `<Suspense>` boundary; `vite.config.ts` proxies `/api` and `/files` to `http://127.0.0.1:8000`; `App.tsx` supports `?url=` debug override with a bundled Khronos Box sample GLB.
- **M7 — Generate flow end-to-end**: `src/api.ts` — typed fetch client + `isTerminal` helper; `src/PromptForm.tsx` — textarea with 800-char cap, disabled-during-submit; `src/GenerationView.tsx` — 3s polling loop with cancel-on-unmount, progress bar, status badge, viewer swap on `PREVIEW_SUCCEEDED`; `src/App.tsx` — query-string router (`?url=` > `?id=` > form) with `history.pushState`.
- **M8 — Explicit refine**:
  - Backend: `POST /api/generations/{id}/refine` in `routes.py` — 404/409/500 guards + REFINE_PENDING first-commit → Meshy call → REFINE_IN_PROGRESS + `_spawn_refine_watcher`. `watcher.py` refactored: `_apply_failure` / `_finalize_failure` now take an explicit `target` status so both stages share failure paths without conditionals; added `watch_refine` + `_load_refine_task_id` / `_apply_refine_snapshot` / `_download_refine_assets` as structural twins of the preview versions. Refine writes `refine.glb` alongside `preview.glb` under the same `<gen_id>/` directory and overwrites `thumbnail.png` with the textured version when Meshy returns one. `REFINE_MESHY_PARAMS` recorded additively under `meshy_params["refine"]` so history stays self-describing without breaking existing rows.
  - Frontend: `api.ts` gets `refineGeneration(id)`; `GenerationView.tsx` shows a "Refine with textures" button when status is `PREVIEW_SUCCEEDED`, overlays a `RefineOverlay` progress ribbon on the preview viewer while refine runs, and shows a non-fatal red banner on `REFINE_FAILED` while keeping preview interactive (PLAN.md: "A failed refine does not invalidate the viewable preview").
  - Polling lifecycle fix caught during M8 smoke test: the M7 poll effect keyed only on `[id]` never restarted after reaching a terminal state, so clicking refine (which moves the row from `PREVIEW_SUCCEEDED` back to non-terminal) left the progress bar frozen at 0% until manual reload. Fixed by keying the effect on `[id, isPolling]` where `isPolling = !gen || !isTerminal(gen.status)` — turning terminal into non-terminal via user action now naturally re-triggers the effect and resumes polling.
- Non-code: architecture plan in `PLAN.md`; workflow rules in `.cursor/rules/project.mdc`.

## Current Feature

- None in progress. M8 done and validated; awaiting go-ahead for **M9 — Task Tracker page**.

## Next Steps

1. M9: Task Tracker page — list newest-first with thumbnail + timestamp + status pill; click a row to load its `?id=` view. All backend endpoints already ship what's needed (`GET /api/generations` with `/files/...` URLs).
2. M10: startup reconciliation for in-flight rows, UI failure-state polish, README finalization with trade-offs and test-mode instructions.

## Key Engineering Decisions

- Single FastAPI process + SQLite file + local `data/models/` folder; no S3/Redis/Celery/queues/cloud services. Zero deployment or maintenance cost.
- Async tracking via in-process asyncio watcher tasks polling Meshy (~5s); frontend polls our backend at ~3s. Backend is the source of truth so users can close and reopen the page.
- One application-level generation row wraps both Meshy tasks (`preview_task_id`, `refine_task_id`); refine is strictly user-initiated.
- Refine watcher / endpoint mirror preview instead of unifying under one abstraction — the shapes are truly identical but keeping two named entry points gives clearer log messages, cleaner tests, and room to diverge later. Only the failure helpers (`_apply_failure` / `_finalize_failure`) are shared, and they take the target status explicitly so no code has to infer "which stage am I in" from the row.
- Refine endpoint follows the same `PENDING → Meshy call → IN_PROGRESS` two-step commit as preview so M10 startup reconciliation has a well-defined intermediate state to pick up from.
- Refine failure keeps `preview_model_path` + `preview_progress` untouched — preview stays viewable. Refine success overwrites `thumbnail_path` because the textured render is a better tracker preview than the untextured one.
- `meshy_params` grows an additive `"refine"` sub-key rather than being reshaped, so existing rows written by M4 remain forward-compatible without a data migration.
- Frontend `GenerationView` overlays refine progress on top of the still-viewable preview instead of replacing it — keeps the user oriented and matches the "refine improves the preview" mental model.
- Generated GLBs/thumbnails must be downloaded locally: Meshy retains API assets max 3 days and its URLs expire, so metadata-only storage would break generation history.
- Lowest-cost model settings: `meshy-6-lite` preview, refine inherits model, `enable_pbr: false`, 2k textures, GLB-only output.
- Frontend: React 18 + Vite 5 + TypeScript 5 (strict) + React Three Fiber 8 + drei 9 + three 0.169; pinned exact versions for reproducible reviewer installs.
- Vite dev-server proxies `/api` and `/files` to the FastAPI backend so no CORS config is needed. Same-origin in prod once the SPA is served alongside the API.
- Frontend types for the generations API are hand-mirrored from `schemas.py` in `frontend/src/api.ts`. Deliberately not using OpenAPI codegen.
- Terminal-state detection uses a suffix check (`_SUCCEEDED` / `_FAILED`). During M8 we learned this handles the *middle* of a refine (REFINE_IN_PROGRESS keeps polling naturally) but does NOT handle the *restart* — the poll effect had to be re-keyed on `[id, isPolling]` so user actions that move a terminal row back to non-terminal (i.e., clicking refine on a PREVIEW_SUCCEEDED row) restart the loop.
- Current generation id lives in the URL as `?id=<uuid>` (via `history.pushState`), giving cheap reload-survival and browser-back-to-form without introducing localStorage.
- No frontend unit tests yet — logic is small and manually verified against the real backend with Meshy's test-mode key. Reconsider once hooks/state get more complex.
- Meshy client is dependency-injected; automated tests mock it (no real credits consumed).
- Tests use a temporary SQLite per test via dependency override — never the production `data/app.db`.
- Reviewer flow: clone from GitHub (no secrets/models in repo), fill `backend/.env` with Meshy's test-mode key (free, fixed sample model) or the privately shared real key. No code changes needed for either mode.

## Validation

- `pytest` in `backend/`: **38 tests passing** — 1 health + 5 model + 7 Meshy client + 9 watcher (5 preview + 4 refine) + 13 generation-endpoint (M4/M5 read/write + 4 refine) + 3 file-serving.
- `npm run build` in `frontend/`: passes (`tsc -b && vite build`) — TypeScript strict-mode clean; production bundle ~1.1 MB / ~317 KB gzipped.
- Manual live smoke tests (M5–M7) with real Meshy key: preview → download → viewer path verified against real Meshy. M8 pending manual verification with real key (see checklist below).
- Zero real Meshy calls in the automated suite (unit: `respx`; integration: `FakeMeshyClient`).
- Verified `.env`, `data/`, `.venv/`, `node_modules/`, `dist/`, and TypeScript build-info files are git-ignored.

## Known Issues / Risks

- Meshy 3-day asset retention: a generation whose backend was offline for >3 days after task completion could lose its model file. Mitigation: watcher downloads immediately on success; reconciliation is the M10 milestone.
- Refine is one-shot: `REFINE_FAILED` is terminal per the state machine. A user who wants to retry must generate a new preview. Matches PLAN's "task deletion/cancellation is out of scope".
- No error boundary around the R3F canvas: if `useGLTF` fails to load, the canvas stays empty but the status bar still communicates what's happening. Proper viewer error UX is M10 polish.
- Single-process design means in-flight watcher state is memory-held between DB writes; acceptable given planned startup reconciliation (M10). A crash mid-download requires re-fetching from Meshy (fine within retention window).
- Frontend bundle size (~1.1 MB before gzip / ~317 KB gzipped) is dominated by three.js + drei. Acceptable for an internal/demo app; code-splitting can be added later if needed.
- The 3s poll cadence + 5s backend Meshy poll mean progress may briefly appear stuck between updates. The progress-bar CSS transition smooths this visually.
