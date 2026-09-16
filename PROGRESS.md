# Progress

## Current Status

M1–M10 complete. The full user story works end-to-end (prompt → preview → refine → history). Watchers survive a backend restart: on boot, any in-flight row is reconciled. The viewer shows a loading overlay and a message if a GLB fails to load. Failed history cards show the error text. After a refine, history sorts and timestamps by `updated_at` and cache-busts the thumbnail so the textured PNG and refine time appear at the front. The README documents the dummy test-mode key, reviewer smoke checklist, and architecture trade-offs.

## Completed Features

- **M1 — Project scaffold**: repo layout, FastAPI app with `GET /api/health`, config via pydantic-settings, pinned deps, `.env.example`, root `.gitignore` and `README.md`.
- **M2 — Persistence layer**: SQLAlchemy 2.0 + SQLite; `Generation` model + `GenerationStatus` enum + `can_transition()`; `init_db()` in FastAPI lifespan; in-memory SQLite + `StaticPool` for test isolation.
- **M3 — Meshy client**: `backend/app/meshy.py` — async `MeshyClient`, `MeshyTask`, `MeshyError`; policy constants (`meshy-6-lite`, GLB-only, PBR off, 2k textures). 7 respx-mocked tests.
- **M4 — Preview generation flow**: `POST /api/generations` in `routes.py`; async `watch_preview` in `watcher.py`; shared `MeshyClient`/session factory/background-task registry on `app.state`; `FakeMeshyClient` in `conftest.py`; `GenerationCreate`/`GenerationRead` in `schemas.py` (internal fields hidden); `deps.get_meshy_client`.
- **M5 — Read endpoints and file serving**: `GET /api/generations` (list, most recently updated first) and `GET /api/generations/{id}` (detail, 404 on missing); `GET /files/{path}` in `main.py` reads from `app.state.models_dir` with path-traversal defense; `GenerationRead.from_generation()` translates DB `_path` columns into public `/files/...` `_url` fields; thumbnail URLs include `?v=<updated_at>` so a refine that overwrites `thumbnail.png` is not stuck behind the browser cache; MIME types registered for `.glb`/`.gltf`.
- **M6 — Frontend scaffold and 3D viewer**: Vite + React + TypeScript + `@react-three/fiber` + `@react-three/drei` (`useGLTF`, `Stage`, `OrbitControls`) inside a `<Suspense>` boundary; `vite.config.ts` proxies `/api` and `/files` to `http://127.0.0.1:8000`; `App.tsx` supports `?url=` debug override with a bundled Khronos Box sample GLB.
- **M7 — Generate flow end-to-end**: `src/api.ts` — typed fetch client + `isTerminal` helper; `src/PromptForm.tsx` — textarea with 800-char cap, disabled-during-submit; `src/GenerationView.tsx` — 3s polling loop with cancel-on-unmount, progress bar, status badge, viewer swap on `PREVIEW_SUCCEEDED`; `src/App.tsx` — query-string router (`?url=` > `?id=` > form) with `history.pushState`.
- **M8 — Explicit refine**:
  - Backend: `POST /api/generations/{id}/refine` in `routes.py` — 404/409/500 guards + REFINE_PENDING first-commit → Meshy call → REFINE_IN_PROGRESS + `_spawn_refine_watcher`. `watcher.py` refactored: `_apply_failure` / `_finalize_failure` now take an explicit `target` status so both stages share failure paths without conditionals; added `watch_refine` + `_load_refine_task_id` / `_apply_refine_snapshot` / `_download_refine_assets` as structural twins of the preview versions. Refine writes `refine.glb` alongside `preview.glb` under the same `<gen_id>/` directory and overwrites `thumbnail.png` with the textured version when Meshy returns one. `REFINE_MESHY_PARAMS` recorded additively under `meshy_params["refine"]` so history stays self-describing without breaking existing rows.
  - Frontend: `api.ts` gets `refineGeneration(id)`; `GenerationView.tsx` shows a "Refine with textures" button when status is `PREVIEW_SUCCEEDED`, overlays a `RefineOverlay` progress ribbon on the preview viewer while refine runs, and shows a non-fatal red banner on `REFINE_FAILED` while keeping preview interactive (PLAN.md: "A failed refine does not invalidate the viewable preview").
  - Polling lifecycle fix caught during M8 smoke test: the M7 poll effect keyed only on `[id]` never restarted after reaching a terminal state, so clicking refine (which moves the row from `PREVIEW_SUCCEEDED` back to non-terminal) left the progress bar frozen at 0% until manual reload. Fixed by keying the effect on `[id, isPolling]` where `isPolling = !gen || !isTerminal(gen.status)` — turning terminal into non-terminal via user action now naturally re-triggers the effect and resumes polling.
- **M9 — Task Tracker page**:
  - Frontend-only build: the backend's `GET /api/generations` (M5, newest-first with `/files/...` URLs) already returned everything the tracker needs.
  - `api.ts` gets `listGenerations()`; new `src/TaskTracker.tsx` renders a responsive card grid (`repeat(auto-fill, minmax(220px, 1fr))`) with thumbnail (or a status-colored placeholder for rows without one). Caption is always three left-aligned lines (prompt, status pill, Pacific `updated_at` such as `Sep 16, 2026, 2:24 AM PDT`) so every card in a row has the same height. Naive backend ISO strings are treated as UTC so SQLite's missing `Z` doesn't display UTC hours as local. Cards use `role="button"` (native `<button>` + `overflow:hidden` collapses to line-height in Chromium).
  - Auto-refresh: the tracker polls the list every 3s while any row is non-terminal, and cleanly stops once every row settles (effect keyed on `anyInFlight`). In-flight cards show live percent on the status line (`Generating preview · 42%`). A manual "Refresh" button is always available; refresh failures show a banner while leaving the last-known list rendered.
  - `App.tsx` gains a `?view=tracker` mode with precedence `?url=` > `?id=` > `?view=tracker` > form. The **"Text to 3D"** title is a home link on every page. The home page's right-aligned **"Generation history"** control is a secondary button (larger than the old text link). On the viewer, **"Generation history"** (secondary) and **"Start a new prompt"** (primary blue) sit on the left of the status bar. Clicking a card sets `?id=<uuid>` (clearing `view` first) so the viewer takes over.
  - Styles: new `.task-tracker*` block in `styles.css` (grid, card, thumb, placeholder, focus outline). Reused existing `.status-*` pill classes so the tracker and `GenerationView` share status colouring — one source of truth for status vocabulary.
- **M10 — Robustness and polish**:
  - Backend: `reconcile_in_flight` in `watcher.py` scans non-terminal rows on FastAPI startup and either respawns `watch_preview` / `watch_refine` (when a Meshy task id exists) or marks the row failed (PENDING with no task id — process died before Meshy accepted; we do not retry create, to avoid double-charging). Spawn helpers moved out of `routes.py` so the lifespan and the endpoints share one path. Pytest sets `TEXT3D_SKIP_RECONCILE=1` so TestClient lifespan never scans the developer's `data/app.db`.
  - Frontend: `ModelViewer` wraps the canvas in an error boundary ("Could not load this 3D model") and a Suspense fallback ("Loading model…"). Failed tracker cards show an ellipsized `error` line; the tooltip still has the full prompt + reason. Grid stretch keeps row heights even when a failed card is taller.
  - README: test-mode key, two-terminal reviewer checklist (including restart-mid-run), pytest note, and architecture trade-offs (SQLite, local `data/models/`, in-process watchers, 3-day Meshy retention).
- Non-code: architecture plan in `PLAN.md`; workflow rules in `.cursor/rules/project.mdc`.
- **Post-M10 polish**: header platform name ("Text to 3D") bumped to 28px / weight 800 / white so it reads as the product lockup rather than another header control. Home prompt card is larger (760px, taller textarea), centered in the main pane, then nudged slightly up so it does not sit below visual center. Opening Generation history from a ``?url=`` debug override now replaces the whole query (``?url=`` outranks ``?view=tracker``, so leaving url set looked like a no-op).

## Current Feature

- None in progress. M10 done — this is the last planned milestone.

## Next Steps

- None required by the plan. Optional later: refine retry, delete/cancel, viewer code-splitting.

## Key Engineering Decisions

- Single FastAPI process + SQLite file + local `data/models/` folder; no S3/Redis/Celery/queues/cloud services. Zero deployment or maintenance cost. Meshy Pro's 10 concurrent-task cap is not enforced in-app: a single user would have to keep 10+ generations in flight at once, and Meshy already rejects extras (we persist that as `*_FAILED`). A local queue would add complexity without a real failure mode for this demo.
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
- Current generation id lives in the URL as `?id=<uuid>` (via `history.pushState`), giving cheap reload-survival and browser-back-to-form without introducing localStorage. M9 layered a `?view=tracker` mode alongside it rather than a full router, keeping the URL-driven navigation model uniform.
- Returning from the viewer to history is a back-action, so it lives on the left (`← Back to generation history`). The home-page header keeps a right-aligned noun phrase (`Generation history →`) because that link is going *to* history, not returning from it.
- Tracker timestamps are always formatted in `America/Los_Angeles` (PDT/PST) rather than the browser locale, so two reviewers in different timezones see the same wall clock. Minutes are kept so same-hour submits stay distinguishable. History is ordered and labeled by `updated_at` so refining an older preview moves that card to the front with the refine time. Thumbnail URLs carry `?v=<updated_at>` so the browser does not keep showing the preview PNG after refine overwrites the same path.
- M9 tracker auto-refresh keys the polling effect on `anyInFlight` (derived from `rows.some(!isTerminal)`) so an idle history page stops polling automatically once every row settles — same "stop when there's nothing to see" contract used by `GenerationView`.
- Frontend `humanize(status)` is duplicated between `GenerationView` and `TaskTracker` deliberately: three lines of `switch` don't justify a cross-component dependency, and the two views may want to diverge later (e.g., "just now" for freshly created rows on the tracker).
- No frontend unit tests yet — logic is small and manually verified against the real backend with Meshy's test-mode key. Reconsider once hooks/state get more complex.
- Meshy client is dependency-injected; automated tests mock it (no real credits consumed).
- Tests use a temporary SQLite per test via dependency override — never the production `data/app.db`.
- Startup reconciliation respawns watchers when a Meshy task id is already on the row. A `*_PENDING` row with **no** task id (crash between the first commit and Meshy's response) is marked failed rather than retrying `create_*_task`, which could double-charge if Meshy had accepted. A failed refine still keeps the preview.
- Pytest sets `TEXT3D_SKIP_RECONCILE=1` so FastAPI TestClient lifespan cannot scan the on-disk `data/app.db` or call Meshy. Reconciliation is unit-tested by calling `reconcile_in_flight` against a fake `app.state`.

## Validation

- `pytest` in `backend/`: **43 tests passing** — list order is `updated_at DESC` (a recently refined older row precedes a newer untouched preview); `thumbnail_url` is `/files/.../thumbnail.png?v=<updated_at>`. Zero real Meshy calls.
- `npm run build` in `frontend/`: `tsc -b && vite build`.

## Known Issues / Risks

- Meshy 3-day asset retention: a generation whose backend was offline for >3 days after task completion could lose its model file. Watcher downloads immediately on success; startup reconciliation retries the download if we come back inside the window.
- Refine is one-shot: `REFINE_FAILED` is terminal per the state machine. A user who wants to retry must generate a new preview. Matches PLAN's "task deletion/cancellation is out of scope".
- Single-process design means in-flight watcher state is memory-held between DB writes; startup reconciliation covers process restart.
- Frontend bundle size (~1.13 MB before gzip / ~317 KB gzipped) is dominated by three.js + drei. Acceptable for an internal/demo app; code-splitting can be added later if needed.
- The 3s poll cadence + 5s backend Meshy poll mean progress may briefly appear stuck between updates. The progress-bar CSS transition smooths this visually.
- Tracker thumbnails are best-effort: rows without a `thumbnail_url` (in-flight, or `PREVIEW_FAILED` before any image was ever downloaded) show a status-tinted placeholder. Failed rows also show the `error` string.
- Refine needs the original Meshy `preview_task_id` to still exist **on the same Meshy account/key** that created it. Switching from a real key to the dummy test-mode key (or waiting past Meshy's 3-day retention) makes Meshy return `Preview task not found`. The locally downloaded preview GLB stays viewable; this is not an app bug. A new preview under the current key is required to refine.
