import type { TFunction } from 'i18next'

/** What did not come along with a copy, as the server names it (``POST /widgets/copy``). */
export interface CopyNote {
  /** ``started_empty``: a holder copied onto its own page, without its cards.
      ``held_left``: cards of a holder this person could not have made where the copy went. */
  code: string
  name: string
  count?: number
}

export interface CopyAnswer {
  copied: number
  page_id: number
  ids: number[]
  notes: CopyNote[]
}

/**
 * One sentence per note. A note nobody knows yet says nothing rather than
 * something wrong: the copy itself is there either way.
 */
export function copyNotes(notes: CopyNote[], t: TFunction): string[] {
  return notes.flatMap((note) => {
    if (note.code === 'started_empty') return [t('arrange.copyStartedEmpty', { name: note.name })]
    if (note.code === 'held_left') return [t('arrange.copyHeldLeft', { name: note.name, count: note.count ?? 1 })]
    return []
  })
}
