import { useCallback, useEffect, useState } from 'react'
import { Generation, GenerationStatus, isTerminal, listGenerations } from './api'

interface Props {
  /** Open a specific generation in the viewer (parent flips ``?id=``). */
  onOpen: (id: string) => void
  /** Return to the prompt form. */
  onNewPrompt: () => void
}

/**
 * Task Tracker page (M9).
 *
 * Renders the full generation history as a grid of cards. Backend already
 * returns newest-first via ``GET /api/generations``; we render the array
 * as-is so pagination/sorting stays a backend concern.
 *
 * Auto-refresh: if any row is still non-terminal (someone submitted a
 * generation in another tab, or refresh landed mid-preview), we poll the
 * list at the same 3s cadence used by ``GenerationView``. Once every row
 * is terminal, polling stops so an idle tracker page doesn't hammer the
 * backend. A manual "Refresh" button is always available as an escape
 * hatch.
 */
const POLL_INTERVAL_MS = 3000

export default function TaskTracker({ onOpen, onNewPrompt }: Props) {
  const [rows, setRows] = useState<Generation[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Distinguishes the very first load ("Loading…") from a manual refresh
  // ("Refreshing…" on top of existing rows) so the grid doesn't flash to
  // an empty state every time the user clicks the button.
  const [refreshing, setRefreshing] = useState(false)

  const anyInFlight = rows?.some(r => !isTerminal(r.status)) ?? false

  const fetchRows = useCallback(async () => {
    setRefreshing(true)
    try {
      const next = await listGenerations()
      setRows(next)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load history')
    } finally {
      setRefreshing(false)
    }
  }, [])

  // Initial fetch on mount.
  useEffect(() => {
    fetchRows()
  }, [fetchRows])

  // Auto-poll while any row is non-terminal. Effect is keyed on
  // ``anyInFlight`` so it naturally stops once every generation settles.
  useEffect(() => {
    if (!anyInFlight) return
    let cancelled = false
    const interval = window.setInterval(() => {
      if (cancelled) return
      // ``fetchRows`` already manages its own error state; we don't await
      // here because a slow response shouldn't delay the next tick past
      // the interval boundary.
      fetchRows()
    }, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      window.clearInterval(interval)
    }
  }, [anyInFlight, fetchRows])

  return (
    <div className="task-tracker">
      <div className="status-bar">
        <button className="link-button" onClick={onNewPrompt}>
          ← Start a new prompt
        </button>
        <div className="status-bar-actions">
          {anyInFlight && (
            <span className="muted">Live — {countInFlight(rows)} in progress</span>
          )}
          <button
            className="secondary"
            onClick={fetchRows}
            disabled={refreshing}
            title="Reload the list now. The page already auto-refreshes every 3s while a generation is in progress; use this after everything has finished, or if a refresh failed."
          >
            {refreshing ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </div>

      {rows === null ? (
        <div className="progress-panel">
          {error ? (
            <div className="error">Failed to load history: {error}</div>
          ) : (
            <div className="progress-label">Loading…</div>
          )}
        </div>
      ) : rows.length === 0 ? (
        <div className="progress-panel">
          <div className="progress-label">No generations yet.</div>
          <button onClick={onNewPrompt}>Generate your first model</button>
        </div>
      ) : (
        <>
          {/* A transient banner keeps the last-known list visible while a
              refresh is in flight, so the grid never blanks out. */}
          {error && <div className="error tracker-error">Refresh failed: {error}</div>}
          <div className="task-tracker-grid">
            {rows.map(row => (
              <TaskCard key={row.id} row={row} onOpen={onOpen} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function countInFlight(rows: Generation[] | null): number {
  if (!rows) return 0
  return rows.reduce((n, r) => (isTerminal(r.status) ? n : n + 1), 0)
}

interface CardProps {
  row: Generation
  onOpen: (id: string) => void
}

/**
 * One entry in the tracker grid.
 *
 * Rendered as a ``div role="button"`` rather than a native ``<button>``:
 * Chromium sizes overflow:hidden flex buttons to line-height and clips
 * the thumbnail. A div sizes to its contents; we keep button semantics
 * with role/tabIndex/Enter-Space.
 *
 * Caption is always three left-aligned lines (prompt / status / time) so
 * every card in a row has the same height.
 */
function TaskCard({ row, onOpen }: CardProps) {
  function activate() {
    onOpen(row.id)
  }

  return (
    <div
      role="button"
      tabIndex={0}
      className="task-card"
      onClick={activate}
      onKeyDown={e => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          activate()
        }
      }}
      // The prompt is the most useful hover-tooltip: prompts are often
      // longer than the card body can show without ellipsis.
      title={row.prompt}
    >
      <div className="task-card-thumb">
        {row.thumbnail_url ? (
          <img src={row.thumbnail_url} alt="" loading="lazy" />
        ) : (
          <ThumbPlaceholder status={row.status} />
        )}
      </div>
      <div className="task-card-body">
        <div className="task-card-prompt">{row.prompt}</div>
        <span className={`status status-${row.status.toLowerCase()}`}>
          {statusLabel(row)}
        </span>
        <time className="muted task-card-time" dateTime={row.created_at}>
          {formatTimestamp(row.created_at)}
        </time>
      </div>
    </div>
  )
}

/**
 * Neutral placeholder rendered when a row has no thumbnail yet (in-flight
 * or preview-failed). Uses the status colour so the card is still visually
 * grouped with its pill.
 */
function ThumbPlaceholder({ status }: { status: GenerationStatus }) {
  const failed = status.endsWith('_FAILED')
  return (
    <div className={`task-card-thumb-placeholder ${failed ? 'failed' : ''}`}>
      {failed ? '⚠' : '⋯'}
    </div>
  )
}

/**
 * Duplicated from ``GenerationView`` on purpose — the two views humanize
 * the same enum but might diverge later (e.g., tracker could show "just
 * now" for freshly-created rows). Keeping a copy avoids reaching into a
 * sibling component just to share three lines of switch.
 */
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

/** In-flight rows append Meshy's percent so the tracker shows live progress. */
function statusLabel(row: Generation): string {
  const label = humanize(row.status)
  if (isTerminal(row.status)) return label
  const pct = row.status.startsWith('REFINE_')
    ? row.refine_progress
    : row.preview_progress
  return `${label} · ${pct}%`
}

/**
 * Format a generation timestamp in US Pacific time.
 *
 * The backend stores UTC but SQLite + FastAPI currently emit a naive ISO
 * string (no ``Z`` / offset). Treat missing timezone as UTC so we don't
 * accidentally display UTC clock hours as if they were local. Minutes are
 * included so two same-hour submits stay distinguishable.
 *
 * ``America/Los_Angeles`` automatically switches PDT/PST; September is PDT.
 */
const PACIFIC_TZ = 'America/Los_Angeles'

function formatTimestamp(iso: string): string {
  const d = new Date(/Z$|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`)
  if (Number.isNaN(d.getTime())) return iso
  return new Intl.DateTimeFormat('en-US', {
    timeZone: PACIFIC_TZ,
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  }).format(d)
}
