# Frontend

React + Vite + TypeScript SPA with a React Three Fiber viewer.

Scaffolded in **M6**: renders a bundled sample GLB (`public/sample.glb`, the
Khronos glTF Box sample) to prove the R3F pipeline works. M7–M9 wire the
prompt form, refine button, and generation history. M10 adds a loading
overlay and an error boundary around the viewer.

## Setup

Requires Node 20+ (developed on Node 24).

```bash
cd frontend
npm install
```

## Run the dev server

```bash
npm run dev
# open http://localhost:5173
```

The dev server proxies `/api` and `/files` to `http://127.0.0.1:8000`
(configured in `vite.config.ts`), so the backend must be running on port
8000 for any real generation flow. The default sample GLB is served by
Vite itself and needs no backend.

To point the viewer at a real backend-served model:

```
http://localhost:5173/?url=/files/<generation_id>/preview.glb
```

## Build

```bash
npm run build
```

Runs the TypeScript compiler then Vite's production build. Output lands in
`dist/` (gitignored).

## Sample model attribution

`public/sample.glb` is the "Box" sample from
[KhronosGroup/glTF-Sample-Assets](https://github.com/KhronosGroup/glTF-Sample-Assets),
released under CC-BY 4.0.
