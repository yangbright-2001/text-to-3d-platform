import { useEffect, useState } from 'react'
import {
  Generation,
  GenerationStatus,
  getGeneration,
  isTerminal,
  refineGeneration,
} from './api'
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
 * Polling lifecycle: the effect is keyed on ``[id, isPolling]``, where
 * ``isPolling`` is derived from the current row's status. This gives us a
 * clean restart when the user takes an action that reopens a "terminal"
 * state — most importantly clicking "Refine with textures", which moves
 * the row from ``PREVIEW_SUCCEEDED`` (backend-terminal, no more updates
 * without user input) back to ``REFINE_IN_PROGRESS`` (non-terminal, keep
 * polling). Keying only on ``id`` would leave a stopped poll loop stopped
 * forever after refine, causing the progress bar to sit at 0% until reload.
 */
export default function GenerationView({ id, onReset }: Props) {
  const [gen, setGen] = useState<Generation | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Guards the refine button so a slow POST can't be double-fired.
  const [refining, setRefining] = useState(false)

  // Derived: are we currently in a state whose row can still change without
  // fresh user input? Non-terminal statuses (and the initial "we haven't
  // loaded anything yet" state) get polled; terminal statuses stop.
  const isPolling = !gen || !isTerminal(gen.status)

  useEffect(() => {
    // Skip polling entirely when the row is at rest. When the user later
    // triggers refine, ``gen.status`` flips to REFINE_IN_PROGRESS →
    // ``isPolling`` becomes true → this effect re-runs and starts polling.
    if (!isPolling) return

    // ``cancelled`` guards against a late tick calling ``setState`` after the
    // effect has been torn down — either due to unmount, an ``id`` change,
    // or a status crossing into terminal.
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
        // Belt-and-suspenders: also stop scheduling within tick as soon as
        // we see a terminal status, so we don't fire one extra request in
        // the ~ms between setGen and React re-rendering with the new
        // isPolling value.
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
  }, [id, isPolling])

  async function handleRefine() {
    if (!gen || refining) return
    setRefining(true)
    setError(null)
    try {
      const next = await refineGeneration(gen.id)
      // Optimistically install the returned row (already REFINE_IN_PROGRESS
      // or REFINE_FAILED). The polling effect above stays keyed on ``id``,
      // so it will keep running and eventually see REFINE_SUCCEEDED.
      setGen(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start refine')
    } finally {
      setRefining(false)
    }
  }

  // First render, before the initial poll resolves.
  if (!gen) {
    return (
      <div className="progress-panel">
        {error ? (
          <div className="error">Failed to load generation: {error}</div>
        ) : (
          <div className="progress-label">Loading…</div>
        )}
        <button className="link-button" onClick={onReset}>← Start a new prompt</button>
      </div>
    )
  }

  // Decide what to show:
  //   * PREVIEW_FAILED → dedicated failure panel, no viewer (no model exists).
  //   * Anything after PREVIEW_SUCCEEDED → viewer, choosing refine URL if
  //     ready, else preview. Refine-in-progress overlays a progress bar on
  //     top of the still-viewable preview.
  //   * Anything before PREVIEW_SUCCEEDED → progress panel (no viewer yet).
  const previewFailed = gen.status === 'PREVIEW_FAILED'
  const previewReady = gen.preview_model_url !== null
  const refineReady = gen.refine_model_url !== null
  const refineInFlight =
    gen.status === 'REFINE_PENDING' || gen.status === 'REFINE_IN_PROGRESS'
  const refineFailed = gen.status === 'REFINE_FAILED'
  // Prefer refined model when available; otherwise fall back to preview.
  const viewerUrl = refineReady ? gen.refine_model_url : gen.preview_model_url

  return (
    <div className="generation-view">
      {/* Row 1: navigation + status/action controls. Prompt echo used to
          live in this row too, but visually neighbouring "← New prompt"
          made users think the shown prompt WAS a new one they had
          entered. Moved to its own row below (see .prompt-echo-row). */}
      <div className="status-bar">
        <button className="link-button" onClick={onReset}>← Start a new prompt</button>
        <div className="status-bar-actions">
          <StatusBadge status={gen.status} />
          {/* Refine button is only meaningful once preview is done and no
              refine has started yet. Once refine is in flight, terminal,
              or failed, there is no way to trigger another refine —
              matches the state machine (REFINE_* states are terminal per
              PLAN.md). */}
          {gen.status === 'PREVIEW_SUCCEEDED' && (
            <button onClick={handleRefine} disabled={refining}>
              {refining ? 'Starting refine…' : 'Refine with textures'}
            </button>
          )}
        </div>
      </div>
      {/* Row 2: the prompt this generation is fulfilling. Centered so
          it reads as a caption for the whole page rather than an item
          in the top toolbar. */}
      <div className="prompt-echo-row">
        <span className="prompt-echo-label">Prompt</span>
        <span className="prompt-echo-text">"{gen.prompt}"</span>
      </div>

      {previewFailed ? (
        <div className="failure-panel">
          <h3>Generation failed</h3>
          <p>{gen.error ?? 'Unknown error'}</p>
          <button onClick={onReset}>Try another prompt</button>
        </div>
      ) : previewReady && viewerUrl ? (
        <div className="viewer">
          <ModelViewer url={viewerUrl} />
          {/* Overlay refine progress on top of the preview viewer so users
              can watch the process without losing sight of what they had. */}
          {refineInFlight && <RefineOverlay progress={gen.refine_progress} />}
          {/* Refine failure is soft — preview stays viewable. Show a banner
              on top so the failure is not hidden. */}
          {refineFailed && (
            <div className="refine-error">
              Refine failed: {gen.error ?? 'Unknown error'}
            </div>
          )}
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
  // Use the refine progress once we've moved past preview.
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

/**
 * Floating progress bar shown while a refine runs on top of the already-
 * viewable preview. Kept simple: a top-anchored ribbon rather than a modal
 * so the user can still orbit the preview meanwhile.
 */
function RefineOverlay({ progress }: { progress: number }) {
  return (
    <div className="refine-overlay">
      <div className="progress-label">Refining textures — {progress}%</div>
      <div className="progress-bar" role="progressbar" aria-valuenow={progress}>
        <div className="progress-bar-fill" style={{ width: `${progress}%` }} />
      </div>
    </div>
  )
}
