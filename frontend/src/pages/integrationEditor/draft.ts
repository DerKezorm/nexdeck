/**
 * The unsaved text of an integration, kept in this browser until it is saved or thrown away. One entry per
 * integration (`new` for one not saved yet). ⚠️ Every read and write is wrapped: a private window or a full storage
 * throws, and the editor must work without a draft rather than not at all.
 */

export interface IntegrationDraft {
  text: string
  /** The `updated_at` of the saved definition the draft was made from. */
  base: string | null
  /** When the draft was written, milliseconds. */
  at: number
}

const PREFIX = 'nexdeck.integrationDraft.'

export function draftKey(short: string | null): string {
  return PREFIX + (short ?? 'new')
}

export function readDraft(short: string | null): IntegrationDraft | null {
  try {
    const raw = localStorage.getItem(draftKey(short))
    if (!raw) return null
    const data = JSON.parse(raw) as Partial<IntegrationDraft>
    if (typeof data.text !== 'string' || typeof data.at !== 'number') return null
    return { text: data.text, base: typeof data.base === 'string' ? data.base : null, at: data.at }
  } catch {
    return null
  }
}

export function writeDraft(short: string | null, draft: IntegrationDraft): void {
  try {
    localStorage.setItem(draftKey(short), JSON.stringify(draft))
  } catch {
    // No room or no storage: the text is still on screen, only the safety net is missing.
  }
}

export function dropDraft(short: string | null): void {
  try {
    localStorage.removeItem(draftKey(short))
  } catch {
    // Nothing to drop where nothing can be kept.
  }
}
