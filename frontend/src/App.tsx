import { ReactNode, useCallback, useEffect, useMemo, useState } from 'react'
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
  let subtitle: ReactNode
  if (urlOverride) {
    body = <ModelViewer url={urlOverride} />
    subtitle = (
      <>
        Viewer override: <span className="uuid">{urlOverride}</span>
      </>
    )
  } else if (id) {
    body = <GenerationView id={id} onReset={handleReset} />
    // Show the full uuid (not a slice) so the user can copy it verbatim to
    // query the DB or share the URL. Rendered in a monospace span so long
    // hex is readable, and prefixed with an explicit "Generation ID:" label
    // so the string right after it is unambiguously an id (not a name or
    // some other bare token that happens to look uuid-ish).
    subtitle = (
      <>
        Generation ID: <span className="uuid">{id}</span>
      </>
    )
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
