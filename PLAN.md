# Text-to-3D Web Application — Project Plan

## Architecture Summary

Stable, project-wide decisions. These should not change during implementation; anything not listed here is a per-milestone implementation detail.

### System shape

- **Three components, zero external infrastructure**: a React SPA, a single FastAPI process, and a SQLite database file.
- **Backend**: Python 3.12 + FastAPI, single process. Owns all Meshy communication, the task state machine, background progress tracking, persistence, and model file serving.
- **Frontend**: React + Vite + TypeScript, with React Three Fiber (Three.js) for the 3D viewer. Talks only to our backend — it has no knowledge of Meshy.
- **No** S3/object storage services, Redis, Celery, Kafka, message queues, microservices, Docker/Kubernetes, or cloud databases.

### Meshy integration

- All Meshy API calls go through the backend. The API key lives in `backend/.env` (gitignored, with a committed `.env.example`) and is never exposed to the frontend.
- The backend controls all model/cost parameters: preview uses `meshy-6-lite` (lowest-cost non-deprecated standard model) with `target_formats: ["glb"]`; refine inherits the preview's model with `enable_pbr: false` and default 2k textures. All tunable in one config module.
- A single Meshy client module is the only code that knows Meshy's API — everything else depends on its interface, which is what tests mock.
- The subscription allows 10 concurrent Meshy tasks; concurrent generations are supported naturally (one watcher per task) and stay well under this limit, so no queueing logic is needed.

### Application-level task model

- One user generation = one row in a `generations` table, holding both `preview_task_id` and `refine_task_id` internally. Preview and refine are never shown as two separate user-visible tasks.
- Explicit app-level status state machine:
  `PREVIEW_PENDING → PREVIEW_IN_PROGRESS → PREVIEW_SUCCEEDED → (explicit user action) → REFINE_PENDING → REFINE_IN_PROGRESS → REFINE_SUCCEEDED`, with `PREVIEW_FAILED` / `REFINE_FAILED` branches. A failed refine does not invalidate the viewable preview.
- **Refine is never automatic** — it only happens via an explicit user request against a succeeded preview.

### Asynchronous task handling

- Creating a generation spawns an in-process `asyncio` background watcher that polls Meshy's task endpoint (~5s interval), persists progress/status to SQLite on every change, and downloads the GLB + thumbnail on success.
- The backend — not the browser — owns tracking: users can close the page mid-generation and return later.
- **Startup reconciliation**: on boot, watchers are respawned for all non-terminal generations found in the DB. The database is the source of truth for what is in flight; no queue needed.
- The frontend polls our backend (~3s) for status while a task is non-terminal.

### Persistence and model storage

- **SQLite** (single file, `data/app.db`) via SQLAlchemy. Trade-off: no multi-process concurrency or managed backups vs. Postgres — irrelevant for a single-process app, and it costs nothing to deploy or maintain. Schema created on startup; Alembic migrations deliberately skipped for a one-table schema.
- **Generated GLB files and thumbnails are downloaded to a local folder** (`data/models/`, gitignored) and served by FastAPI. This is required, not optional: Meshy retains API-generated assets for a maximum of 3 days and its download URLs are presigned and expire, so storing only Meshy URLs would break the "return later and view history" requirement. Local download also avoids URL-expiry and CORS issues in the browser viewer. No external/paid object storage is involved — models live on the same machine's disk.
- All Meshy metadata (task ids, credits consumed, timestamps, request params) is stored alongside for traceability.

### API surface (backend)

- `POST /api/generations` — submit a prompt, starts preview, returns immediately.
- `GET /api/generations` — list all generations (Task Tracker).
- `GET /api/generations/{id}` — detail; the polling target.
- `POST /api/generations/{id}/refine` — explicit refine of a succeeded preview.
- `GET /files/...` — serves downloaded models/thumbnails. Clients only ever receive our own file URLs, never Meshy URLs.

### Testing

- `pytest` with FastAPI's test client. The Meshy client is dependency-injected, so lifecycle tests use a fake that scripts status sequences (pending → in progress → succeeded/failed) — no real API credits consumed. HTTP-level tests of the real client mock `api.meshy.ai` with `respx`.
- **Test database isolation**: the DB session is dependency-injected; tests override it with a fresh temporary SQLite (in-memory or `tmp_path` file) per test, so automated tests never touch the production `data/app.db`. No extra database infrastructure needed.
- Meshy's documented test-mode API key (`msy_dummy_api_key_for_test_mode_12345678`) enables free manual end-to-end runs: all app logic (persistence, watcher, download to `data/models/`, tracker, viewer) runs for real; Meshy just returns a fixed sample model regardless of prompt, near-instantly. Documented in README for reviewers.

### Local development and reproducibility

- Pinned dependencies (`requirements.txt` / `package-lock.json`), committed `.env.example`, two-command startup (backend dev server + Vite dev server) documented in README. Vite proxies `/api` and `/files` to the backend in dev, so no CORS configuration is needed.
- **External reviewers**: clone from GitHub (repo contains no secrets, no model files — `data/` is gitignored), fill `backend/.env` with either the test-mode key (zero cost) or the real key shared privately. Generated files are downloaded at runtime to the reviewer's own machine; nothing is pre-bundled in the repo.

### Assumptions

- Single user, no authentication; all generations visible in the tracker.
- Task deletion/cancellation is out of scope.

---

## Milestones

One feature at a time; each milestone ends in a working, tested state and its own commit.

- [x] **M1 — Project scaffold**: repo layout (`backend/`, `frontend/` placeholder), FastAPI skeleton with health endpoint, config loading from `.env`, README with setup instructions.
- [x] **M2 — Persistence layer**: SQLite wiring, `Generation` model with the status state machine, first tests.
- [ ] **M3 — Meshy client**: client module wrapping preview/refine/get-task/file-download, with mocked HTTP tests.
- [ ] **M4 — Preview generation flow**: `POST /api/generations`, background watcher, GLB + thumbnail download on success, full lifecycle tests against a fake Meshy client.
- [ ] **M5 — Read endpoints and file serving**: list and detail endpoints, static serving of downloaded models.
- [ ] **M6 — Frontend scaffold and 3D viewer**: Vite + React + R3F app rendering a sample GLB.
- [ ] **M7 — Generate flow end-to-end**: prompt form, status polling, progress display, preview model shown on completion.
- [ ] **M8 — Explicit refine**: refine endpoint and watcher reuse; "Refine with textures" button; textured model replaces preview in the viewer.
- [ ] **M9 — Task Tracker page**: generation history with statuses, thumbnails, and click-through to the viewer.
- [ ] **M10 — Robustness and polish**: startup reconciliation, failure states in the UI, README finalization with trade-offs and test-mode instructions.
