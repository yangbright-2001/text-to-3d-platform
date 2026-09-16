# Frontend

React + Vite + TypeScript app with a React Three Fiber 3D viewer.

For the full project (backend + API key + both terminals), start from
the root [`README.md`](../README.md). This file is only the frontend
piece.

## Requirements

Node 20+ (developed on Node 24).

## Run

```bash
cd frontend
npm install
npm run dev
# open http://localhost:5173
```

The dev server proxies `/api` and `/files` to `http://127.0.0.1:8000`
(see `vite.config.ts`). The backend must be running on port 8000 for
prompt submission, history, and models served from `data/models/`.

To point the viewer at a backend-served GLB without going through
history:

```
http://localhost:5173/?url=/files/<generation_id>/preview.glb
```

## Build

```bash
npm run build
```

Runs the TypeScript compiler then Vite's production build. Output lands
in `dist/` (gitignored).

## Sample model attribution

`public/sample.glb` is the "Box" sample from
[KhronosGroup/glTF-Sample-Assets](https://github.com/KhronosGroup/glTF-Sample-Assets),
released under CC-BY 4.0.
