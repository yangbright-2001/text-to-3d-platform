import { Suspense } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls, Stage, useGLTF } from '@react-three/drei'

/**
 * Loads and renders a GLB from `url`.
 *
 * `useGLTF` suspends until the model is fetched + parsed, so this component
 * must live inside a `<Suspense>` boundary (see the parent below). Drei's
 * `<Stage>` handles centering, framing, and neutral lighting automatically —
 * enough for the M6 milestone where the only goal is "does a GLB render".
 */
function GLBModel({ url }: { url: string }) {
  const { scene } = useGLTF(url)
  // `primitive` mounts an existing Three.js object into the R3F scene graph
  // without cloning — we want the GLTF hierarchy exactly as authored.
  return <primitive object={scene} />
}

interface ModelViewerProps {
  url: string
}

/**
 * Full-viewport R3F canvas with orbit controls and a suspense fallback.
 *
 * Kept intentionally simple: no error boundary, no loading spinner beyond a
 * plain text overlay — later milestones can wrap this with better UX once we
 * have real generation flows to react to (M7+).
 */
export default function ModelViewer({ url }: ModelViewerProps) {
  return (
    <Canvas
      // A soft off-black background reads well against the dark app chrome.
      style={{ background: '#1a1a1a' }}
      camera={{ position: [3, 2, 3], fov: 45 }}
    >
      <Suspense fallback={null}>
        {/* Stage auto-frames the model and adds neutral studio lighting. */}
        <Stage adjustCamera intensity={0.6} environment="city">
          <GLBModel url={url} />
        </Stage>
      </Suspense>
      {/* Orbit for user-controlled inspection; damping feels smoother. */}
      <OrbitControls makeDefault enableDamping />
    </Canvas>
  )
}

// Preload hint: not strictly needed for a single default model, but useful
// once M7 starts swapping URLs. Kept commented to avoid firing a request for
// the sample file when the user has already provided `?url=`.
// useGLTF.preload('/sample.glb')
