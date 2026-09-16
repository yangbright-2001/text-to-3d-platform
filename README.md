# Text-to-3D Web Application

A local web app that turns a text prompt into a 3D model using the
[Meshy Text-to-3D API](https://docs.meshy.ai/en/api/text-to-3d). Submit a
prompt, wait for a **preview** mesh, then optionally **refine** it with
textures. Generations are tracked asynchronously, so you can close the
browser and reopen them later from **Generation history**.

How the project was designed and built (including the AI-assisted
workflow) is in [`AI_WORKFLOW.md`](AI_WORKFLOW.md). Architecture and
milestone status are in [`PLAN.md`](PLAN.md) and [`PROGRESS.md`](PROGRESS.md).

## Tech stack

- Backend: Python 3.11+ / FastAPI, SQLite, local file storage
- Frontend: React + Vite + TypeScript + React Three Fiber

## Project layout

```
backend/        FastAPI app, tests, dependencies
frontend/       React app (Vite + 3D viewer)
data/           SQLite DB + downloaded models (gitignored, created at runtime)
AI_WORKFLOW.md  Design context and AI-assisted workflow
PLAN.md         Architecture summary + milestones
PROGRESS.md     Living status log
```

## How to run

You need **Python 3.11+** (developed on 3.13) and **Node 20+** (developed
on Node 24). Generation also needs a Meshy API key, which you add after
copying the env template (step 1 below).

### 1. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Open **`backend/.env`** and set `MESHY_API_KEY` on the line that currently
reads `MESHY_API_KEY=` (leave `MESHY_API_BASE` as-is).

To run the full app without a personal API key, use Meshy's public
**test-mode** key. It still persists, polls, downloads GLB + thumbnail,
and supports history / viewer / refine, but always returns **the same
sample** model (**a wooden tankard**), regardless of the prompt:

```
MESHY_API_KEY=msy_dummy_api_key_for_test_mode_12345678
```

To generate a model that matches your prompt instead of the sample
tankard, replace the public
**test-mode** key and put your own Meshy API key in the same
`MESHY_API_KEY=` line. Restart uvicorn after any change to `.env`.

Then start the API:

```bash
uvicorn app.main:app --reload
curl http://127.0.0.1:8000/api/health
# {"status":"ok","app":"text-to-3d-backend","meshy_key_configured":"true"}
```

```bash
pytest
```

Automated tests mock Meshy (`respx` + `FakeMeshyClient`) and use a
temporary SQLite per test. They never touch `data/app.db` and never call
the real Meshy API.

### 2. Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Vite proxies `/api` and `/files` to the
backend on port 8000, so keep uvicorn running for generation, history,
and the 3D viewer.

More frontend notes (build, debug `?url=`, sample GLB attribution) are in
[`frontend/README.md`](frontend/README.md).

### 3. Try the app

1. Submit any prompt → a preview mesh appears (the sample tankard in
   test mode).
2. Click **Refine with textures** → the textured model replaces the
   preview.
3. Open **Generation history** → cards with thumbnails; click one to
   reopen it.
4. Optional: stop the backend mid-generation and start it again.
   Progress should resume.

## How it works

- One FastAPI process, one SQLite file (`data/app.db`), and model files
  on local disk (`data/models/`), served at `/files/...`.
- In-process watchers poll Meshy (~5s) and persist progress. On process
  start, any unfinished generation is picked up again. Meshy keeps
  API-generated assets for at most 3 days; if the backend was down
  longer than that after Meshy finished, the download URL is gone and
  that row fails.
- Preview and refine are two Meshy tasks wrapped as one generation.
  Refine starts only when the user clicks the button.
- Preview uses `meshy-6-lite`, GLB only; refine inherits that model with
  `enable_pbr: false` and 2k textures.
