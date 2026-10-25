/**
 * Saving a card from the editor (KARTEN-9 AC-13): a new one with `POST /cards`, a saved one with `PUT /cards/{slug}`
 * and the `updated_at` read on opening as `base` (decision 7).
 *
 * What can go wrong is told apart, so the page can offer the way on: somebody else saved meanwhile (EC-3, Overwrite
 * or Reload), the sign-in ran out (EC-8, sign in again and save, nothing lost), the card was deleted meanwhile
 * (KARTEN-11 EC-6, Save as new), the text has problems (at their lines and fields).
 */
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, post, put } from '../../api/client'
import { problemsOf, type CustomCardRow } from '../../lib/customCards'
import { dropDraft } from './draft'
import { useCardEditor } from './store'

export type SaveTrouble =
  | { kind: 'conflict'; by: string; at: string }
  | { kind: 'session' }
  | { kind: 'gone' }
  | { kind: 'error'; message: string }
  | null

type Saved = CustomCardRow & { yaml?: string }

export function useSaveCard() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [busy, setBusy] = useState(false)
  const [trouble, setTrouble] = useState<SaveTrouble>(null)

  /** Save what is on screen. Resolves to the saved card, or `null` when it was not saved. */
  const save = async ({ overwrite = false, asNew = false }: { overwrite?: boolean; asNew?: boolean } = {}): Promise<Saved | null> => {
    useCardEditor.getState().flusher?.()
    const { text, slug, base, card } = useCardEditor.getState()
    if (!card) return null
    setBusy(true)
    setTrouble(null)
    try {
      const saved =
        slug === null || asNew
          ? await post<Saved>('/cards', { yaml: text })
          : await put<Saved>(`/cards/${encodeURIComponent(slug)}`, { yaml: text, ...(base ? { base } : {}), ...(overwrite ? { overwrite: true } : {}) })
      useCardEditor.getState().saved(saved.slug, text, saved.updated_at ?? null)
      dropDraft(slug)
      if (saved.slug !== slug) dropDraft(saved.slug)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['custom-cards'] }),
        queryClient.invalidateQueries({ queryKey: ['cards-library'] }),
      ])
      return saved
    } catch (failure) {
      if (failure instanceof ApiError) {
        if (failure.status === 401) setTrouble({ kind: 'session' })
        else if (failure.code === 'card_changed_meanwhile') setTrouble({ kind: 'conflict', by: String(failure.detail.by ?? ''), at: String(failure.detail.at ?? '') })
        else if (failure.code === 'card_deleted') setTrouble({ kind: 'gone' })
        else if (problemsOf(failure).length) useCardEditor.getState().setServerProblems(problemsOf(failure), text)
        else if (failure.code === 'too_many_cards') setTrouble({ kind: 'error', message: t('cards.tooMany') })
        else setTrouble({ kind: 'error', message: failure.message })
      } else {
        setTrouble({ kind: 'error', message: t('errors.network') })
      }
      return null
    } finally {
      setBusy(false)
    }
  }

  return { save, busy, trouble, clear: () => setTrouble(null) }
}
