# Progress

## Current Status

M1–M9 complete. The full user story now works end-to-end and the app has a browsable history: submit a prompt → watch preview progress → view the untextured model → click "Refine with textures" → watch refine progress → view the textured model. A **generation history** page (linked as "Generation history →" from the home page; "← Back to generation history" from a viewer) lists every past generation with its thumbnail and current status; clicking a card reopens it in the viewer via `?id=<uuid>`. Both preview and refine stages remain tracked independently on one row, and a failed refine still keeps the preview viewable.

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
- **M9 — Task Tracker page**:
  - Frontend-only build: the backend's `GET /api/generations` (M5, newest-first with `/files/...` URLs) already returned everything the tracker needs.
  - `api.ts` gets `listGenerations()`; new `src/TaskTracker.tsx` renders a responsive card grid (`repeat(auto-fill, minmax(220px, 1fr))`) with thumbnail (or a status-colored placeholder for rows without one). Caption is always three left-aligned lines (prompt, status pill, Pacific timestamp such as `Sep 16, 2026, 2:24 AM PDT`) so every card in a row has the same height. Naive backend ISO strings are treated as UTC so SQLite's missing `Z` doesn't display UTC hours as local. Cards use `role="button"` (native `<button>` + `overflow:hidden` collapses to line-height in Chromium).
  - Auto-refresh: the tracker polls the list every 3s while any row is non-terminal, and cleanly stops once every row settles (effect keyed on `anyInFlight`). In-flight cards show live percent on the status line (`Generating preview · 42%`). A manual "Refresh" button is always available; refresh failures show a banner while leaving the last-known list rendered.
  - `App.tsx` gains a `?view=tracker` mode with precedence `?url=` > `?id=` > `?view=tracker` > form. The **"Text to 3D"** title is a home link on every page. The home page's right-aligned **"Generation history"** control is a secondary button (larger than the old text link). On the viewer, **"Generation history"** (secondary) and **"Start a new prompt"** (primary blue) sit on the left of the status bar. Clicking a card sets `?id=<uuid>` (clearing `view` first) so the viewer takes over.
  - Styles: new `.task-tracker*` block in `styles.css` (grid, card, thumb, placeholder, focus outline). Reused existing `.status-*` pill classes so the tracker and `GenerationView` share status colouring — one source of truth for status vocabulary.
- Non-code: architecture plan in `PLAN.md`; workflow rules in `.cursor/rules/project.mdc`.

## Current Feature

- None in progress. M9 done and validated; awaiting go-ahead for **M10 — Robustness and polish**.

## Next Steps

1. M10: startup reconciliation for in-flight rows (re-spawn watchers on boot for any `*_PENDING` / `*_IN_PROGRESS` row — endpoint code already commits well-defined pending states specifically for this handoff), UI failure-state polish (R3F error boundary, tracker-side visibility of failure reasons), README finalization with trade-offs and test-mode instructions.

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
- Current generation id lives in the URL as `?id=<uuid>` (via `history.pushState`), giving cheap reload-survival and browser-back-to-form without introducing localStorage. M9 layered a `?view=tracker` mode alongside it rather than a full router, keeping the URL-driven navigation model uniform.
- Returning from the viewer to history is a back-action, so it lives on the left (`← Back to generation history`). The home-page header keeps a right-aligned noun phrase (`Generation history →`) because that link is going *to* history, not returning from it.
- Tracker timestamps are always formatted in `America/Los_Angeles` (PDT/PST) rather than the browser locale, so two reviewers in different timezones see the same wall clock. Minutes are kept so same-hour submits stay distinguishable.
- M9 tracker auto-refresh keys the polling effect on `anyInFlight` (derived from `rows.some(!isTerminal)`) so an idle history page stops polling automatically once every row settles — same "stop when there's nothing to see" contract used by `GenerationView`.
- Frontend `humanize(status)` is duplicated between `GenerationView` and `TaskTracker` deliberately: three lines of `switch` don't justify a cross-component dependency, and the two views may want to diverge later (e.g., "just now" for freshly created rows on the tracker).
- No frontend unit tests yet — logic is small and manually verified against the real backend with Meshy's test-mode key. Reconsider once hooks/state get more complex.
- Meshy client is dependency-injected; automated tests mock it (no real credits consumed).
- Tests use a temporary SQLite per test via dependency override — never the production `data/app.db`.
- Reviewer flow: clone from GitHub (no secrets/models in repo), fill `backend/.env` with Meshy's test-mode key (free, fixed sample model) or the privately shared real key. No code changes needed for either mode.

## Validation

- `pytest` in `backend/`: **38 tests passing** — 1 health + 5 model + 7 Meshy client + 9 watcher (5 preview + 4 refine) + 13 generation-endpoint (M4/M5 read/write + 4 refine) + 3 file-serving. M9 introduced no backend changes so the suite is unchanged.
- `npm run build` in `frontend/`: passes after M9 (`tsc -b && vite build`) — TypeScript strict-mode clean; production bundle ~1.13 MB / ~317 KB gzipped (essentially unchanged from M8, since three.js + drei still dominate).
- Manual live smoke tests (M5–M7) with real Meshy key: preview → download → viewer path verified against real Meshy. M8 + M9 pending manual verification with the real key (see checklist below).
- Zero real Meshy calls in the automated suite (unit: `respx`; integration: `FakeMeshyClient`).
- Verified `.env`, `data/`, `.venv/`, `node_modules/`, `dist/`, and TypeScript build-info files are git-ignored.

## Known Issues / Risks

- Meshy 3-day asset retention: a generation whose backend was offline for >3 days after task completion could lose its model file. Mitigation: watcher downloads immediately on success; reconciliation is the M10 milestone.
- Refine is one-shot: `REFINE_FAILED` is terminal per the state machine. A user who wants to retry must generate a new preview. Matches PLAN's "task deletion/cancellation is out of scope".
- No error boundary around the R3F canvas: if `useGLTF` fails to load, the canvas stays empty but the status bar still communicates what's happening. Proper viewer error UX is M10 polish.
- Single-process design means in-flight watcher state is memory-held between DB writes; acceptable given planned startup reconciliation (M10). A crash mid-download requires re-fetching from Meshy (fine within retention window).
- Frontend bundle size (~1.13 MB before gzip / ~317 KB gzipped) is dominated by three.js + drei. Acceptable for an internal/demo app; code-splitting can be added later if needed.
- The 3s poll cadence + 5s backend Meshy poll mean progress may briefly appear stuck between updates. The progress-bar CSS transition smooths this visually.
- Tracker thumbnails are best-effort: rows without a `thumbnail_url` (in-flight, or `PREVIEW_FAILED` before any image was ever downloaded) show a status-tinted placeholder. Not treated as an error state — the status pill already communicates what's happening.
- Refine needs the original Meshy `preview_task_id` to still exist **on the same Meshy account/key** that created it. Switching from a real key to the dummy test-mode key (or waiting past Meshy's 3-day retention) makes Meshy return `Preview task not found`. The locally downloaded preview GLB stays viewable; this is not an app bug. A new preview under the current key is required to refine.
