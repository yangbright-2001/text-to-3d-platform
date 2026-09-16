import { Component, ReactNode, Suspense } from 'react'
import { Canvas } from '@react-three/fiber'
import { Html, OrbitControls, Stage, useGLTF } from '@react-three/drei'

/**
 * Loads and renders a GLB from `url`.
 *
 * `useGLTF` suspends until the model is fetched + parsed, so this component
 * must live inside a `<Suspense>` boundary (see the parent below). Drei's
 * `<Stage>` handles centering, framing, and neutral lighting automatically.
 */
function GLBModel({ url }: { url: string }) {
  const { scene } = useGLTF(url)
  // `primitive` mounts an existing Three.js object into the R3F scene graph
  // without cloning — we want the GLTF hierarchy exactly as authored.
  return <primitive object={scene} />
}

/**
 * Catches `useGLTF` / R3F failures so a missing or corrupt file shows a
 * message instead of an empty canvas (M10). Remount with ``key={url}`` when
 * the generation swaps preview → refine.
 */
class ViewerErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="viewer-error" role="alert">
          Could not load this 3D model. The file may be missing or damaged.
        </div>
      )
    }
    return this.props.children
  }
}

function LoadingFallback() {
  return (
    <Html center>
      <div className="viewer-loading">Loading model…</div>
    </Html>
  )
}

/**
 * Full-viewport R3F canvas with orbit controls, a loading overlay, and an
 * error boundary so a bad GLB does not blank the page.
 */
export default function ModelViewer({ url }: { url: string }) {
  return (
    <ViewerErrorBoundary key={url}>
      <Canvas
        // A soft off-black background reads well against the dark app chrome.
        style={{ background: '#1a1a1a' }}
        camera={{ position: [3, 2, 3], fov: 45 }}
      >
        <Suspense fallback={<LoadingFallback />}>
          <Stage adjustCamera intensity={0.6} environment="city">
            <GLBModel url={url} />
          </Stage>
        </Suspense>
        <OrbitControls makeDefault enableDamping />
      </Canvas>
    </ViewerErrorBoundary>
  )
}
