import { Sparkles } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'

import { useAssistant } from '../../lib/assistant'
import { problemText } from '../../lib/customCards'
import { Spinner } from '../../components/ui'
import { isFresh, useCardAi, type AiProposal } from './ai'
import { useConnections } from './connections'
import { DraftPreview } from './DraftPreview'
import { useCardEditor } from './store'

/** Whether "Ask AI" is on offer: the provider of "Ask nexdeck" is set up (KARTEN-17 AC-1). Loads what it needs once. */
export function useAiReady(): boolean {
  const ready = useAssistant((state) => state.state?.ready === true)
  useEffect(() => {
    if (useAssistant.getState().state === null) void useAssistant.getState().load()
  }, [])
  // The provider went (EC-6): nothing of the panel stays, a request that ran is stopped.
  useEffect(() => {
    if (!ready) useCardAi.getState().reset()
  }, [ready])
  return ready
}

/** The button on top of the editor, in all three views; it opens and closes the panel. */
export function AiButton() {
  const { t } = useTranslation()
  const open = useCardAi((state) => state.open)
  return (
    <button
      type="button"
      className={`btn ${open ? 'btn-accent' : ''}`}
      aria-pressed={open}
      aria-controls="card-ai"
      onClick={() => useCardAi.getState().setOpen(!open)}
    >
      <Sparkles size={14} />
      {t('editor.ai.button')}
    </button>
  )
}

function Summary({ proposal }: { proposal: AiProposal }) {
  const { t } = useTranslation()
  const { summary } = proposal
  return (
    <dl className="grid gap-1 text-[13px] min-w-0" data-testid="card-ai-summary">
      <div className="flex flex-wrap gap-x-2">
        <dt className="text-muted">{t('editor.ai.summary.connection')}</dt>
        <dd className="break-words">{summary.connection_kind ?? t('editor.ai.summary.none')}</dd>
      </div>
      <div className="flex flex-wrap gap-x-2">
        <dt className="text-muted">{t('editor.ai.summary.path')}</dt>
        <dd className="font-mono break-all">{summary.path ?? t('editor.ai.summary.none')}</dd>
      </div>
      <div className="flex flex-wrap gap-x-2">
        <dt className="text-muted">{t('editor.ai.summary.form')}</dt>
        <dd>{t(`editor.ai.summary.forms.${summary.form}`, { defaultValue: summary.form })}</dd>
      </div>
      <div className="flex flex-wrap gap-x-2">
        <dt className="text-muted">{t('editor.ai.summary.buttons')}</dt>
        <dd>{summary.buttons ? t('editor.ai.summary.withButtons') : t('editor.ai.summary.readOnly')}</dd>
      </div>
    </dl>
  )
}

function Proposed({ proposal }: { proposal: AiProposal }) {
  const { t } = useTranslation()
  return (
    <div className="rounded-xl border border-line px-3 py-3 grid gap-3 min-w-0" role="region" aria-label={t('editor.ai.proposal')} data-testid="card-ai-proposal">
      <h3 className="text-sm font-medium break-words hyphens-auto">{proposal.ok ? t('editor.ai.proposal') : t('editor.ai.notValid')}</h3>
      {proposal.ok ? (
        <div className="flex flex-col sm:flex-row gap-3 min-w-0">
          <div className="min-w-0 sm:flex-1">
            <DraftPreview yaml={proposal.yaml} />
          </div>
          <div className="min-w-0 sm:flex-1 grid gap-2 content-start">
            <Summary proposal={proposal} />
          </div>
        </div>
      ) : (
        <div className="grid gap-2 min-w-0">
          <p className="text-[13px] text-muted break-words hyphens-auto">{t('editor.ai.notValidBody')}</p>
          <ul className="text-[13px] space-y-1" data-testid="card-ai-problems">
            {(proposal.problems ?? []).map((problem, index) => (
              <li key={index} className="break-words">
                {problem.line !== null ? <span className="text-faint">{t('cards.line', { line: problem.line })} · </span> : null}
                {problemText(t, problem)}
              </li>
            ))}
          </ul>
          <pre className="rounded-lg bg-surface px-3 py-2 text-[12px] overflow-auto max-h-64 whitespace-pre-wrap break-words">{proposal.yaml}</pre>
        </div>
      )}
      <p className="text-[12px] text-faint break-words hyphens-auto">{proposal.sent.values ? t('editor.ai.sentValues') : t('editor.ai.sentNoValues')}</p>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn btn-accent" onClick={() => useCardAi.getState().accept()}>
          {proposal.ok ? t('editor.ai.accept') : t('editor.ai.takeAnyway')}
        </button>
        <button type="button" className="btn btn-flat" onClick={() => useCardAi.getState().discard()}>
          {t('editor.ai.discard')}
        </button>
      </div>
    </div>
  )
}

/**
 * "Ask AI" (KARTEN-17): a sentence in, a card out, as a proposal beside the editor's own text. The sentence under the
 * field says who is asked and what goes out (AC-9). One request at a time (AC-8), Cancel while it runs.
 */
export function AiPanel() {
  const { t } = useTranslation()
  const state = useAssistant((s) => s.state)
  const { description, values, running, error, proposal } = useCardAi()
  const { chosen } = useConnections()
  const card = useCardEditor((s) => s.card)
  const box = useRef<HTMLTextAreaElement>(null)
  const fresh = useCardEditor((s) => isFresh(s))
  useEffect(() => {
    box.current?.focus()
  }, [])

  const ask = (mode: 'new' | 'change' | 'translate') => void useCardAi.getState().ask(mode, chosen?.id ?? null, t)
  const main = fresh ? 'new' : 'change'
  const providerName = state?.provider === 'anthropic' ? t('editor.ai.provider.anthropic') : t('editor.ai.provider.openai')

  return (
    <section id="card-ai" className="glass rounded-2xl p-4 sm:p-5 min-w-0 grid gap-3" aria-labelledby="card-ai-title" data-testid="card-ai">
      <h2 id="card-ai-title" className="font-semibold text-[15px] break-words hyphens-auto">
        {t('editor.ai.title')}
      </h2>
      <label className="grid gap-1 min-w-0">
        <span className="text-sm font-medium break-words hyphens-auto">{fresh ? t('editor.ai.describeNew') : t('editor.ai.describeChange')}</span>
        <textarea
          ref={box}
          className="input min-h-20 py-2"
          rows={3}
          maxLength={2000}
          value={description}
          placeholder={fresh ? t('editor.ai.placeholderNew') : t('editor.ai.placeholderChange')}
          onChange={(event) => useCardAi.getState().setDescription(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && description.trim() && !running && card) {
              event.preventDefault()
              ask(main)
            }
          }}
        />
      </label>
      <label className="flex items-start gap-2 text-sm min-w-0">
        <input type="checkbox" className="mt-1" checked={values} onChange={(event) => useCardAi.getState().setValues(event.target.checked)} />
        <span className="break-words hyphens-auto">{t('editor.ai.values')}</span>
      </label>
      <p className="text-[12px] text-muted break-words hyphens-auto" data-testid="card-ai-hint">
        {t(state?.leaves_the_house === false ? 'editor.ai.hintHome' : 'editor.ai.hintOut', { provider: providerName, model: state?.model ?? '' })}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className="btn btn-accent" disabled={running || !card || !description.trim()} onClick={() => ask(main)}>
          {running ? <Spinner /> : null}
          {fresh ? t('editor.ai.create') : t('editor.ai.change')}
        </button>
        <button type="button" className="btn" disabled={running || !card || fresh} onClick={() => ask('translate')}>
          {t('editor.ai.translate')}
        </button>
        {running && (
          <button type="button" className="btn btn-flat" onClick={() => useCardAi.getState().cancel()}>
            {t('common.cancel')}
          </button>
        )}
      </div>
      {running && (
        <p className="text-[12px] text-muted" role="status">
          {t('editor.ai.working')}
        </p>
      )}
      {error && (
        <p className="text-sm text-bad rounded-lg border border-bad/40 px-3 py-2 break-words hyphens-auto" role="alert" data-testid="card-ai-error">
          {error}
        </p>
      )}
      {proposal && <Proposed proposal={proposal} />}
    </section>
  )
}
