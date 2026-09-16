# Text-to-3D Web Application

A local web app that turns a text prompt into a 3D model using the
[Meshy Text-to-3D API](https://docs.meshy.ai/en/api/text-to-3d). Submit a
prompt, wait for a **preview** mesh, then optionally **refine** it with
textures. Generations are tracked asynchronously, so you can close the
browser and reopen them later from **Generation history**.

More information about how the project was designed and built (including the AI-assisted
workflow) is in `[AI_WORKFLOW.md](AI_WORKFLOW.md)`. Project architecture and
milestone status are in `[PLAN.md](PLAN.md)` and `[PROGRESS.md](PROGRESS.md)`.

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
on Node 24). Backend setup is in steps **§1a–1d** (venv → dependencies → API key →
uvicorn); frontend is steps **§2**.

**For Fresh clone:** `data/` is not in git (`data/app.db` + `data/models/`).  
**Generation history** page starts **empty** — it will not match the sample **Generation history** page screenshots in `[AI_WORKFLOW.md](AI_WORKFLOW.md)` or `doc-image/`. 
Submit a few prompts locally (or run refine) and 3D-asset cards in **Generation history** 
page will appear. To reproduce someone else's filled history, you would 
need their `data/` folder copied onto your machine (not part of the repo).

### 1. Backend

Do **1a** for your OS, then **1b → 1c → 1d** in order (same on every platform).

#### 1a. Create a venv and copy the env template

**macOS / Linux**

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
cp .env.example .env
```

**Windows (Command Prompt)**

```bat
cd backend
python -m venv .venv
.venv\Scripts\activate.bat
copy .env.example .env
```

**Windows (PowerShell)**

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
```

On Windows, if `python` is missing use `py -3 -m venv .venv`. If PowerShell
refuses `Activate.ps1`, use Command Prompt with `activate.bat` instead.

#### 1b. Install dependencies

With the venv still active:

```bash
pip install -r requirements.txt
```

#### 1c. Set the Meshy API key

Edit **`backend/.env`**. On the line `MESHY_API_KEY=`, paste a key (leave
`MESHY_API_BASE` unchanged).

For a full local demo of this platform **without your own Meshy API key**, use the public
**test-mode** key (it will generate the same sample **wooden tankard** output for every prompt; but you can still see the "generation history", viewer, and refine):

```
MESHY_API_KEY=msy_dummy_api_key_for_test_mode_12345678
```

For a model that matches your prompt, replace that value with your own Meshy
API key. Restart the backend after any `.env` change.

#### 1d. Start the Web APP

With the venv still active:

```bash
uvicorn app.main:app --reload
```

Optional sanity check: open http://127.0.0.1:8000/api/health — you should
see `"meshy_key_configured":"true"`. Or run `curl` on macOS/Linux.

#### 1e. (Optional) tests (mock Meshy; never uses `data/app.db`):

```bash
pytest
```

### 2. Frontend

In a **second** terminal (need to open **another** terminal, because we activated the 
backend venv only in terminal 1; frontend needs Node, not Python):

**macOS / Linux / Windows**

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). Vite proxies `/api` and `/files` to the
backend on port 8000, so keep uvicorn running for generation, history,
and the 3D viewer.

More frontend notes (build, debug `?url=`, sample GLB attribution) are in
`[frontend/README.md](frontend/README.md)`.

### 3. Try the app

1. Submit any prompt → a preview mesh appears (the sample tankard in
  test mode).
2. Click **"Refine with textures"** → the textured model replaces the
  preview.
3. Open **"Generation history"** → cards with thumbnails; click one to
  reopen it. (Right after clone this page is empty until you generate
   locally.)
4. Optional: stop the backend mid-generation and start it again.
  Generation progress should resume after backend restarts.



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

