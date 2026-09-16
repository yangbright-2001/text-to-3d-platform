/**
 * Thin, typed client for the backend's generations API.
 *
 * The types below are hand-maintained mirrors of ``schemas.GenerationRead`` on
 * the backend. That's deliberate for a small project: OpenAPI codegen would
 * be more infrastructure than a ~10-field DTO is worth. If the surface grows
 * we can revisit.
 */

/** Enum values must stay in lockstep with backend ``GenerationStatus``. */
export type GenerationStatus =
  | 'PREVIEW_PENDING'
  | 'PREVIEW_IN_PROGRESS'
  | 'PREVIEW_SUCCEEDED'
  | 'PREVIEW_FAILED'
  | 'REFINE_PENDING'
  | 'REFINE_IN_PROGRESS'
  | 'REFINE_SUCCEEDED'
  | 'REFINE_FAILED'

/** Mirror of ``schemas.GenerationRead``. Nulls are surfaced as ``null`` (not
 *  ``undefined``) to match FastAPI's serialization exactly. */
export interface Generation {
  id: string
  prompt: string
  status: GenerationStatus
  error: string | null
  preview_progress: number
  preview_model_url: string | null
  thumbnail_url: string | null
  refine_progress: number
  refine_model_url: string | null
  created_at: string
  updated_at: string
}

/**
 * True when the backend will make no further updates to a generation.
 *
 * Encoded as a suffix check so we don't have to enumerate every status — the
 * app-level state machine only ever ends in ``_SUCCEEDED`` or ``_FAILED``.
 * This means the polling loop is future-proof against M8's refine states.
 */
export function isTerminal(status: GenerationStatus): boolean {
  return status.endsWith('_SUCCEEDED') || status.endsWith('_FAILED')
}

/** Unwrap FastAPI JSON responses, promoting ``detail`` strings into ``Error``s. */
async function jsonFetch<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const res = await fetch(input, init)
  if (!res.ok) {
    // FastAPI's default error shape is ``{"detail": "..."}``; surface it
    // verbatim so validation messages (e.g., prompt too long) reach the UI
    // without us having to know every endpoint's failure modes.
    let detail: string = res.statusText
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      // Non-JSON error body — keep the HTTP status text as the fallback.
    }
    throw new Error(`${res.status} ${detail}`)
  }
  return (await res.json()) as T
}

/** ``POST /api/generations`` — submit a prompt, receive the initial row. */
export function createGeneration(prompt: string): Promise<Generation> {
  return jsonFetch<Generation>('/api/generations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt }),
  })
}

/** ``GET /api/generations/{id}`` — polling target while a generation runs. */
export function getGeneration(id: string): Promise<Generation> {
  return jsonFetch<Generation>(`/api/generations/${encodeURIComponent(id)}`)
}
