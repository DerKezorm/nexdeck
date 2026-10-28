import { ArrowLeft } from 'lucide-react'
import { lazy, Suspense, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { ApiError, get, post, serverUrl } from '../../api/client'
import { Confirm, Dialog, Spinner, Toast } from '../../components/ui'
import { readAt } from '../../lib/cardDocument'
import type { CardProblem } from '../../lib/customCards'
import { useLeaveGuard } from '../cardEditor/useLeaveGuard'
import { localProblemText, serverProblemText } from '../cardEditor/problems'
import { dropDraft, writeDraft, type IntegrationDraft } from './draft'
import { resendIssue, resendNumber } from '../settings/share/resend'
import { FormView, SetupPreview } from './FormView'
import { currentServerProblems, isDirty, useIntegrationEditor, type IntegrationView } from './store'
import { useSaveIntegration } from './useSaveIntegration'

const CodeField = lazy(() => import('./CodeField'))

/** The two ways into the definition, in the order they stand on top. */
const VIEWS: IntegrationView[] = ['form', 'yaml']

/** Where "Back" leads: the Integrations tab of Custom cards. */
export const LIST_PATH = '/system/cards?tab=integrations'

/** The server checks a valid text this long after typing stops. */
export const CHECK_MS = 700

function clock(at: number | string, language: string): string {
  const moment = new Date(at)
  if (Number.isNaN(moment.getTime())) return String(at)
  const today = new Date().toDateString() === moment.toDateString()
  return new Intl.DateTimeFormat(language, today ? { timeStyle: 'short' } : { dateStyle: 'medium', timeStyle: 'short' }).format(moment)
}

/** Every problem of the text at its line, in words; a line opens in the YAML view. */
function ProblemList() {
  const { t } = useTranslation()
  const local = useIntegrationEditor((state) => state.problems)
  const server = useIntegrationEditor(currentServerProblems)
  const goToLine = useIntegrationEditor((state) => state.goToLine)
  const view = useIntegrationEditor((state) => state.view)
  // In the form a problem of the server stands at its field; the YAML's own, and every problem in the YAML view, stand here.
  const rows = [
    ...local.map((problem) => ({ line: problem.line, path: '', text: localProblemText(t, problem) })),
    ...(view === 'yaml' ? server.map((problem: CardProblem) => ({ line: problem.line, path: problem.path, text: serverProblemText(t, problem) })) : []),
  ]
  if (!rows.length) return null
  return (
    <div className="rounded-xl border border-bad/40 px-3 py-2 min-w-0" role="alert" data-testid="integration-problems">
      <div className="text-sm font-medium text-bad mb-1">{t('cards.problems')}</div>
      <ul className="text-[13px] space-y-1">
        {rows.map((row, index) => (
          <li key={index} className="break-words">
            {row.line !== null && (
              <button type="button" className="text-faint hover:text-accent hover:underline" onClick={() => goToLine(row.line ?? 1)}>
                {t('cards.line', { line: row.line })}
              </button>
            )}
            {row.path ? <span className="text-faint">{row.line !== null ? ' · ' : ''}{row.path}</span> : null}
            {row.line !== null || row.path ? ' · ' : ''}
            <span>{row.text}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * The editor of one integration (KARTEN-3): Back, the name, Form | YAML and Save on top; the form with the view of
 * what whoever sets it up sees, or the YAML. Asks before leaving with unsaved changes, keeps a draft in this browser.
 */
export function IntegrationFrame({ offer, onOfferDone }: { offer: IntegrationDraft | null; onOfferDone: () => void }) {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const editor = useIntegrationEditor()
  const { text, card, lastValid, view, short, base } = editor
  const dirty = isDirty(editor)
  const guard = useLeaveGuard(dirty)
  const { save, busy, trouble, clear } = useSaveIntegration()
  const [toast, setToast] = useState('')
  const [askReload, setAskReload] = useState(false)

  const shown = card ?? lastValid
  const name = shown ? String(readAt(shown, ['name']) ?? '') : ''
  const title = name || short || t('integrationEditor.titleNew')

  // Every change kept in this browser until it is saved. A draft not yet answered is left alone.
  useEffect(() => {
    if (offer) return
    if (dirty) writeDraft(short, { text, base, at: Date.now() })
    else dropDraft(short)
  }, [text, dirty, short, base, offer])

  // The server's check of a valid text, a moment after typing stops.
  useEffect(() => {
    if (!card) return
    let current = true
    const timer = window.setTimeout(() => {
      post<{ ok: boolean; problems?: CardProblem[] }>('/own-integrations/check', { yaml: text })
        .then((answer) => {
          if (current) useIntegrationEditor.getState().setServerProblems(answer.ok ? [] : (answer.problems ?? []), text)
        })
        .catch(() => {
          // The check helps while typing; saving checks again and says what is wrong.
        })
    }, CHECK_MS)
    return () => {
      current = false
      window.clearTimeout(timer)
    }
  }, [text, card])

  const doSave = async (options: { overwrite?: boolean } = {}) => {
    const before = useIntegrationEditor.getState().short
    const saved = await save(options)
    if (!saved) return
    setToast(t('integrationEditor.saved'))
    const resend = resendNumber(params)
    if (resend > 0) {
      const sent = await resendIssue(t, resend)
      setToast(sent.message)
      if (sent.ok) setParams({}, { replace: true })
    }
    if (saved.short !== before) {
      guard.allow()
      navigate(`/system/custom-cards/integrations/${encodeURIComponent(saved.short)}/edit`, { replace: true })
    }
  }

  const reload = async () => {
    if (!short) return
    clear()
    try {
      const fresh = await get<{ yaml: string; updated_at: string }>(`/own-integrations/${encodeURIComponent(short)}`)
      dropDraft(short)
      useIntegrationEditor.getState().open({ short, text: fresh.yaml, base: fresh.updated_at, saved: fresh.yaml, view })
    } catch (failure) {
      setToast(failure instanceof ApiError ? failure.message : t('errors.network'))
    }
  }

  const restore = () => {
    if (!offer) return
    useIntegrationEditor.getState().setText(offer.text)
    if (offer.base) useIntegrationEditor.setState({ base: offer.base })
    onOfferDone()
  }

  const discard = () => {
    dropDraft(short)
    onOfferDone()
  }

  const canSave = card !== null && !busy && (dirty || short === null)

  return (
    <div className="min-w-0">
      <div className="sticky top-0 z-20 glass-strong border-b border-line">
        <div className="max-w-7xl mx-auto px-3 sm:px-4 py-2 flex flex-wrap items-center gap-2 min-w-0">
          <Link to={LIST_PATH} className="btn btn-icon btn-flat" aria-label={t('editor.back')} title={t('editor.back')}>
            <ArrowLeft size={16} />
          </Link>
          <div className="min-w-0 flex-1 basis-40">
            <div className="text-[11px] text-faint break-words">{t('integrationEditor.crumb')}</div>
            <h1 className="font-semibold text-[15px] break-words">{title}</h1>
          </div>
          {!card && lastValid && <span className="text-[12px] text-muted break-words">{t('integrationEditor.lastValid')}</span>}
          <div className="inline-flex rounded-lg bg-surface p-0.5 gap-0.5" role="group" aria-label={t('editor.view.label')}>
            {VIEWS.map((one) => (
              <button
                key={one}
                type="button"
                className={`px-3 h-8 rounded-md text-sm ${view === one ? 'bg-accent-soft text-ink font-medium' : 'text-muted'} disabled:opacity-50`}
                aria-pressed={view === one}
                disabled={one === 'form' && !card}
                title={one === 'form' && !card ? t('integrationEditor.fixFirst') : undefined}
                onClick={() => useIntegrationEditor.getState().setView(one)}
              >
                {t(`integrationEditor.view.${one}`)}
              </button>
            ))}
          </div>
          <button type="button" className="btn btn-accent" onClick={() => void doSave()} disabled={!canSave}>
            {busy ? <Spinner /> : null}
            {t('editor.save')}
          </button>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-3 sm:px-4 py-4 grid gap-4 min-w-0">
        {offer && (
          <div className="rounded-xl border border-accent/40 px-3 py-2 flex flex-wrap items-center gap-2" role="status">
            <div className="min-w-0 flex-1 basis-60">
              <div className="text-sm font-medium">{t('editor.restore.title')}</div>
              <div className="text-[13px] text-muted">{t('editor.restore.body', { time: clock(offer.at, i18n.language) })}</div>
            </div>
            <button type="button" className="btn btn-accent" onClick={restore}>
              {t('editor.restore.restore')}
            </button>
            <button type="button" className="btn btn-flat" onClick={discard}>
              {t('editor.restore.discard')}
            </button>
          </div>
        )}

        {trouble?.kind === 'error' && (
          <p className="text-sm text-bad rounded-lg border border-bad/40 px-3 py-2" role="alert">
            {trouble.message}
          </p>
        )}

        <ProblemList />

        {view === 'form' && card ? (
          <div className="flex flex-col lg:flex-row gap-4 min-w-0">
            <div className="flex-1 min-w-0">
              <FormView />
            </div>
            <div className="lg:w-[360px] lg:flex-none min-w-0 lg:sticky lg:top-16 lg:self-start">
              <SetupPreview />
            </div>
          </div>
        ) : (
          <Suspense
            fallback={
              <div className="min-h-[420px] grid place-items-center">
                <Spinner />
              </div>
            }
          >
            <CodeField />
          </Suspense>
        )}
      </div>

      <Confirm open={guard.asking} title={t('editor.leave.title')} body={t('integrationEditor.leaveBody')} danger confirmLabel={t('editor.leave.leave')} onCancel={guard.stay} onConfirm={guard.leave} />

      <Confirm
        open={askReload}
        title={t('editor.conflict.reloadTitle')}
        body={t('integrationEditor.reloadBody')}
        danger
        confirmLabel={t('editor.conflict.reloadConfirm')}
        onCancel={() => setAskReload(false)}
        onConfirm={() => {
          setAskReload(false)
          void reload()
        }}
      />

      <Dialog
        open={trouble?.kind === 'conflict'}
        onClose={clear}
        title={trouble?.kind === 'conflict' ? t('integrationEditor.conflict.title', { by: trouble.by }) : ''}
        footer={
          <>
            <button
              type="button"
              className="btn"
              onClick={() => {
                if (!isDirty(useIntegrationEditor.getState())) return void reload()
                clear()
                setAskReload(true)
              }}
            >
              {t('editor.conflict.reload')}
            </button>
            <button type="button" className="btn btn-accent" onClick={() => void doSave({ overwrite: true })} disabled={busy}>
              {t('editor.conflict.overwrite')}
            </button>
          </>
        }
      >
        {trouble?.kind === 'conflict' && <p className="text-sm break-words">{t('integrationEditor.conflict.body', { by: trouble.by, time: clock(trouble.at, i18n.language) })}</p>}
      </Dialog>

      <Dialog
        open={trouble?.kind === 'session'}
        onClose={clear}
        title={t('editor.session.title')}
        footer={
          <>
            <a className="btn" href={serverUrl('/login')} target="_blank" rel="noopener">
              {t('editor.session.signIn')}
            </a>
            <button type="button" className="btn btn-accent" onClick={() => void doSave()} disabled={busy}>
              {t('editor.session.retry')}
            </button>
          </>
        }
      >
        <p className="text-sm break-words">{t('editor.session.body')}</p>
      </Dialog>

      {toast && (
        <Toast level="ok" onClose={() => setToast('')}>
          {toast}
        </Toast>
      )}
    </div>
  )
}
