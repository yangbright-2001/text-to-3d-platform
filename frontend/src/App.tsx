import { ReactNode, useCallback, useEffect, useMemo, useState } from 'react'
import GenerationView from './GenerationView'
import ModelViewer from './ModelViewer'
import PromptForm from './PromptForm'
import TaskTracker from './TaskTracker'

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
 * Top-level router between the app's URL-driven modes.
 *
 * Precedence (most-specific first):
 *   1. ``?url=``          — M6 debug override; renders any GLB verbatim.
 *   2. ``?id=``           — poll a specific generation (M7) / show refine (M8).
 *   3. ``?view=tracker``  — M9 Task Tracker page.
 *   4. neither            — prompt form (default landing).
 *
 * Keeping both ``id`` and ``view`` in the URL means back/forward walks the
 * history naturally: form → tracker → viewer → back → tracker → back → form.
 */
export default function App() {
  const [id, setId] = useQueryParam('id')
  const [view, setView] = useQueryParam('view')

  // ``url`` is only read on mount: it's a debug override, not something the
  // app itself ever mutates. Kept in a ``useMemo`` for symmetry with ``id``.
  const urlOverride = useMemo(
    () => new URLSearchParams(window.location.search).get('url'),
    [],
  )

  const handleCreated = useCallback((newId: string) => setId(newId), [setId])
  // Reset clears BOTH ``id`` and ``view`` so "← Start a new prompt" always
  // lands on the form regardless of which page triggered it.
  const handleReset = useCallback(() => {
    setView(null)
    setId(null)
  }, [setId, setView])
  const handleOpenTracker = useCallback(() => {
    // Clear any lingering ``?id=`` so the tracker isn't shadowed by a viewer.
    setId(null)
    setView('tracker')
  }, [setId, setView])
  // Opening a card from the tracker: clear ``view`` and set ``id`` so the
  // viewer takes precedence.
  const handleOpenGeneration = useCallback(
    (openId: string) => {
      setView(null)
      setId(openId)
    },
    [setId, setView],
  )

  let body: JSX.Element
  let subtitle: ReactNode
  // A right-aligned nav link in the header, shown on every mode that isn't
  // already the tracker (so the user always has a discoverable path to
  // history without cluttering the tracker page itself).
  let headerNav: ReactNode = null
  if (urlOverride) {
    body = <ModelViewer url={urlOverride} />
    subtitle = (
      <>
        Viewer override: <span className="uuid">{urlOverride}</span>
      </>
    )
    headerNav = (
      <button className="link-button" onClick={handleOpenTracker}>
        History →
      </button>
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
    headerNav = (
      <button className="link-button" onClick={handleOpenTracker}>
        History →
      </button>
    )
  } else if (view === 'tracker') {
    body = (
      <TaskTracker
        onOpen={handleOpenGeneration}
        onNewPrompt={handleReset}
      />
    )
    subtitle = 'generation history'
    // No "History" link on the history page itself.
    headerNav = null
  } else {
    body = <PromptForm onCreated={handleCreated} />
    subtitle = 'enter a prompt to generate a 3D preview'
    headerNav = (
      <button className="link-button" onClick={handleOpenTracker}>
        History →
      </button>
    )
  }

  return (
    <div className="app">
      <header className="app-header">
        <strong>Text to 3D</strong>
        <span className="muted app-header-subtitle">{subtitle}</span>
        {headerNav && <div className="app-header-nav">{headerNav}</div>}
      </header>
      <main className="app-main">{body}</main>
    </div>
  )
}
