# Text-to-3D Web Application

A small web app that turns a text prompt into a 3D model using the Meshy
Text-to-3D API. A user submits a prompt, the backend generates a low-cost
**preview** mesh, and the user can then explicitly **refine** it with textures.
Generations are tracked asynchronously so you can close the browser and come
back later via the Generation history page.

See [`PLAN.md`](PLAN.md) for the architecture and milestone roadmap, and
[`PROGRESS.md`](PROGRESS.md) for current status.

## Tech stack

- Backend: Python 3.11+ / FastAPI, SQLite, local file storage (no cloud services)
- Frontend: React + Vite + TypeScript + React Three Fiber

## Project layout

```
backend/     FastAPI app, tests, dependencies
frontend/    React app (Vite + R3F viewer)
data/        SQLite DB + downloaded models (gitignored, created at runtime)
PLAN.md      Architecture summary + milestones
PROGRESS.md  Living status log
```

## Reviewer demo (zero Meshy credits)

Reviewers **do** need an API key in `.env`, but it does not have to be a paid
key. Meshy ships a public **test-mode** key that runs the full app loop
(persist, poll, download GLB + thumbnail, history, viewer, refine) and always
returns the same sample model (a wooden barrel) regardless of the prompt.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Set this in `backend/.env` (not a secret; it consumes no credits):

```
MESHY_API_KEY=msy_dummy_api_key_for_test_mode_12345678
```

Then two terminals:

```bash
# terminal 1 — API on http://127.0.0.1:8000
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload

# terminal 2 — UI on http://localhost:5173
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and:

1. Submit any prompt → a preview mesh appears (the sample barrel in test mode).
2. Click **Refine with textures** → the textured model replaces the preview.
3. Open **Generation history** → cards with thumbnails; click one to reopen it.
4. Optional: stop the backend mid-generation and start it again. Progress
   should resume (startup reconciliation).
5. `cd backend && source .venv/bin/activate && pytest` — 0 real Meshy credits.

A real Meshy key (shared privately, never committed) produces prompt-accurate
models and spends subscription credits. No code change is required to switch
keys: edit `.env` and restart uvicorn.

The Meshy API key is **backend-only**. Never commit `.env`.

## Backend setup (detail)

Requires Python 3.11+ (developed on 3.13).

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# then set MESHY_API_KEY (test-mode or real)
```

```bash
uvicorn app.main:app --reload
curl http://127.0.0.1:8000/api/health
# {"status":"ok","app":"text-to-3d-backend","meshy_key_configured":"true"}
```

```bash
pytest
```

Automated tests mock Meshy (`respx` + `FakeMeshyClient`) and use a temporary
SQLite per test. They never touch `data/app.db` and never consume credits.

## Frontend setup (detail)

Requires Node 20+ (developed on Node 24). See [`frontend/README.md`](frontend/README.md).

```bash
cd frontend
npm install
npm run dev
```

Vite proxies `/api` and `/files` to the backend on port 8000.

## Architecture trade-offs

Chosen so the demo has **no extra hosting, database, queue, or object-storage
cost**:

- **One FastAPI process + one SQLite file (`data/app.db`)**. No Postgres,
  Redis, Celery, or message queue. Fine for a single-user demo; not for
  multi-process production.
- **Models live on local disk (`data/models/`)**, served by FastAPI at
  `/files/...`. Meshy keeps API assets for at most 3 days and its download
  URLs expire, so storing only Meshy URLs would break history. Reviewers
  generate files on their own machine; nothing is pre-bundled in git.
- **In-process asyncio watchers** poll Meshy (~5s) and persist progress.
  On process start, any non-terminal row is picked up again (reconciliation).
  If the backend was down for more than 3 days after Meshy finished, the
  download URL is gone and that row fails.
- **Preview then explicit refine**. One application-level generation wraps
  two Meshy tasks. Refine never starts by itself.
- **Lowest-cost Meshy settings**: `meshy-6-lite` preview, refine inherits
  the model, `enable_pbr: false`, 2k textures, GLB only.

Out of scope: login, deleting/cancelling tasks, retrying a failed refine
(generate a new preview instead).
