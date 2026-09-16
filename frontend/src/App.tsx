import { useMemo } from 'react'
import ModelViewer from './ModelViewer'

// Default GLB shipped with the frontend (Khronos "Box" sample, in public/).
// Serves as the M6 smoke test: opening the dev server should show a rendered
// GLB without needing the backend running.
const DEFAULT_MODEL_URL = '/sample.glb'

/**
 * App shell.
 *
 * M6 scope is deliberately narrow: prove the R3F pipeline can load and render
 * a GLB. Later milestones add the prompt form (M7), refine button (M8), and
 * task tracker (M9). Until then, the viewer accepts a `?url=` query-string
 * override so the same build can be pointed at a real backend-served model
 * (e.g. `?url=/files/<gen_id>/preview.glb`) without any code changes.
 */
export default function App() {
  const modelUrl = useMemo(() => {
    // URLSearchParams is safer than manual parsing and encodes correctly.
    const params = new URLSearchParams(window.location.search)
    return params.get('url') || DEFAULT_MODEL_URL
  }, [])

  return (
    <div className="app">
      <header className="app-header">
        <strong>Text to 3D</strong>
        <span className="muted">M6 viewer scaffold — {modelUrl}</span>
      </header>
      <main className="viewer">
        <ModelViewer url={modelUrl} />
      </main>
    </div>
  )
}
