import { ArrowLeft } from 'lucide-react'
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'

import { get, serverUrl } from '../../api/client'
import { Confirm, Dialog, Spinner, Toast } from '../../components/ui'
import { pickText, type CardText } from '../../lib/cardText'
import { readAt } from '../../lib/cardDocument'
import { AdjustedBlock } from './AdjustedBlock'
import { dropDraft, writeDraft, type CardDraft } from './draft'
import { GuidedWay } from './guided/GuidedWay'
import { Preview } from './Preview'
import { ProblemList } from './ProblemList'
import { LookStep } from './steps/LookStep'
import { RulesStep } from './steps/RulesStep'
import { SourceStep } from './steps/SourceStep'
import { TextsStep } from './steps/TextsStep'
import { isDirty, STEPS, useCardEditor, type EditorStep, type EditorView } from './store'
import { NEW_CARD } from './templates'
import { useLeaveGuard } from './useLeaveGuard'
import { useSaveCard } from './useSaveCard'

const YamlView = lazy(() => import('./YamlView'))

/** The three ways into the card, in the order they stand on top (U1). */
const VIEWS: EditorView[] = ['guided', 'editor', 'yaml']

/** The page each step shows. A step of a later version adds itself here and to `STEPS`. */
const STEP_PAGES: Record<EditorStep, () => React.ReactElement> = {
  source: SourceStep,
  look: LookStep,
  rules: RulesStep,
  texts: TextsStep,
}

export const LIST_PATH = '/system/cards'

/**
 * Whether Ctrl Z in `target` is the card's step back: in the editor's fields and in the YAML view, or with no field
 * focused. Not in a dialog and not in a field outside the editor (the search, say), where it is that field's own.
 */
export function takesHistory(target: EventTarget | null, root: HTMLElement | null): boolean {
  if (!(target instanceof Element)) return true
  if (target.closest('[role="dialog"]')) return false
  const field = target.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"])')
  return !field || (root?.contains(field) ?? false)
}

function clock(at: number | string, language: string): string {
  const moment = new Date(at)
  if (Number.isNaN(moment.getTime())) return String(at)
  const today = new Date().toDateString() === moment.toDateString()
  return new Intl.DateTimeFormat(language, today ? { timeStyle: 'short' } : { dateStyle: 'medium', timeStyle: 'short' }).format(moment)
}

/**
 * The editor of one card (KARTEN-9, KARTEN-10): Back, the name, Editor | YAML and Save on top; the steps and the
 * preview below, or the YAML view and the preview. Asks before leaving with unsaved changes (AC-11), keeps a draft
 * in this browser (EC-7), takes Ctrl Z and Ctrl Shift Z for every change since opening (EC-10).
 */
export function EditorFrame({ offer, onOfferDone }: { offer: CardDraft | null; onOfferDone: () => void }) {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const editor = useCardEditor()
  const { text, card, lastValid, problems, view, step, slug, base, replaced, refusal } = editor
  // A new card nobody has touched yet holds nothing to lose: no draft, no question before leaving.
  const dirty = isDirty(editor) && !(slug === null && text === NEW_CARD)
  const guard = useLeaveGuard(dirty)
  const { save, busy, trouble, clear } = useSaveCard()
  const [toast, setToast] = useState('')
  const [askReload, setAskReload] = useState(false)
  const root = useRef<HTMLDivElement>(null)

  const shown = card ?? lastValid?.card ?? null
  const name = shown ? pickText(readAt(shown, ['name']) as CardText, i18n.language) : ''
  const title = name || (slug ?? t('editor.titleNew'))
  const firstLine = problems.find((problem) => problem.line !== null)?.line ?? null

  // Every change kept in this browser until it is saved (EC-7). A draft not yet answered is left alone.
  useEffect(() => {
    if (offer) return
    if (dirty) writeDraft(slug, { text, base, at: useCardEditor.getState().now() })
    else dropDraft(slug)
  }, [text, dirty, slug, base, offer])

  // Ctrl Z and Ctrl Shift Z (Cmd on a Mac) for everything since the editor opened, in a field or in the YAML (EC-10).
  // ⚠️ The code editor keeps no history of its own, and a field outside the editor or in a dialog keeps its own.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey) return
      if (!takesHistory(event.target, root.current)) return
      const key = event.key.toLowerCase()
      if (key === 'z' && !event.shiftKey) {
        event.preventDefault()
        useCardEditor.getState().undo()
      } else if ((key === 'z' && event.shiftKey) || key === 'y') {
        event.preventDefault()
        useCardEditor.getState().redo()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const doSave = async (options: { overwrite?: boolean; asNew?: boolean } = {}) => {
    const before = useCardEditor.getState().slug
    const saved = await save(options)
    if (!saved) return
    setToast(t('editor.saved'))
    // The first save of a new card: the guided way offers to put it on a board, on its last step, wherever the
    // author saved from (Save at the top included).
    if (before === null) useCardEditor.setState((state) => ({ created: true, guidedStep: state.view === 'guided' ? 'finish' : state.guidedStep }))
    if (saved.slug !== before) {
      guard.allow()
      navigate(`/system/custom-cards/${encodeURIComponent(saved.slug)}/edit`, { replace: true })
    }
  }

  const reload = async () => {
    if (!slug) return
    clear()
    try {
      const fresh = await get<{ yaml: string; updated_at: string }>(`/cards/${encodeURIComponent(slug)}`)
      dropDraft(slug)
      useCardEditor.getState().open({ slug, text: fresh.yaml, base: fresh.updated_at, saved: fresh.yaml, view })
    } catch {
      setToast(t('errors.network'))
    }
  }

  const restore = () => {
    if (!offer) return
    // A new card starts over with the draft, in the way that can show it; a saved one keeps its steps back.
    if (useCardEditor.getState().slug === null) {
      useCardEditor.getState().open({ slug: null, text: offer.text, base: offer.base ?? null, saved: null })
      return onOfferDone()
    }
    useCardEditor.getState().setText(offer.text)
    useCardEditor.setState({ base: offer.base ?? useCardEditor.getState().base })
    onOfferDone()
  }

  const discard = () => {
    dropDraft(slug)
    onOfferDone()
  }

  const Step = STEP_PAGES[step]
  // A new card in the guided way is saved once it has something to show and a name, like the mock-up; the other views
  // leave that to the server's check.
  const unfinished = slug === null && view === 'guided' && !(name.trim() && editor.shapedPath !== null && editor.pendingShape === null)
  const canSave = card !== null && !busy && !unfinished && (dirty || trouble?.kind === 'gone')

  return (
    <div className="min-w-0" ref={root}>
      <div className="sticky top-0 z-20 glass-strong border-b border-line">
        <div className="max-w-7xl mx-auto px-3 sm:px-4 py-2 flex flex-wrap items-center gap-2 min-w-0">
          <Link to={LIST_PATH} className="btn btn-icon btn-flat" aria-label={t('editor.back')} title={t('editor.back')}>
            <ArrowLeft size={16} />
          </Link>
          <div className="min-w-0 flex-1 basis-40">
            <div className="text-[11px] text-faint break-words hyphens-auto">{t('editor.crumb')}</div>
            <h1 className="font-semibold text-[15px] break-words hyphens-auto">{title}</h1>
          </div>
          {!card && lastValid && (
            <span className="text-[12px] text-muted break-words" data-testid="card-last-valid">
              {t('editor.lastValid', { time: clock(lastValid.at, i18n.language) })}
            </span>
          )}
          <div className="inline-flex flex-wrap rounded-lg bg-surface p-0.5 gap-0.5" role="group" aria-label={t('editor.view.label')}>
            {VIEWS.map((one) => (
              <button
                key={one}
                type="button"
                className={`px-3 h-8 rounded-md text-sm break-words hyphens-auto ${view === one ? 'bg-accent-soft text-ink font-medium' : 'text-muted'} disabled:opacity-50`}
                aria-pressed={view === one}
                disabled={one !== 'yaml' && !card}
                title={one !== 'yaml' && !card ? (firstLine ? t('editor.fixFirst', { line: firstLine }) : t('editor.fixFirstNoLine')) : undefined}
                onClick={() => (view === 'yaml' && one !== 'yaml' ? useCardEditor.getState().leaveYaml(one) : useCardEditor.getState().setView(one))}
              >
                {t(`editor.view.${one}`)}
              </button>
            ))}
          </div>
          {trouble?.kind === 'gone' ? (
            <button type="button" className="btn btn-accent" onClick={() => void doSave({ asNew: true })} disabled={busy || !card}>
              {t('cards.saveAsNew')}
            </button>
          ) : (
            <button type="button" className="btn btn-accent" onClick={() => void doSave()} disabled={!canSave}>
              {busy ? <Spinner /> : null}
              {t('editor.save')}
            </button>
          )}
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-3 sm:px-4 py-4 grid gap-4 min-w-0">
        {offer && (
          <div className="rounded-xl border border-accent/40 px-3 py-2 flex flex-wrap items-center gap-2" role="status">
            <div className="min-w-0 flex-1 basis-60">
              <div className="text-sm font-medium break-words hyphens-auto">{t('editor.restore.title')}</div>
              <div className="text-[13px] text-muted break-words hyphens-auto">{t('editor.restore.body', { time: clock(offer.at, i18n.language) })}</div>
            </div>
            <button type="button" className="btn btn-accent" onClick={restore}>
              {t('editor.restore.restore')}
            </button>
            <button type="button" className="btn btn-flat" onClick={discard}>
              {t('editor.restore.discard')}
            </button>
          </div>
        )}

        {replaced && (
          <div className="rounded-lg border border-warn/40 px-3 py-2 text-sm flex flex-wrap items-center gap-2" role="status" data-testid="card-replaced">
            <span className="min-w-0 flex-1 basis-60 break-words hyphens-auto">
              {t('editor.replaced.text', { place: t(replaced.place.key, { number: replaced.place.number }), what: t(`editor.replaced.what.${replaced.what}`), path: replaced.path })}
            </span>
            <button type="button" className="btn" onClick={() => useCardEditor.getState().undo()}>
              {t('editor.replaced.undo')}
            </button>
            <button type="button" className="btn btn-flat" onClick={() => useCardEditor.setState({ replaced: null })}>
              {t('editor.replaced.dismiss')}
            </button>
          </div>
        )}

        {trouble?.kind === 'gone' && (
          <div className="rounded-lg border border-warn/40 px-3 py-2 text-sm" role="alert">
            <strong>{t('cards.deletedMeanwhile')}</strong>
            <p className="text-muted">{t('cards.deletedBody')}</p>
          </div>
        )}
        {trouble?.kind === 'error' && (
          <p className="text-sm text-bad rounded-lg border border-bad/40 px-3 py-2" role="alert">
            {trouble.message}
          </p>
        )}

        {view === 'guided' ? (
          <div className="flex flex-col lg:flex-row gap-4 min-w-0">
            <div className="flex-1 min-w-0 grid gap-4 content-start">
              <ProblemList />
              <GuidedWay onSave={() => void doSave()} canSave={canSave} busy={busy} />
            </div>
            <aside className="lg:w-[420px] lg:flex-none min-w-0 lg:sticky lg:top-16 lg:self-start">
              <Preview guided />
            </aside>
          </div>
        ) : view === 'editor' ? (
          <>
            {refusal && (
              <p className="rounded-lg border border-line px-3 py-2 text-sm text-muted break-words hyphens-auto" role="note" data-testid="card-guided-refused">
                {t('editor.guided.why.text', { why: t(`editor.guided.why.${refusal}`) })}
              </p>
            )}
            <nav aria-label={t('editor.steps.label')}>
              <ol className="flex flex-wrap gap-1.5">
                {STEPS.map((one, index) => (
                  <li key={one}>
                    <button
                      type="button"
                      aria-current={step === one ? 'step' : undefined}
                      className={`h-9 px-3 rounded-xl border text-sm break-words hyphens-auto ${step === one ? 'border-accent/50 bg-accent-soft text-accent font-medium' : 'border-line text-muted hover:text-ink hover:bg-surface-hover'}`}
                      onClick={() => useCardEditor.getState().setStep(one)}
                    >
                      {t('editor.stepNumber', { number: index + 1, name: t(`editor.steps.${one}`) })}
                    </button>
                  </li>
                ))}
              </ol>
            </nav>
            <div className="flex flex-col lg:flex-row gap-4 min-w-0">
              <div className="flex-1 min-w-0 grid gap-4 content-start">
                <AdjustedBlock />
                <ProblemList />
                <Step />
              </div>
              <aside className="lg:w-[420px] lg:flex-none min-w-0">
                <Preview />
              </aside>
            </div>
          </>
        ) : (
          <div className="flex flex-col lg:flex-row gap-4 min-w-0">
            <div className="lg:flex-[2] min-w-0 grid gap-3 content-start">
              <Suspense
                fallback={
                  <div className="min-h-[420px] grid place-items-center" aria-label={t('editor.yaml.loading')}>
                    <Spinner />
                  </div>
                }
              >
                <YamlView onPastedValid={() => setToast(t('editor.yaml.pasted'))} />
              </Suspense>
              <ProblemList />
            </div>
            <aside className="lg:flex-1 min-w-0">
              <Preview />
            </aside>
          </div>
        )}
      </div>

      <Confirm open={guard.asking} title={t('editor.leave.title')} body={t('editor.leave.body')} danger confirmLabel={t('editor.leave.leave')} onCancel={guard.stay} onConfirm={guard.leave} />

      <Confirm
        open={askReload}
        title={t('editor.conflict.reloadTitle')}
        body={t('editor.conflict.reloadBody')}
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
        title={trouble?.kind === 'conflict' ? t('editor.conflict.title', { by: trouble.by }) : ''}
        footer={
          <>
            <button
              type="button"
              className="btn"
              onClick={() => {
                // Own changes are about to go, and the steps back with them: ask first.
                if (!isDirty(useCardEditor.getState())) return void reload()
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
        {trouble?.kind === 'conflict' && <p className="text-sm break-words hyphens-auto">{t('editor.conflict.body', { by: trouble.by, time: clock(trouble.at, i18n.language) })}</p>}
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
        <p className="text-sm break-words hyphens-auto">{t('editor.session.body')}</p>
      </Dialog>

      {toast && (
        <Toast level="ok" onClose={() => setToast('')}>
          {toast}
        </Toast>
      )}
    </div>
  )
}
