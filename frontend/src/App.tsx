import { useCallback, useEffect, useMemo, useState } from 'react'
import GenerationView from './GenerationView'
import ModelViewer from './ModelViewer'
import PromptForm from './PromptForm'

/**
 * Read a query-string param and keep it in sync with browser navigation.
 *
 * Storing the current generation id in the URL means:
 *   - reload survives (M7 gets rudimentary "resume where you left off"
 *     without needing localStorage or the M9 tracker),
 *   - a link is shareable / bookmarkable,
 *   - browser back/forward walks between the prompt form and the view.
 *
 * ``pushState`` (not ``replaceState``) is deliberate so back returns to the
 * prompt form after a submit.
 */
function useQueryParam(
  name: string,
): [string | null, (value: string | null) => void] {
  const [value, setValue] = useState<string | null>(() =>
    new URLSearchParams(window.location.search).get(name),
  )

  useEffect(() => {
    // React to back/forward so state and URL stay consistent.
    const onPop = () => {
      setValue(new URLSearchParams(window.location.search).get(name))
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [name])

  const update = useCallback(
    (next: string | null) => {
      const params = new URLSearchParams(window.location.search)
      if (next === null) params.delete(name)
      else params.set(name, next)
      const query = params.toString()
      const nextUrl = `${window.location.pathname}${query ? `?${query}` : ''}`
      window.history.pushState({}, '', nextUrl)
      setValue(next)
    },
    [name],
  )

  return [value, update]
}

/**
 * Top-level router between the three M7 modes.
 *
 * Precedence (most-specific first):
 *   1. ``?url=`` — M6's debug override, renders any GLB verbatim.
 *   2. ``?id=``  — poll a specific generation and show progress/model.
 *   3. neither   — prompt form.
 */
export default function App() {
  const [id, setId] = useQueryParam('id')

  // ``url`` is only read on mount: it's a debug override, not something the
  // app itself ever mutates. Kept in a ``useMemo`` for symmetry with ``id``.
  const urlOverride = useMemo(
    () => new URLSearchParams(window.location.search).get('url'),
    [],
  )

  const handleCreated = useCallback((newId: string) => setId(newId), [setId])
  const handleReset = useCallback(() => setId(null), [setId])

  let body: JSX.Element
  let subtitle: string
  if (urlOverride) {
    body = <ModelViewer url={urlOverride} />
    subtitle = `viewer override — ${urlOverride}`
  } else if (id) {
    body = <GenerationView id={id} onReset={handleReset} />
    // Show a short id so the user can correlate with backend logs.
    subtitle = `generation ${id.slice(0, 8)}…`
  } else {
    body = <PromptForm onCreated={handleCreated} />
    subtitle = 'enter a prompt to generate a 3D preview'
  }

  return (
    <div className="app">
      <header className="app-header">
        <strong>Text to 3D</strong>
        <span className="muted">{subtitle}</span>
      </header>
      <main className="app-main">{body}</main>
    </div>
  )
}
