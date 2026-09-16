# Text-to-3D Web Application

A small web app that turns a text prompt into a 3D model using the Meshy
Text-to-3D API. A user submits a prompt, the backend generates a low-cost
**preview** mesh, and the user can then explicitly **refine** it with textures.
Generations are tracked asynchronously so users can leave and return to a Task
Tracker page.

See [`PLAN.md`](PLAN.md) for the architecture and milestone roadmap, and
[`PROGRESS.md`](PROGRESS.md) for current status.

## Tech stack

- Backend: Python + FastAPI, SQLite, local file storage (no cloud services)
- Frontend: React + Vite + TypeScript + React Three Fiber

## Project layout

```
backend/     FastAPI app, tests, dependencies
frontend/    React app (Vite + R3F viewer)
data/        SQLite DB + downloaded models (gitignored, created at runtime)
PLAN.md      Architecture summary + milestones
PROGRESS.md  Living status log
```

## Backend setup

Requires Python 3.11+ (developed on 3.13).

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# then edit .env and set MESHY_API_KEY when you have it
```

### Run the backend

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload
```

Verify it is up:

```bash
curl http://127.0.0.1:8000/api/health
# {"status":"ok","app":"text-to-3d-backend","meshy_key_configured":"false"}
```

### Run the tests

```bash
cd backend
source .venv/bin/activate
pytest
```

## Frontend setup

Requires Node 20+ (developed on Node 24). See [`frontend/README.md`](frontend/README.md) for details.

```bash
cd frontend
npm install
npm run dev
# open http://localhost:5173
```

The dev server proxies `/api` and `/files` to the backend on port 8000, so run
both in separate terminals for the full experience. The default view renders
a bundled sample GLB and needs no backend.

## Notes

- The Meshy API key is backend-only and is never sent to the frontend. Never
  commit `.env`.
- Automated tests mock Meshy and never consume real API credits.
