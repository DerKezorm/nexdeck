/**
 * The integration editor's own page (KARTEN-3): `/system/custom-cards/integrations/new` and
 * `/system/custom-cards/integrations/:short/edit`, for administrators only (the server refuses everyone else as well).
 *
 * A new one begins with the example the server hands out (`GET /own-integrations/template`); a saved one is read with
 * its text and the moment it was last changed. A draft this browser kept is offered before anything is lost.
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useParams } from 'react-router-dom'

import { ApiError, get } from '../../api/client'
import { AppShell } from '../../components/AppShell'
import { EmptyState, Spinner } from '../../components/ui'
import { useAuth } from '../../stores/auth'
import { useEditorTexts } from '../cardEditor/editorTexts'
import { dropDraft, readDraft, type IntegrationDraft } from './draft'
import { IntegrationFrame, LIST_PATH } from './IntegrationFrame'
import { useIntegrationEditor } from './store'

type Phase = { kind: 'loading' } | { kind: 'editing' } | { kind: 'missing' } | { kind: 'failed'; message: string }

export function IntegrationEditorPage() {
  const { t } = useTranslation()
  const ready = useEditorTexts()
  const user = useAuth((state) => state.user)
  const { short: wanted } = useParams<{ short?: string }>()
  const [phase, setPhase] = useState<Phase>({ kind: 'loading' })
  const [offer, setOffer] = useState<IntegrationDraft | null>(null)
  const admin = user?.role === 'admin'

  useEffect(() => {
    if (!admin) return
    // Just saved as new and moved to its own address: what is on screen is this one already.
    if (wanted && useIntegrationEditor.getState().short === wanted && phase.kind === 'editing') return
    let gone = false
    setOffer(readDraft(wanted ?? null))
    setPhase({ kind: 'loading' })
    const failed = (failure: unknown) => {
      if (gone) return
      if (failure instanceof ApiError && failure.status === 404) setPhase({ kind: 'missing' })
      else setPhase({ kind: 'failed', message: failure instanceof ApiError ? failure.message : t('errors.network') })
    }
    if (!wanted) {
      get<{ yaml: string }>('/own-integrations/template')
        .then((template) => {
          if (gone) return
          useIntegrationEditor.getState().open({ short: null, text: template.yaml, base: null, saved: template.yaml })
          setPhase({ kind: 'editing' })
        })
        .catch(failed)
    } else {
      get<{ yaml: string; updated_at: string }>(`/own-integrations/${encodeURIComponent(wanted)}`)
        .then((found) => {
          if (gone) return
          useIntegrationEditor.getState().open({ short: wanted, text: found.yaml, base: found.updated_at, saved: found.yaml })
          // A draft that is the saved text is no draft.
          const kept = readDraft(wanted)
          if (kept && kept.text === found.yaml) {
            dropDraft(wanted)
            setOffer(null)
          }
          setPhase({ kind: 'editing' })
        })
        .catch(failed)
    }
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
        <EmptyState
          title={phase.kind === 'missing' ? t('integrationEditor.notFound', { short: wanted ?? '' }) : phase.message}
          action={
            <Link className="btn" to={LIST_PATH}>
              {t('editor.back')}
            </Link>
          }
        />
      </div>
    )
  } else {
    body = <IntegrationFrame offer={offer} onOfferDone={() => setOffer(null)} />
  }

  return <AppShell title={t('cards.title')}>{body}</AppShell>
}
