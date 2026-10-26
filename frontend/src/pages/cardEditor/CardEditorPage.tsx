/**
 * The card editor's own page (decision 9): `/system/custom-cards/new` and `/system/custom-cards/:slug/edit`, for
 * administrators only (KARTEN-9 AC-1; the server refuses everyone else as well).
 *
 * A new card begins in the guided way with nothing chosen (U3); a saved one is read with its text and the moment it
 * was last changed. A draft this browser kept is offered before anything is lost (EC-7).
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useParams } from 'react-router-dom'

import { ApiError, get } from '../../api/client'
import { AppShell } from '../../components/AppShell'
import { EmptyState, Spinner } from '../../components/ui'
import { useAuth } from '../../stores/auth'
import { dropDraft, readDraft, type CardDraft } from './draft'
import { EditorFrame, LIST_PATH } from './EditorFrame'
import { useEditorTexts } from './editorTexts'
import { useCardEditor } from './store'
import { NEW_CARD } from './templates'

type Phase = { kind: 'loading' } | { kind: 'editing' } | { kind: 'missing' } | { kind: 'failed'; message: string }

export function CardEditorPage() {
  const { t } = useTranslation()
  const ready = useEditorTexts()
  const user = useAuth((state) => state.user)
  const { slug: wanted } = useParams<{ slug?: string }>()
  const [phase, setPhase] = useState<Phase>({ kind: 'loading' })
  const [offer, setOffer] = useState<CardDraft | null>(null)
  const admin = user?.role === 'admin'

  useEffect(() => {
    if (!admin) return
    // Just saved as new and moved to its own address: the card on screen is this one already.
    if (wanted && useCardEditor.getState().slug === wanted && phase.kind === 'editing') return
    let gone = false
    setOffer(readDraft(wanted ?? null))
    if (!wanted) {
      useCardEditor.getState().open({ slug: null, text: NEW_CARD, base: null, saved: null })
      setPhase({ kind: 'editing' })
      return
    }
    setPhase({ kind: 'loading' })
    get<{ yaml: string; updated_at: string }>(`/cards/${encodeURIComponent(wanted)}`)
      .then((card) => {
        if (gone) return
        useCardEditor.getState().open({ slug: wanted, text: card.yaml, base: card.updated_at, saved: card.yaml })
        // A draft that is the saved text is no draft.
        const kept = readDraft(wanted)
        if (kept && kept.text === card.yaml) {
          dropDraft(wanted)
          setOffer(null)
        }
        setPhase({ kind: 'editing' })
      })
      .catch((failure) => {
        if (gone) return
        if (failure instanceof ApiError && failure.status === 404) setPhase({ kind: 'missing' })
        else setPhase({ kind: 'failed', message: failure instanceof ApiError ? failure.message : t('errors.network') })
      })
    return () => {
      gone = true
    }
    // The phase is read only to notice the move after a first save.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wanted, admin])

  if (!admin) return <Navigate to="/system" replace />

  let body: React.ReactNode
  if (!ready || phase.kind === 'loading') {
    body = (
      <div className="min-h-[50vh] grid place-items-center">
        <Spinner />
      </div>
    )
  } else if (phase.kind === 'missing' || phase.kind === 'failed') {
    body = (
      <div className="max-w-3xl mx-auto px-4 py-8">
        <EmptyState title={phase.kind === 'missing' ? t('editor.notFound', { slug: wanted ?? '' }) : phase.message} action={
            <Link className="btn" to={LIST_PATH}>
              {t('editor.back')}
            </Link>
          } />
      </div>
    )
  } else {
    body = <EditorFrame offer={offer} onOfferDone={() => setOffer(null)} />
  }

  return <AppShell title={t('cards.title')}>{body}</AppShell>
}
