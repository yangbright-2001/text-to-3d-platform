import { ReactNode, useCallback, useEffect, useState } from 'react'
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

/** One history entry that replaces the whole query string, then syncs
 *  every ``useQueryParam`` via popstate. Needed because each hook's
 *  setter only mutates *its* key and would leave a leftover ``?url=``
 *  (which outranks ``?view=tracker``) when opening history from a
 *  debug override. */
function replaceQuery(search: string): void {
  const nextUrl = `${window.location.pathname}${search}`
  const current = `${window.location.pathname}${window.location.search}`
  if (current === nextUrl) return
  window.history.pushState({}, '', nextUrl)
  window.dispatchEvent(new PopStateEvent('popstate'))
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
  const [view] = useQueryParam('view')
  // Same hook as id/view so "Text to 3D" → home can clear a ``?url=`` debug
  // override via one pushState + popstate, without a leftover frozen memo.
  const [urlOverride] = useQueryParam('url')

  const handleCreated = useCallback((newId: string) => setId(newId), [setId])
  // Bare ``/`` so a leftover ``?url=`` debug override cannot keep the
  // viewer on screen after "Start a new prompt".
  const handleReset = useCallback(() => replaceQuery(''), [])
  const handleOpenTracker = useCallback(() => {
    // Replace the whole query: ``?url=`` outranks ``?view=tracker``, so
    // adding view while leaving url set looks like a no-op (URL changes,
    // page does not).
    replaceQuery('?view=tracker')
  }, [])
  const handleOpenGeneration = useCallback((openId: string) => {
    replaceQuery(`?id=${encodeURIComponent(openId)}`)
  }, [])
  const handleGoHome = useCallback(() => replaceQuery(''), [])

  let body: JSX.Element
  let subtitle: ReactNode
  // Right-aligned header nav is only for *going to* history (home / debug
  // override). On the viewer, returning to history is a back-action and
  // lives on the left inside ``GenerationView`` so it isn't mistaken for
  // "forward".
  let headerNav: ReactNode = null
  if (urlOverride) {
    body = <ModelViewer url={urlOverride} />
    subtitle = (
      <>
        Viewer override: <span className="uuid">{urlOverride}</span>
      </>
    )
    headerNav = (
      <button className="secondary history-nav" onClick={handleOpenTracker}>
        Generation history
      </button>
    )
  } else if (id) {
    body = (
      <GenerationView
        id={id}
        onReset={handleReset}
        onBackToHistory={handleOpenTracker}
      />
    )
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
  } else if (view === 'tracker') {
    body = (
      <TaskTracker
        onOpen={handleOpenGeneration}
        onNewPrompt={handleReset}
      />
    )
    subtitle = 'generation history'
    // No history link on the history page itself.
    headerNav = null
  } else {
    body = <PromptForm onCreated={handleCreated} />
    subtitle = 'enter a prompt to generate a 3D preview'
    headerNav = (
      <button className="secondary history-nav" onClick={handleOpenTracker}>
        Generation history
      </button>
    )
  }

  return (
    <div className="app">
      <header className="app-header">
        <a
          href="/"
          className="app-title"
          onClick={e => {
            e.preventDefault()
            handleGoHome()
          }}
        >
          Text to 3D
        </a>
        <span className="muted app-header-subtitle">{subtitle}</span>
        {headerNav && <div className="app-header-nav">{headerNav}</div>}
      </header>
      <main className="app-main">{body}</main>
    </div>
  )
}
