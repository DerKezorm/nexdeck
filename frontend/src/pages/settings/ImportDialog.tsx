import { useQuery, useQueryClient } from '@tanstack/react-query'
import { lazy, Suspense, useState, type ChangeEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { get, post } from '../../api/client'
import { ServiceIcon } from '../../components/ServiceIcon'
import { Dialog, Field } from '../../components/ui'
import {
  cardTextOf,
  documentKey,
  IMPORT_MAX_BYTES,
  importFailure,
  sourceKind,
  type ImportCheck,
  type ImportChoice,
  type ImportDocument,
  type ImportSource,
} from '../../lib/cardExchange'
import { pickText } from '../../lib/cardText'
import { problemText, type CardForm, type CardSource } from '../../lib/customCards'

const ImportPreview = lazy(() => import('./ImportPreview'))

/** What a person may answer for a document that exists already; "cancel" stops the whole import. */
type Answer = ImportChoice | 'cancel'
const ANSWERS: Answer[] = ['replace', 'copy', 'cancel']

const FORMS: CardForm[] = ['value', 'stats', 'list', 'posters', 'builder']

/** The queries that show cards and integrations, refreshed when something came in. */
const LISTS = [['custom-cards'], ['cards-library'], ['own-integrations'], ['adapters'], ['cards-sources'], ['integrations']]

/** The icon of the first source of a document, if the check named one. */
function firstIcon(document: ImportDocument, known: CardSource[]): string {
  const first = (document.requires ?? [])[0]
  if (!first) return ''
  return typeof first === 'object' ? (first.icon ?? '') : (known.find((one) => one.kind === first)?.icon ?? '')
}

/** The kinds of connection the installation knows, to word the sources of a card as people read them. */
function useKnownKinds() {
  const known = useQuery({ queryKey: ['cards-sources'], queryFn: () => get<CardSource[]>('/cards/sources'), staleTime: 60_000 })
  return Array.isArray(known.data) ? known.data : []
}

/**
 * Import of cards and integrations from a file or from pasted text (KARTEN-12 AC-2 to AC-4, EC-7).
 *
 * Two steps: the text goes to the server's check, which names every document in it with its source, buttons and
 * problems; then the administrator decides about what exists already and imports. Nothing is made before that.
 */
export function ImportDialog({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const [text, setText] = useState('')
  const [checked, setChecked] = useState<{ text: string; result: ImportCheck } | null>(null)
  const [answers, setAnswers] = useState<Record<string, Answer>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const lang = i18n.language
  const known = useKnownKinds()
  const iconOf = (source: ImportSource) => (typeof source === 'object' && source.icon) || known.find((one) => one.kind === sourceKind(source))?.icon || sourceKind(source)
  const labelOf = (source: ImportSource) => (typeof source === 'object' && source.label) || known.find((one) => one.kind === sourceKind(source))?.label || sourceKind(source).replace(/^custom:/, '')
  // A result belongs to the text it was made for; once the text changes it is stale and goes.
  const result = checked && checked.text === text ? checked.result : null
  const documents = result?.documents ?? []

  const fail = (failure: unknown) => setError(importFailure(t, failure))

  const pick = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setError('')
    if (file.size > IMPORT_MAX_BYTES) {
      setError(t('cards.exchange.tooBig'))
      return
    }
    setText(await file.text())
  }

  const check = () => {
    setBusy(true)
    setError('')
    const sent = text
    post<ImportCheck>('/cards/import/check', { text: sent })
      .then((answer) => {
        setChecked({ text: sent, result: { documents: answer.documents ?? [], missing_integrations: answer.missing_integrations ?? [] } })
        setAnswers({})
      })
      .catch(fail)
      .finally(() => setBusy(false))
  }

  const problems = documents.some((document) => (document.problems ?? []).length > 0)
  const undecided = documents.filter((document) => document.exists && !answers[documentKey(document)])
  const stopped = Object.values(answers).includes('cancel')
  const ready = result !== null && documents.length > 0 && !problems && undecided.length === 0 && !stopped

  const close = () => {
    setText('')
    setChecked(null)
    setAnswers({})
    setError('')
    onClose()
  }

  const run = () => {
    setBusy(true)
    setError('')
    const choices: Record<string, ImportChoice> = {}
    for (const document of documents) if (document.exists) choices[documentKey(document)] = answers[documentKey(document)] as ImportChoice
    post('/cards/import', { text, choices })
      .then(async () => {
        await Promise.all(LISTS.map((queryKey) => queryClient.invalidateQueries({ queryKey })))
        onDone()
        close()
      })
      .catch(fail)
      .finally(() => setBusy(false))
  }

  const comesAlong = (document: ImportDocument, source: ImportSource) => {
    const kind = sourceKind(source)
    return kind.startsWith('custom:') && documents.some((other) => other.type === 'integration' && other.short === kind.slice(7)) && document.type === 'card'
  }

  return (
    <Dialog
      open={open}
      onClose={close}
      title={t('cards.exchange.title')}
      size="lg"
      footer={
        <>
          <button className="btn" onClick={close}>
            {t('common.cancel')}
          </button>
          {result === null ? (
            <button className="btn btn-accent" disabled={busy || !text.trim()} onClick={check}>
              {t('cards.exchange.check')}
            </button>
          ) : (
            <button className="btn btn-accent" disabled={busy || !ready} onClick={run}>
              {t('cards.exchange.run')}
            </button>
          )}
        </>
      }
    >
      <p className="text-sm text-muted mb-3">{t('cards.exchange.lead')}</p>
      <div className="flex flex-wrap items-center gap-2 mb-2">
        <label className="btn cursor-pointer focus-within:border-accent focus-within:text-accent">
          {t('cards.exchange.pick')}
          <input type="file" accept=".yaml,.yml,.txt" className="sr-only" aria-label={t('cards.exchange.pick')} onChange={(event) => void pick(event)} />
        </label>
      </div>
      <Field label={t('cards.exchange.paste')} htmlFor="import-text">
        <textarea id="import-text" className="input font-mono text-xs" rows={8} value={text} spellCheck={false} onChange={(event) => setText(event.target.value)} placeholder="nexdeck-card: 1&#10;slug: …" />
      </Field>
      {error && (
        <p className="text-sm text-bad mb-3" role="alert">
          {error}
        </p>
      )}

      {result !== null && documents.length === 0 && <p className="text-sm text-muted">{t('cards.exchange.empty')}</p>}

      {result !== null && (result.missing_integrations ?? []).length > 0 && (
        <p className="text-sm text-warn mb-3" role="note" data-testid="import-missing">
          {t('cards.exchange.missing', { kinds: result.missing_integrations.map((kind) => kind.replace(/^custom:/, '')).join(', ') })}
        </p>
      )}

      {documents.length > 0 && (
        <ul className="grid gap-3" aria-label={t('cards.exchange.documents')}>
          {documents.map((document, position) => {
            const key = documentKey(document)
            const name = pickText(document.name, lang) || (document.type === 'card' ? document.slug : document.short) || ''
            const own = document.problems ?? []
            const form = (FORMS.includes(document.form as CardForm) ? document.form : 'value') as CardForm
            const yaml = document.type === 'card' && own.length === 0 && document.slug && result ? cardTextOf(text, document.slug) : null
            const buttons = document.buttons ?? []
            return (
              <li key={`${key}-${position}`} className="rounded-xl border border-line p-3 min-w-0" data-testid={`import-doc-${key}`}>
                <div className="flex flex-wrap items-center gap-2 min-w-0">
                  {document.type !== 'unknown' && <span className="chip !py-0">{t(document.type === 'card' ? 'cards.exchange.card' : 'cards.exchange.integration')}</span>}
                  <span className="text-sm font-medium break-words min-w-0">{name}</span>
                  {document.type !== 'unknown' && <span className="text-[11px] text-muted break-all">{key.slice(key.indexOf(':') + 1)}</span>}
                </div>

                {(document.requires ?? []).length > 0 && (
                  <div className="mt-2 text-sm">
                    <span className="text-[11px] text-faint mr-1.5">{t('cards.exchange.source')}</span>
                    <ul className="inline-flex flex-wrap gap-x-3 gap-y-1">
                      {(document.requires ?? []).map((source) => (
                        <li key={sourceKind(source)} className="inline-flex items-center gap-1.5">
                          <ServiceIcon icon={iconOf(source)} size={16} />
                          {labelOf(source)}
                          {comesAlong(document, source) && <span className="text-[11px] text-muted">{t('cards.exchange.comesAlong')}</span>}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {document.type === 'card' && (
                  <div className="mt-2 text-sm">
                    <span className="text-[11px] text-faint mr-1.5">{t('cards.exchange.buttons')}</span>
                    {buttons.length === 0 ? (
                      <span className="text-muted">{t('cards.exchange.noButtons')}</span>
                    ) : (
                      <ul className="mt-1 grid gap-0.5">
                        {buttons.map((button, index) => (
                          <li key={index} className="text-[12px] break-words">
                            {pickText(button.label, lang)} <span className="font-mono text-muted">{button.method} {button.path}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}

                {own.length > 0 && (
                  <ul className="mt-2 grid gap-0.5" aria-label={t('cards.exchange.problems')} data-testid="import-problems">
                    {own.map((problem, index) => (
                      <li key={index} className="text-[12px] text-bad break-words">
                        {problem.line !== null && problem.line !== undefined && <span className="font-mono">{t('cards.line', { line: problem.line })}: </span>}
                        {problemText(t, problem)}
                      </li>
                    ))}
                  </ul>
                )}

                {yaml !== null && (
                  <div className="mt-3">
                    <p className="text-[11px] text-faint mb-1">{t('cards.exchange.preview')}</p>
                    <Suspense fallback={null}>
                      <ImportPreview yaml={yaml} form={form} name={document.name} icon={firstIcon(document, known)} />
                    </Suspense>
                  </div>
                )}

                {document.exists && (
                  <fieldset className="mt-3" data-testid={`import-conflict-${key}`}>
                    <legend className="text-[12px] text-warn mb-1">{t(document.same ? 'cards.exchange.existsSame' : 'cards.exchange.exists')}</legend>
                    <div className="flex flex-wrap gap-x-4 gap-y-1">
                      {ANSWERS.map((answer) => (
                        <label key={answer} className="inline-flex items-center gap-1.5 text-sm">
                          <input type="radio" className="accent-accent" name={`answer-${key}`} checked={answers[key] === answer} onChange={() => setAnswers((current) => ({ ...current, [key]: answer }))} />
                          {t(`cards.exchange.${answer}`)}
                        </label>
                      ))}
                    </div>
                  </fieldset>
                )}
              </li>
            )
          })}
        </ul>
      )}

      {result !== null && documents.length > 0 && (
        <p className="text-[12px] text-muted mt-3" role="status">
          {stopped ? t('cards.exchange.stopped') : problems ? t('cards.exchange.fixFirst') : undecided.length > 0 ? t('cards.exchange.chooseFirst') : ''}
        </p>
      )}
    </Dialog>
  )
}
