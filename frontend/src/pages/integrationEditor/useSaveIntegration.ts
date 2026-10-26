/**
 * Saving an integration from the editor (KARTEN-3 AC-1): a new one with `POST /own-integrations`, a saved one with
 * `PUT /own-integrations/{short}` and the `updated_at` read on opening as `base`. What can go wrong is told apart so
 * that the page can offer the way on: somebody else saved meanwhile (Overwrite or Reload), the sign-in ran out, the
 * limit of 50, the text has problems (at their lines and fields).
 */
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, post, put } from '../../api/client'
import { problemsOf } from '../../lib/customCards'
import { dropDraft } from './draft'
import { useIntegrationEditor } from './store'

export interface SavedIntegration {
  short: string
  kind: string
  name: string
  yaml: string
  updated_at: string
}

export type SaveTrouble = { kind: 'conflict'; by: string; at: string } | { kind: 'session' } | { kind: 'error'; message: string } | null

export function useSaveIntegration() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [busy, setBusy] = useState(false)
  const [trouble, setTrouble] = useState<SaveTrouble>(null)

  /** Save what is on screen. Resolves to the saved integration, or `null` when it was not saved. */
  const save = async ({ overwrite = false }: { overwrite?: boolean } = {}): Promise<SavedIntegration | null> => {
    useIntegrationEditor.getState().flusher?.()
    const { text, short, base, card } = useIntegrationEditor.getState()
    if (!card) return null
    setBusy(true)
    setTrouble(null)
    try {
      const saved =
        short === null
          ? await post<SavedIntegration>('/own-integrations', { yaml: text })
          : await put<SavedIntegration>(`/own-integrations/${encodeURIComponent(short)}`, { yaml: text, ...(base ? { base } : {}), ...(overwrite ? { overwrite: true } : {}) })
      useIntegrationEditor.getState().markSaved(saved.short, text, saved.updated_at ?? null)
      dropDraft(short)
      dropDraft(saved.short)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['own-integrations'] }),
        queryClient.invalidateQueries({ queryKey: ['adapters'] }),
        queryClient.invalidateQueries({ queryKey: ['cards-sources'] }),
      ])
      return saved
    } catch (failure) {
      if (failure instanceof ApiError) {
        if (failure.status === 401) setTrouble({ kind: 'session' })
        else if (failure.code === 'integration_changed_meanwhile') setTrouble({ kind: 'conflict', by: String(failure.detail.by ?? ''), at: String(failure.detail.at ?? '') })
        else if (problemsOf(failure).length) useIntegrationEditor.getState().setServerProblems(problemsOf(failure), text)
        else if (failure.code === 'integration_limit') setTrouble({ kind: 'error', message: t('cards.integrations.tooMany') })
        else if (failure.code === 'integration_exists') setTrouble({ kind: 'error', message: t('cards.integrations.exists') })
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
