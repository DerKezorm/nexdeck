/**
 * "Ask nexdeck" (roadmap M3): the chat at the right edge, the board beside it.
 *
 * Narrow on purpose (420 px), so the card an answer is about stays in sight.
 * An answer cites where it looked as chips; a chip leads to the card or the
 * chronicle. A button the assistant proposes is drawn here with what it would
 * hit, and only a press of the person's own runs it. A dangerous one asks a
 * second time. Logs are read only after "Allow".
 */
import { ArrowLeft, ArrowUpRight, Lock, Plus, Send, Sparkles, Trash2, X } from 'lucide-react'
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

import { ApiError, del, get, post } from '../../api/client'
import { tLabel } from '../../i18n/texts'
import {
  factText,
  useAssistant,
  type Citation,
  type ConversationRow,
  type ConversationView,
  type DraftRef,
  type Permission,
  type Proposal,
  type Reply,
  type Turn,
} from '../../lib/assistant'
import { blocks, dayGroup, type Part } from '../../lib/assistantWords'
import { useAssistantTexts } from '../../lib/assistantTexts'
import { focusCard } from '../../lib/focusCard'
import { useEditorTexts } from '../../pages/cardEditor/editorTexts'
import { Confirm } from '../ui'

// The little preview of a draft is the editor's own, drawn with its words.
const DraftPreview = lazy(() => import('../../pages/cardEditor/DraftPreview').then((module) => ({ default: module.DraftPreview })))
const DraftSummary = lazy(() => import('../../pages/cardEditor/DraftPreview').then((module) => ({ default: module.DraftSummary })))

type Step = 'idle' | 'sure' | 'running' | 'done' | 'failed' | 'cancelled'
interface Pressed {
  step: Step
  message?: string
}

const KNOWN_ERRORS = ['off', 'auth', 'rate_limited', 'unreachable', 'busy', 'model', 'provider']

function Parts({ parts }: { parts: Part[] }) {
  return (
    <>
      {parts.map((part, index) => (part.bold ? <strong key={index}>{part.text}</strong> : <span key={index}>{part.text}</span>))}
    </>
  )
}

/** The answer's own words: paragraphs, lists and bold, nothing else. */
function Words({ text }: { text: string }) {
  return (
    <>
      {blocks(text).map((block, index) =>
        block.kind === 'p' ? (
          <p key={index} className="mb-1.5 last:mb-0">
            <Parts parts={block.parts} />
          </p>
        ) : (
          <ul key={index} className="mb-1.5 list-disc pl-5 last:mb-0">
            {block.items.map((item, at) => (
              <li key={at} className="my-0.5">
                <Parts parts={item} />
              </li>
            ))}
          </ul>
        ),
      )}
    </>
  )
}

function ProposalBox({ proposal, pressed, onPress }: { proposal: Proposal; pressed: Pressed; onPress: (next: Step) => void }) {
  const { t } = useTranslation()
  const label = tLabel(proposal.label)
  const finished = pressed.step === 'done' || pressed.step === 'failed' || pressed.step === 'cancelled'
  return (
    <div
      className={`mt-2 rounded-xl border p-3 ${proposal.danger ? 'border-bad/55 bg-bad/5' : 'border-line-strong bg-surface-hover'}`}
      data-testid="assistant-proposal"
    >
      <div className="text-sm font-semibold">
        {label}
        {proposal.row ? ` · ${proposal.row}` : ''}
      </div>
      <div className="text-[11px] text-faint">{proposal.card}</div>
      {proposal.impact.length > 0 && (
        <ul className="mt-1.5 text-[12.5px] text-muted">
          {proposal.impact.map((fact, index) => (
            <li key={index}>{factText(t, fact)}</li>
          ))}
        </ul>
      )}
      {pressed.step === 'sure' && <p className="mt-2 text-[12.5px] font-medium text-bad">{t('assistant.reallySure')}</p>}
      {finished ? (
        <p className={`mt-2 text-[12px] ${pressed.step === 'done' ? 'text-ok' : pressed.step === 'failed' ? 'text-bad' : 'text-muted'}`}>
          {pressed.step === 'done' ? t('assistant.ran', { message: tLabel(pressed.message ?? '') }) : pressed.step === 'failed' ? pressed.message : t('assistant.cancelled')}
        </p>
      ) : (
        <div className="mt-2 flex flex-wrap gap-1.5">
          <button
            type="button"
            className={`btn ${proposal.danger ? 'btn-danger' : 'btn-accent'}`}
            disabled={pressed.step === 'running'}
            onClick={() => onPress(proposal.danger && pressed.step === 'idle' ? 'sure' : 'running')}
          >
            {pressed.step === 'sure' ? t('assistant.reallyDo', { label }) : label}
          </button>
          <button type="button" className="btn" disabled={pressed.step === 'running'} onClick={() => onPress('cancelled')}>
            {t('common.cancel')}
          </button>
        </div>
      )}
    </div>
  )
}

function PermissionBox({ permission, outside, answered, onAnswer }: { permission: Permission; outside: boolean; answered: 'allowed' | 'denied' | undefined; onAnswer: (allow: boolean) => void }) {
  const { t } = useTranslation()
  const values = permission.kind === 'values'
  return (
    <div className="mt-2 rounded-xl border border-warn/50 p-3" data-testid="assistant-permission">
      <div className="flex items-center gap-2 text-sm font-semibold">
        <Lock size={14} className="text-warn" />
        {permission.kind === 'values' ? t('assistant.mayShareValues', { integration: permission.integration, path: permission.path }) : t('assistant.mayReadLog', { container: permission.container })}
      </div>
      <p className="mt-1 text-[12.5px] text-muted">{outside ? t(values ? 'assistant.valuesLeave' : 'assistant.logLeaves') : t(values ? 'assistant.valuesStay' : 'assistant.logStays')}</p>
      {answered ? (
        <p className="mt-2 text-[12px] text-muted">{answered === 'allowed' ? t('assistant.allowed') : t(values ? 'assistant.deniedValues' : 'assistant.denied')}</p>
      ) : (
        <div className="mt-2 flex gap-1.5">
          <button type="button" className="btn btn-accent" onClick={() => onAnswer(true)}>
            {t(values ? 'assistant.allowValues' : 'assistant.allow')}
          </button>
          <button type="button" className="btn" onClick={() => onAnswer(false)}>
            {t('assistant.deny')}
          </button>
        </div>
      )}
    </div>
  )
}

/** The words of the draft's preview and summary are the editor's; until they are there the box shows only the chip. */
function DraftBox({ draft, onOpen }: { draft: DraftRef; onOpen: () => void }) {
  const { t } = useTranslation()
  const ready = useEditorTexts()
  const [yaml, setYaml] = useState<string | null>(null)
  useEffect(() => {
    let gone = false
    get<{ yaml: string }>(`/assistant/drafts/${draft.id}`)
      .then((found) => {
        if (!gone) setYaml(found.yaml)
      })
      .catch(() => undefined)
    return () => {
      gone = true
    }
  }, [draft.id])
  return (
    <div className="mt-2 rounded-xl border border-line-strong bg-surface-hover p-3" data-testid="assistant-draft">
      <div className="text-sm font-semibold break-words">{draft.name || t('assistant.draft.untitled')}</div>
      {ready && (
        <Suspense fallback={null}>
          <div className="mt-2">{yaml !== null ? <DraftPreview yaml={yaml} /> : null}</div>
          <div className="mt-2">
            <DraftSummary summary={draft.summary} />
          </div>
        </Suspense>
      )}
      <p className="mt-2 text-[12px] text-muted">{draft.sent.values ? t('assistant.draft.sentValues') : t('assistant.draft.sentNoValues')}</p>
      <p className="mt-1 text-[12px] text-muted">{t('assistant.draft.keeps', { days: draft.keep_days })}</p>
      <div className="mt-2">
        <button type="button" className="btn btn-accent" onClick={onOpen}>
          <ArrowUpRight size={14} />
          {t('assistant.draft.open')}
        </button>
      </div>
    </div>
  )
}

/** The panel once its words are there; they come with it, not with the board. */
export function AssistantPanel({ open }: { open: boolean }) {
  const ready = useAssistantTexts()
  return ready ? <Panel open={open} /> : null
}

function Panel({ open }: { open: boolean }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const state = useAssistant((s) => s.state)
  const setOpen = useAssistant((s) => s.setOpen)
  const asking = useAssistant((s) => s.asking)
  const taken = useAssistant((s) => s.taken)
  const [view, setView] = useState<'chat' | 'history'>('chat')
  const [conversation, setConversation] = useState<number | null>(null)
  const [turns, setTurns] = useState<Turn[]>([])
  const [waiting, setWaiting] = useState(false)
  const [failure, setFailure] = useState('')
  const [draft, setDraft] = useState('')
  const [pressed, setPressed] = useState<Record<string, Pressed>>({})
  const [answers, setAnswers] = useState<Record<string, 'allowed' | 'denied'>>({})
  const [history, setHistory] = useState<ConversationRow[] | null>(null)
  const [clearing, setClearing] = useState(false)
  const box = useRef<HTMLTextAreaElement>(null)
  const log = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (open && view === 'chat') window.setTimeout(() => box.current?.focus(), 30)
  }, [open, view])
  useEffect(() => {
    if (log.current) log.current.scrollTop = log.current.scrollHeight
  }, [turns, waiting, failure])
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, setOpen])

  const send = useCallback(
    async (text: string, into: number | null = conversation, about = '') => {
      const question = text.trim()
      if (!question || waiting) return
      setFailure('')
      setTurns((current) => [...current, { me: true, text: question }])
      setWaiting(true)
      try {
        const reply = await post<Reply & { conversation_id: number }>('/assistant/chat', { text: question, conversation_id: into, ...(about ? { about } : {}) })
        setConversation(reply.conversation_id)
        setTurns((current) => [...current, { me: false, ...reply }])
      } catch (error) {
        const code = error instanceof ApiError ? error.code : ''
        setFailure(KNOWN_ERRORS.includes(code) ? t(`assistant.error.${code}`) : error instanceof ApiError ? error.message : t('errors.network'))
      } finally {
        setWaiting(false)
      }
    },
    [conversation, waiting, t],
  )

  // A question typed into Ctrl K arrives here, in a conversation of its own.
  // ⚠️ Taken out of the store before anything else: read from the render, it
  // was sent twice when the effect ran twice, and the second came back busy.
  useEffect(() => {
    if (!open || !asking || waiting) return
    const { asking: question, about } = useAssistant.getState()
    if (!question) return
    taken()
    setView('chat')
    setConversation(null)
    setTurns([])
    void send(question, null, about)
  }, [open, asking, waiting, taken, send])

  const fresh = () => {
    setConversation(null)
    setTurns([])
    setFailure('')
    setPressed({})
    setAnswers({})
    setView('chat')
  }

  const showHistory = async () => {
    setView('history')
    try {
      setHistory(await get<ConversationRow[]>('/assistant/conversations'))
    } catch {
      setHistory([])
    }
  }

  const reopen = async (id: number) => {
    try {
      const found = await get<ConversationView>(`/assistant/conversations/${id}`)
      setConversation(found.id)
      setTurns(found.turns)
      setPressed({})
      setAnswers({})
      setFailure('')
      setView('chat')
    } catch {
      setHistory((rows) => rows?.filter((row) => row.id !== id) ?? null)
    }
  }

  const forget = async (id: number) => {
    await del(`/assistant/conversations/${id}`)
    setHistory((rows) => rows?.filter((row) => row.id !== id) ?? null)
    if (conversation === id) fresh()
  }

  const go = (citation: Citation) => {
    if (citation.chronicle) {
      navigate('/chronicle')
      return
    }
    const target = citation.target
    if (!target) return
    // On a phone the chat covers the board; it steps aside for the card.
    if (window.matchMedia?.('(max-width: 639px)').matches) setOpen(false)
    if (focusCard(target.widget)) return
    navigate(`/b/${target.board}/${target.page}`, { state: { focus: target.widget } })
  }

  const openDraft = (draft: DraftRef) => {
    // On a phone the chat covers the page; it steps aside for the editor. The address is built here from the id.
    if (window.matchMedia?.('(max-width: 639px)').matches) setOpen(false)
    navigate(`/system/custom-cards/new?draft=${draft.id}`)
  }

  const press = async (key: string, proposal: Proposal, next: Step) => {
    setPressed((current) => ({ ...current, [key]: { step: next } }))
    if (next !== 'running') return
    try {
      const result = await post<{ message: string }>(`/widgets/${proposal.card_id}/actions/${proposal.action}`, { params: proposal.params, via: 'assistant' })
      setPressed((current) => ({ ...current, [key]: { step: 'done', message: result.message } }))
    } catch (error) {
      setPressed((current) => ({ ...current, [key]: { step: 'failed', message: error instanceof ApiError ? error.message : t('errors.network') } }))
    }
  }

  const answer = async (key: string, permission: Permission, allow: boolean) => {
    setAnswers((current) => ({ ...current, [key]: allow ? 'allowed' : 'denied' }))
    if (!allow || conversation === null) return
    try {
      await post(`/assistant/conversations/${conversation}/allow`, { grant: permission.grant })
      await send(permission.kind === 'values' ? t('assistant.allowedValuesFollowUp', { integration: `${permission.integration_kind || 'connection'} #${permission.integration_id}` }) : t('assistant.allowedFollowUp', { container: permission.container }))
    } catch (error) {
      setFailure(error instanceof ApiError ? error.message : t('errors.network'))
    }
  }

  const outside = state?.leaves_the_house ?? false
  const groups = (['today', 'yesterday', 'week', 'older'] as const)
    .map((group) => [group, (history ?? []).filter((row) => dayGroup(row.updated_at) === group)] as const)
    .filter(([, rows]) => rows.length)

  return (
    <aside
      className={`glass-strong fixed top-12 right-0 bottom-0 z-40 flex w-full flex-col rounded-none border-y-0 border-r-0 shadow-2xl sm:w-[420px] ${open ? '' : 'hidden'}`}
      aria-label={t('assistant.title')}
      data-testid="assistant-panel"
      // ⚠️ Its proposals to act stand inline, with the red button; no skin may dim or cover them (lib/skin/guard.ts).
      data-skin-guard=""
    >
      <header className="flex items-center gap-1 border-b border-line px-3 py-2">
        <Sparkles size={15} className="text-accent" />
        <h2 className="ml-1 flex-1 truncate text-[15px] font-semibold">{t('assistant.title')}</h2>
        <button type="button" className="btn btn-flat h-8 px-2 text-[12.5px]" onClick={fresh} title={t('assistant.new')}>
          <Plus size={14} /> {t('assistant.new')}
        </button>
        <button type="button" className="btn btn-flat h-8 px-2 text-[12.5px]" onClick={() => (view === 'history' ? setView('chat') : void showHistory())}>
          {view === 'history' ? <ArrowLeft size={14} /> : null}
          {view === 'history' ? t('common.back') : t('assistant.history')}
        </button>
        <button type="button" className="btn btn-icon btn-flat" onClick={() => setOpen(false)} aria-label={t('common.close')}>
          <X size={16} />
        </button>
      </header>
      {state && state.provider !== 'off' && (
        // One quiet line: which model answers, and whether questions leave the house.
        <p className="mx-3 mt-2 text-[11.5px] leading-snug text-faint" data-testid="assistant-privacy">
          <span className="font-medium text-muted">{state.model}</span>
          {' · '}
          {outside ? t(state.provider === 'anthropic' ? 'assistant.privacy.anthropic' : 'assistant.privacy.out') : t('assistant.privacy.home')}
        </p>
      )}

      {!state?.ready ? (
        <div className="flex flex-col gap-2 p-5">
          <b>{t('assistant.notSet')}</b>
          <span className="text-sm text-muted">{t('assistant.notSetHelp')}</span>
          <span>
            <button type="button" className="btn btn-accent" onClick={() => navigate('/system/assistant')}>
              {t('assistant.setUp')}
            </button>
          </span>
        </div>
      ) : view === 'history' ? (
        <div className="scroll min-h-0 flex-1 px-3 py-2" data-testid="assistant-history">
          {history === null && <p className="text-sm text-muted">…</p>}
          {history?.length === 0 && <p className="text-sm text-muted">{t('assistant.noHistory')}</p>}
          {groups.map(([group, rows]) => (
            <section key={group}>
              <h3 className="mt-3 mb-1 text-[11px] font-semibold uppercase tracking-wide text-faint">{t(`assistant.day.${group}`)}</h3>
              {rows.map((row) => (
                <div key={row.id} className="flex items-center gap-1 rounded-lg hover:bg-surface-hover">
                  <button type="button" className="min-w-0 flex-1 truncate px-2 py-1.5 text-left text-sm" onClick={() => void reopen(row.id)}>
                    {row.title}
                  </button>
                  <span className="text-[11px] text-faint">{new Date(row.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                  <button type="button" className="btn btn-icon btn-flat h-7 w-7" onClick={() => void forget(row.id)} aria-label={t('assistant.forget', { title: row.title })}>
                    <Trash2 size={13} />
                  </button>
                </div>
              ))}
            </section>
          ))}
          <p className="mt-4 text-[12px] text-muted">{t('assistant.keep', { days: state.keep_days })}</p>
          {!!history?.length && (
            <button type="button" className="btn btn-danger mt-2" onClick={() => setClearing(true)}>
              {t('assistant.forgetAll')}
            </button>
          )}
        </div>
      ) : (
        <>
          <div ref={log} className="scroll flex min-h-0 flex-1 flex-col gap-3 px-3 py-3" data-testid="assistant-log">
            {turns.length === 0 && !waiting && (
              <div className="flex flex-col gap-2.5 pt-2">
                <div className="text-[15px] font-semibold">{t('assistant.hello')}</div>
                <span className="text-[12.5px] text-muted">{t('assistant.helloHelp')}</span>
                <div className="flex flex-wrap gap-1.5">
                  {(['wrong', 'night', 'changed'] as const).map((key) => (
                    <button key={key} type="button" className="btn h-auto rounded-full px-3 py-1 text-[12.5px]" onClick={() => void send(t(`assistant.suggest.${key}`))}>
                      {t(`assistant.suggest.${key}`)}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {turns.map((turn, index) =>
              turn.me ? (
                <div key={index} className="max-w-[92%] self-end whitespace-pre-wrap rounded-2xl rounded-br-sm bg-accent-soft px-3 py-2 text-sm">
                  {turn.text}
                </div>
              ) : (
                <div key={index} className="max-w-[96%] self-start text-sm" data-testid="assistant-answer">
                  {turn.refused ? <p className="text-muted">{t('assistant.refused')}</p> : <Words text={turn.text || t('assistant.empty')} />}
                  {turn.proposals.map((proposal, at) => {
                    const key = `${index}-${at}`
                    return <ProposalBox key={key} proposal={proposal} pressed={pressed[key] ?? { step: 'idle' }} onPress={(next) => void press(key, proposal, next)} />
                  })}
                  {(turn.drafts ?? []).map((draft) => (
                    <DraftBox key={draft.id} draft={draft} onOpen={() => openDraft(draft)} />
                  ))}
                  {turn.permissions.map((permission, at) => {
                    const key = `${index}-${at}`
                    return <PermissionBox key={key} permission={permission} outside={outside} answered={answers[key]} onAnswer={(allow) => void answer(key, permission, allow)} />
                  })}
                  {turn.citations.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {turn.citations.map((citation, at) => (
                        <button
                          key={at}
                          type="button"
                          className="inline-flex items-center gap-1 rounded-full border border-line-strong px-2 py-0.5 text-[11px] text-muted hover:border-accent hover:text-ink"
                          onClick={() => go(citation)}
                        >
                          <ArrowUpRight size={11} />
                          {citation.chronicle ? t('chronicle.title') : citation.label}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ),
            )}
            {waiting && (
              <p className="text-[12.5px] text-faint" role="status">
                {t('assistant.thinking')}
              </p>
            )}
            {failure && (
              <p className="text-[12.5px] text-bad" role="alert">
                {failure}
              </p>
            )}
          </div>
          <form
            className="flex items-end gap-2 border-t border-line px-3 py-2.5"
            onSubmit={(event) => {
              event.preventDefault()
              const text = draft
              setDraft('')
              void send(text)
            }}
          >
            <textarea
              ref={box}
              rows={1}
              className="input max-h-32 min-h-10 flex-1 resize-none py-2"
              placeholder={t('assistant.placeholder')}
              aria-label={t('assistant.question')}
              value={draft}
              maxLength={4000}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  event.currentTarget.form?.requestSubmit()
                }
              }}
            />
            <button type="submit" className="btn btn-accent h-10" disabled={waiting || !draft.trim()} aria-label={t('assistant.send')}>
              <Send size={15} />
            </button>
          </form>
        </>
      )}
      <Confirm
        open={clearing}
        danger
        title={t('assistant.forgetAll')}
        body={t('assistant.forgetAllBody')}
        confirmLabel={t('assistant.forgetAll')}
        onCancel={() => setClearing(false)}
        onConfirm={() => {
          setClearing(false)
          void del('/assistant/conversations').then(() => {
            setHistory([])
            fresh()
          })
        }}
      />
    </aside>
  )
}
