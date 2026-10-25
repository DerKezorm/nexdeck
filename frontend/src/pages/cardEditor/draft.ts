/**
 * The unsaved text of a card, kept in this browser until it is saved or thrown away (KARTEN-9 EC-7).
 *
 * One entry per card (`slug`, `new` for a card not saved yet). ⚠️ Every read and write is wrapped: a private window,
 * a full or blocked storage throws, and the editor must work without a draft rather than not at all (decision 8).
 */

export interface CardDraft {
  text: string
  /** The `updated_at` of the saved card the draft was made from, so that saving it still notices a change meanwhile. */
  base: string | null
  /** When the draft was written, milliseconds. */
  at: number
}

const PREFIX = 'nexdeck.cardDraft.'

export function draftKey(slug: string | null): string {
  return PREFIX + (slug ?? 'new')
}

export function readDraft(slug: string | null): CardDraft | null {
  try {
    const raw = localStorage.getItem(draftKey(slug))
    if (!raw) return null
    const data = JSON.parse(raw) as Partial<CardDraft>
    if (typeof data.text !== 'string' || typeof data.at !== 'number') return null
    return { text: data.text, base: typeof data.base === 'string' ? data.base : null, at: data.at }
  } catch {
    return null
  }
}

export function writeDraft(slug: string | null, draft: CardDraft): void {
  try {
    localStorage.setItem(draftKey(slug), JSON.stringify(draft))
  } catch {
    // No room or no storage: the card is still on screen, only the safety net is missing.
  }
}

export function dropDraft(slug: string | null): void {
  try {
    localStorage.removeItem(draftKey(slug))
  } catch {
    // Nothing to drop where nothing can be kept.
  }
}
