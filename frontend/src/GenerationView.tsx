import { useEffect, useState } from 'react'
import { Generation, GenerationStatus, getGeneration, isTerminal } from './api'
import ModelViewer from './ModelViewer'

/**
 * Backend-poll cadence for a running generation.
 *
 * Chosen to match ``PLAN.md``'s "~3s frontend poll" figure. The backend
 * watcher polls Meshy at ~5s, so ~3s here means the UI sees each backend
 * update within one poll of it landing in SQLite — good enough for a
 * progress bar without hammering FastAPI.
 */
const POLL_INTERVAL_MS = 3000

interface Props {
  id: string
  /** Return to the prompt form. Wired to the "← New prompt" button. */
  onReset: () => void
}

/**
 * Polls a single generation until it terminates, then either shows the
 * viewer (on success) or a failure panel (on error).
 *
 * The polling loop lives inside a ``useEffect`` keyed on ``id`` so switching
 * generations (or unmounting) reliably tears down the pending timer.
 */
export default function GenerationView({ id, onReset }: Props) {
  const [gen, setGen] = useState<Generation | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // ``cancelled`` guards against a late tick calling ``setState`` after the
    // effect has been torn down — either due to unmount or an ``id`` change.
    let cancelled = false
    let timeoutId: number | undefined

    async function tick() {
      try {
        const next = await getGeneration(id)
        if (cancelled) return
        setGen(next)
        // A successful poll clears any transient error banner from an
        // earlier failed attempt.
        setError(null)
        // Only schedule another tick if the row can still change. Once the
        // status is terminal, this component stops touching the network.
        if (!isTerminal(next.status)) {
          timeoutId = window.setTimeout(tick, POLL_INTERVAL_MS)
        }
      } catch (err) {
        if (cancelled) return
        // Keep retrying: the backend watcher may recover, or the user may
        // reconnect. The banner tells them we're not just silently stuck.
        setError(err instanceof Error ? err.message : 'Failed to load status')
        timeoutId = window.setTimeout(tick, POLL_INTERVAL_MS)
      }
    }

    // Fire the first poll immediately so we don't wait 3s to show anything.
    tick()

    return () => {
      cancelled = true
      if (timeoutId !== undefined) window.clearTimeout(timeoutId)
    }
  }, [id])

  // First render, before the initial poll resolves.
  if (!gen) {
    return (
      <div className="progress-panel">
        {error ? (
          <div className="error">Failed to load generation: {error}</div>
        ) : (
          <div className="progress-label">Loading…</div>
        )}
        <button className="link-button" onClick={onReset}>← New prompt</button>
      </div>
    )
  }

  // M7 scope: only the preview stage is user-triggerable, so we only render
  // preview outcomes here. M8 will branch on REFINE_* states as well.
  const previewSucceeded = gen.status === 'PREVIEW_SUCCEEDED'
  const previewFailed = gen.status === 'PREVIEW_FAILED'

  return (
    <div className="generation-view">
      <div className="status-bar">
        <button className="link-button" onClick={onReset}>← New prompt</button>
        <span className="prompt-echo">"{gen.prompt}"</span>
        <StatusBadge status={gen.status} />
      </div>

      {previewSucceeded && gen.preview_model_url ? (
        <div className="viewer">
          <ModelViewer url={gen.preview_model_url} />
        </div>
      ) : previewFailed ? (
        <div className="failure-panel">
          <h3>Generation failed</h3>
          <p>{gen.error ?? 'Unknown error'}</p>
          <button onClick={onReset}>Try another prompt</button>
        </div>
      ) : (
        <ProgressPanel gen={gen} error={error} />
      )}
    </div>
  )
}

/** Small colored pill next to the prompt echo. Class names key off the
 *  lowercased status so `styles.css` can theme per state. */
function StatusBadge({ status }: { status: GenerationStatus }) {
  return (
    <span className={`status status-${status.toLowerCase()}`}>
      {humanize(status)}
    </span>
  )
}

/** Map raw enum values to short, human-friendly labels. Exhaustive so the
 *  TypeScript compiler will flag any new backend status we forget to translate. */
function humanize(status: GenerationStatus): string {
  switch (status) {
    case 'PREVIEW_PENDING':
      return 'Queued'
    case 'PREVIEW_IN_PROGRESS':
      return 'Generating preview'
    case 'PREVIEW_SUCCEEDED':
      return 'Preview ready'
    case 'PREVIEW_FAILED':
      return 'Preview failed'
    case 'REFINE_PENDING':
      return 'Refine queued'
    case 'REFINE_IN_PROGRESS':
      return 'Refining textures'
    case 'REFINE_SUCCEEDED':
      return 'Refined'
    case 'REFINE_FAILED':
      return 'Refine failed'
  }
}

function ProgressPanel({
  gen,
  error,
}: {
  gen: Generation
  error: string | null
}) {
  // Use the refine progress once we've moved past preview — makes the bar
  // meaningful even for M8 flows that reuse this component.
  const isRefine = gen.status.startsWith('REFINE_')
  const progress = isRefine ? gen.refine_progress : gen.preview_progress
  return (
    <div className="progress-panel">
      <div className="progress-label">
        {humanize(gen.status)} — {progress}%
      </div>
      <div className="progress-bar" role="progressbar" aria-valuenow={progress}>
        <div className="progress-bar-fill" style={{ width: `${progress}%` }} />
      </div>
      {error && (
        <div className="muted">Reconnecting… ({error})</div>
      )}
    </div>
  )
}
