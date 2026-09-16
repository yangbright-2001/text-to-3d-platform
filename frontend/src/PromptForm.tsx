import { FormEvent, useState } from 'react'
import { createGeneration } from './api'

interface Props {
  /** Called with the new generation's id once ``POST /api/generations`` succeeds. */
  onCreated: (id: string) => void
}

/**
 * Prompt entry form.
 *
 * The submit button is disabled while a request is in flight so the user
 * can't fire two identical generations (each would cost real Meshy credits
 * on a non-test key). Client-side length matches the backend's 800-char cap
 * so the user hits a friendly counter instead of a 422 from FastAPI.
 */
export default function PromptForm({ onCreated }: Props) {
  const [prompt, setPrompt] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const trimmed = prompt.trim()
    // Guard against submitting whitespace-only prompts; the button is also
    // disabled in this state, but Enter-to-submit could bypass that.
    if (!trimmed || submitting) return

    setSubmitting(true)
    setError(null)
    try {
      const gen = await createGeneration(trimmed)
      onCreated(gen.id)
      // Deliberately not resetting ``submitting`` on success: the parent will
      // swap us out for ``GenerationView`` and this form unmounts.
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to submit')
      setSubmitting(false)
    }
  }

  return (
    <form className="prompt-form" onSubmit={handleSubmit}>
      <label htmlFor="prompt">Describe the object you want to generate</label>
      <textarea
        id="prompt"
        value={prompt}
        onChange={e => setPrompt(e.target.value)}
        maxLength={800}
        rows={8}
        placeholder="e.g. a small yellow rubber duck"
        disabled={submitting}
        autoFocus
      />
      <div className="prompt-form-footer">
        <span className="muted">{prompt.length}/800</span>
        <button type="submit" disabled={submitting || !prompt.trim()}>
          {submitting ? 'Submitting…' : 'Generate preview'}
        </button>
      </div>
      {error && <div className="error">{error}</div>}
    </form>
  )
}
