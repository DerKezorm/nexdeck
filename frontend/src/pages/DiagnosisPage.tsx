/**
 * Why is this broken (roadmap M6): one page per service, for administrators.
 * Built as the mock-up agreed on 25.10.2026: a page of its own with two
 * columns, since when and the cause on top; on the left what happened in the
 * two hours before, the check and the cards, the log on asking; on the right
 * the chat, what it hangs on, the runbook and the buttons. Nothing repairs
 * itself; a button asks first and says what it would hit.
 */
import { ArrowLeft, ExternalLink, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { ApiError, get, post, put } from '../api/client'
import { ActionSheet, type PendingAction } from '../components/ActionSheet'
import { AppShell } from '../components/AppShell'
import { ServiceIcon } from '../components/ServiceIcon'
import { Spinner } from '../components/ui'
import { tLabel } from '../i18n/texts'
import { useAssistant } from '../lib/assistant'
import { clockOf, lineDetail, lineStatus, lineText, momentOf } from '../lib/chronicle'
import { diagnosisPath, lengthOf, type Diagnosis, type Runbook } from '../lib/diagnosis'
import { useLazyTexts } from '../lib/lazyTexts'
import { safeUrl } from '../lib/safeUrl'
import type { Action } from '../lib/types'
import { useAuth } from '../stores/auth'

export function DiagnosisPage() {
  const ready = useLazyTexts('diagnosis')
  const admin = useAuth((state) => state.user?.role === 'admin')
  if (!admin) return null
  return ready ? <Page /> : null
}

/** Markdown of a runbook, sanitised; fetched with the page, never with the board. */
let render: ((source: string) => string) | null = null
async function renderer(): Promise<(source: string) => string> {
  if (render) return render
  const [{ marked }, purify] = await Promise.all([import('marked'), import('dompurify')])
  render = (source: string) => purify.default.sanitize(marked.parse(source, { async: false }) as string)
  return render
}

function Section({ title, aside, children, testid }: { title: string; aside?: React.ReactNode; children: React.ReactNode; testid?: string }) {
  return (
    <section className="glass rounded-2xl p-4 min-w-0" data-testid={testid}>
      <h2 className="mb-2.5 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-faint">
        <span className="flex-1">{title}</span>
        {aside}
      </h2>
      {children}
    </section>
  )
}

function Page() {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const ref = params.get('ref') ?? ''
  const at = Number(params.get('at')) || undefined
  const [page, setPage] = useState<Diagnosis | null>(null)
  const [failure, setFailure] = useState('')
  const [busy, setBusy] = useState(true)

  const load = useCallback(async () => {
    setFailure('')
    try {
      const query = new URLSearchParams({ ref })
      if (at) query.set('at', String(at))
      setPage(await get<Diagnosis>(`/diagnosis?${query.toString()}`))
    } catch (error) {
      setPage(null)
      setFailure(error instanceof ApiError && error.code === 'not_found' ? t('diagnosis.notFound') : error instanceof ApiError ? error.message : t('errors.network'))
    } finally {
      setBusy(false)
    }
  }, [ref, at, t])

  useEffect(() => {
    setBusy(true)
    void load()
  }, [load])

  const moment = (seconds: number) => momentOf(seconds, i18n.language, t)
  return (
    <AppShell title={page?.subject.name ?? t('diagnosis.title')}>
      <div className="mx-auto max-w-6xl px-4 py-6" data-testid="diagnosis-page">
        <button type="button" className="mb-3 inline-flex items-center gap-1.5 text-[13px] text-muted hover:text-ink" onClick={() => navigate(-1)}>
          <ArrowLeft size={14} /> {t('diagnosis.back')}
        </button>
        {busy && !page ? <div className="flex justify-center py-10"><Spinner /></div> : null}
        {failure ? <p className="text-sm text-bad" role="alert">{failure}</p> : null}
        {page ? <Body page={page} reload={load} moment={moment} /> : null}
      </div>
    </AppShell>
  )
}

function Body({ page, reload, moment }: { page: Diagnosis; reload: () => Promise<void>; moment: (seconds: number) => string }) {
  const { t, i18n } = useTranslation()
  const { subject } = page
  const length = page.since ? lengthOf((page.until ?? page.window.to) - page.since, t) : ''
  let state: string
  if (page.state === 'ok') state = t('diagnosis.state.ok')
  else if (page.state === 'now') state = page.since ? t(`diagnosis.state.now_${page.level === 'warn' ? 'warn' : 'bad'}`, { when: moment(page.since) }) : t(`diagnosis.state.nowOpen_${page.level === 'warn' ? 'warn' : 'bad'}`)
  else state = page.until && page.since
    ? t(`diagnosis.state.past_${page.level === 'warn' ? 'warn' : 'bad'}`, { from: moment(page.since), to: clockOf(page.until, i18n.language) })
    : t(`diagnosis.state.pastOpen_${page.level === 'warn' ? 'warn' : 'bad'}`, { from: page.since ? moment(page.since) : '' })
  const tone = page.state === 'ok' ? 'ok' : page.state === 'past' ? 'ok' : page.level
  return (
    <>
      <header className="mb-4 flex items-start gap-3">
        <span className="flex h-11 w-11 flex-none items-center justify-center rounded-xl glass">
          <ServiceIcon icon={subject.icon ?? ''} size={26} />
        </span>
        <div className="min-w-0">
          <h1 className="text-xl font-semibold leading-tight">{subject.name}</h1>
          <p className="text-[12.5px] text-muted">{[t(`diagnosis.kind.${subject.kind}`), subject.engine, subject.detail].filter(Boolean).join(' · ')}</p>
          <p className="mt-1.5 inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[12.5px] font-semibold" data-tone={tone} data-testid="diagnosis-state"
            style={{ background: `color-mix(in srgb, var(--nd-${tone === 'warn' ? 'warn' : tone === 'bad' ? 'bad' : 'ok'}) 14%, transparent)`, color: `var(--nd-${tone === 'warn' ? 'warn' : tone === 'bad' ? 'bad' : 'ok'})` }}>
            <span className="dot" data-status={tone} aria-hidden="true" />
            {state}
            {length && page.state !== 'ok' ? <span className="font-normal opacity-80">({length})</span> : null}
          </p>
          {page.reason ? <p className="mt-1.5 text-[13px]">{tLabel(page.reason)}</p> : null}
        </div>
      </header>

      {page.cause ? (
        <div className="mb-4 flex items-center gap-3 rounded-xl border border-bad/40 bg-bad/10 px-3.5 py-2.5" data-testid="diagnosis-cause">
          <span className="min-w-0 flex-1 text-[13px]">
            {t(page.state === 'past' ? 'diagnosis.cause.past' : 'diagnosis.cause.now', { name: page.cause.name })}
            <span className="block text-[12px] text-muted">{t('diagnosis.cause.note', { name: subject.name })}</span>
          </span>
          <Link className="btn flex-none" to={diagnosisPath(page.cause.ref, page.state === 'past' && page.since ? page.since : undefined)}>{t('diagnosis.cause.open')}</Link>
        </div>
      ) : null}

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-4">
          <Happened page={page} />
          <Checks page={page} moment={moment} />
          <LogSection page={page} />
        </div>
        <div className="flex min-w-0 flex-col gap-4">
          <Ask page={page} />
          <HangsOn page={page} />
          <RunbookSection page={page} saved={reload} />
          <Buttons page={page} done={reload} />
        </div>
      </div>
    </>
  )
}

function Happened({ page }: { page: Diagnosis }) {
  const { t, i18n } = useTranslation()
  const marks: { at: number; text: string; ok: boolean }[] = []
  if (page.since) marks.push({ at: page.since, text: t('diagnosis.began', { time: clockOf(page.since, i18n.language) }), ok: false })
  if (page.until) marks.push({ at: page.until, text: t('diagnosis.ended', { time: clockOf(page.until, i18n.language) }), ok: true })
  // The marks stand among the lines by time; a line at the same second as the start comes after it.
  const rows: ({ mark: (typeof marks)[number] } | { line: Diagnosis['lines'][number] })[] = []
  let next = 0
  for (const line of page.lines) {
    while (next < marks.length && marks[next].at <= line.when) rows.push({ mark: marks[next++] })
    rows.push({ line })
  }
  while (next < marks.length) rows.push({ mark: marks[next++] })
  const windowWords = page.state === 'now' ? t('diagnosis.windowNow') : page.state === 'past' ? t('diagnosis.windowPast') : t('diagnosis.windowOk')
  return (
    <Section title={t('diagnosis.happened')} aside={<span className="font-normal normal-case tracking-normal">{windowWords}</span>} testid="diagnosis-lines">
      {page.lines.length === 0 ? <p className="text-[13px] text-muted">{t('diagnosis.nothingHappened')}</p> : null}
      <ol className="flex flex-col gap-1">
        {rows.map((row, index) => 'mark' in row ? (
          <li key={`mark-${index}`} className={`my-1 flex items-center gap-2 text-[11.5px] font-semibold ${row.mark.ok ? 'text-ok' : 'text-bad'}`} data-testid="diagnosis-mark">
            <span className="h-px flex-1 bg-current opacity-40" />{row.mark.text}<span className="h-px flex-1 bg-current opacity-40" />
          </li>
        ) : (
          <li key={row.line.id ?? `${row.line.kind}-${row.line.when}`} className="flex items-start gap-2" data-whose={row.line.whose === 'self' ? 'self' : 'above'}>
            <span className="num min-w-11 flex-none pt-[2px] text-[11px] text-faint">{clockOf(row.line.when, i18n.language)}</span>
            <span className="dot mt-[6px] flex-none" data-status={lineStatus(row.line)} aria-hidden="true" />
            <span className="min-w-0 flex-1 text-[13px] leading-snug">
              {lineText(row.line, t, i18n.language)}
              {row.line.via ? <span className="chip ml-1.5 !py-0 align-[1px] text-[10.5px] text-accent">{t('diagnosis.via', { name: row.line.via })}</span> : null}
              {lineDetail(row.line, t) ? <span className="block text-[11.5px] text-muted">{lineDetail(row.line, t)}</span> : null}
            </span>
          </li>
        ))}
      </ol>
      <Link className="mt-2 inline-block text-[12px] text-accent hover:underline" to="/chronicle">{t('diagnosis.readOn')}</Link>
    </Section>
  )
}

function Checks({ page, moment }: { page: Diagnosis; moment: (seconds: number) => string }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  return (
    <Section title={t('diagnosis.checksTitle')} testid="diagnosis-checks">
      {page.checks.length === 0 && page.cards.length === 0 ? <p className="text-[13px] text-muted">{t('diagnosis.noCards')}</p> : null}
      <ul className="flex flex-col gap-2 text-[13px]">
        {page.checks.map((check) => {
          const status = !check.enabled ? 'unknown' : check.ok === false ? 'bad' : check.ok ? 'ok' : 'unknown'
          const said = !check.enabled ? t('diagnosis.checkOff') : check.ok === false
            ? [tLabel(check.error), check.down_since ? t('diagnosis.checkDown', { when: moment(check.down_since) }) : ''].filter(Boolean).join(' · ')
            : check.ok ? [t('diagnosis.checkOk'), check.latency_ms != null ? `${check.latency_ms} ms` : ''].filter(Boolean).join(' · ') : t('diagnosis.checkUnknown')
          return (
            <li key={`check-${check.id}`} className="flex items-start gap-2">
              <span className="dot mt-[6px] flex-none" data-status={status} aria-hidden="true" />
              <span className="min-w-0 flex-1">
                <span className="block truncate">{check.kind.toUpperCase()} {check.target}</span>
                <span className="block text-[12px] text-muted">{said}</span>
              </span>
            </li>
          )
        })}
        {page.cards.map((card) => (
          <li key={`card-${card.id}`} className="flex items-start gap-2">
            <span className="dot mt-[6px] flex-none" data-status={card.status} aria-hidden="true" />
            <span className="min-w-0 flex-1">
              {card.target ? (
                <button type="button" className="block truncate text-left hover:underline" onClick={() => navigate(`/b/${card.target?.board}/${card.target?.page}`, { state: { focus: card.target?.widget } })}>
                  {tLabel(card.title)} <span className="text-muted">· {card.board}</span>
                </button>
              ) : <span className="block truncate">{tLabel(card.title)}</span>}
              {card.reason ? <span className="block text-[12px] text-muted">{tLabel(card.reason)}</span> : null}
            </span>
          </li>
        ))}
      </ul>
    </Section>
  )
}

function LogSection({ page }: { page: Diagnosis }) {
  const { t, i18n } = useTranslation()
  const [log, setLog] = useState<{ lines: string[]; read: number; container: string; engine: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState('')
  const place = page.log
  const read = async () => {
    setBusy(true)
    setFailure('')
    try {
      setLog(await post('/diagnosis/log', { ref: page.subject.ref }))
    } catch (error) {
      setFailure(error instanceof ApiError ? error.message : t('errors.network'))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Section title={t('diagnosis.log.title')} testid="diagnosis-log">
      {!place.available ? (
        <p className="text-[13px] text-muted">{t(`diagnosis.log.why.${place.why ?? 'no_container'}`, { engine: place.engine ?? '' })}</p>
      ) : !log ? (
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" className="btn" disabled={busy} onClick={() => void read()}>{busy ? <Spinner /> : null}{t('diagnosis.log.show')}</button>
          <span className="flex-1 text-[12px] text-muted">{t('diagnosis.log.help', { container: place.container, engine: place.engine })}</span>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <span className="flex-1 text-[12px] text-muted">{t('diagnosis.log.from', { container: log.container, engine: log.engine, count: log.lines.length, time: clockOf(log.read, i18n.language) })}</span>
            <button type="button" className="btn h-8" disabled={busy} onClick={() => void read()}><RefreshCw size={13} className={busy ? 'animate-spin' : ''} />{t('diagnosis.log.again')}</button>
            <button type="button" className="btn h-8" onClick={() => setLog(null)}>{t('diagnosis.log.hide')}</button>
          </div>
          {log.lines.length === 0 ? <p className="mt-2 text-[13px] text-muted">{t('diagnosis.log.empty')}</p> : (
            <pre className="scroll mt-2.5 max-h-80 overflow-auto rounded-lg border border-line bg-black/20 py-2 font-mono text-[11.5px] leading-relaxed" data-testid="diagnosis-log-lines">
              {log.lines.map((line, index) => (
                <span key={index} className={`block whitespace-pre-wrap break-words px-2.5 ${/\b(error|fatal|panic|exception)\b/i.test(line) ? 'bg-bad/10 text-bad' : /\bwarn(ing)?\b/i.test(line) ? 'text-warn' : ''}`}>{line}</span>
              ))}
            </pre>
          )}
        </>
      )}
      {failure ? <p className="mt-2 text-[12px] text-bad" role="alert">{failure}</p> : null}
    </Section>
  )
}

function Ask({ page }: { page: Diagnosis }) {
  const { t } = useTranslation()
  const ready = useAssistant((state) => state.state?.ready ?? false)
  const load = useAssistant((state) => state.load)
  const ask = useAssistant((state) => state.ask)
  useEffect(() => {
    if (useAssistant.getState().state === null) void load()
  }, [load])
  return (
    <Section title={t('diagnosis.ask.title')} testid="diagnosis-ask">
      {ready ? (
        <div className="flex items-center gap-3">
          <span className="flex-1 text-[12.5px] text-muted">{t('diagnosis.ask.help')}</span>
          <button type="button" className="btn btn-accent flex-none" onClick={() => ask(t(`diagnosis.ask.question_${page.state}`, { name: page.subject.name }), page.subject.ref)}>
            {t('diagnosis.ask.button')}
          </button>
        </div>
      ) : <p className="text-[12.5px] text-muted">{t('diagnosis.ask.off')}</p>}
    </Section>
  )
}

function HangsOn({ page }: { page: Diagnosis }) {
  const { t } = useTranslation()
  const node = (one: { ref: string; name: string; kind: string; detail: string; down: boolean }, me = false) => (
    <div className={`flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-[13px] ${me ? 'border-accent/50 bg-accent-soft' : 'border-line'}`} data-testid={me ? 'diagnosis-me' : 'diagnosis-above'}>
      <span className="dot flex-none" data-status={one.down ? 'bad' : 'ok'} aria-hidden="true" />
      <span className="min-w-0 flex-1">
        <span className="block truncate">{one.name}</span>
        <span className="block truncate text-[11.5px] text-muted">{me ? t('diagnosis.hangs.this') : [t(`diagnosis.kind.${one.kind}`, { defaultValue: one.kind }), one.detail].filter(Boolean).join(' · ')}</span>
      </span>
      {!me ? <span className={`text-[11.5px] ${one.down ? 'text-bad' : 'text-muted'}`}>{one.down ? t('diagnosis.hangs.down') : t('diagnosis.hangs.up')}</span> : null}
      {!me ? <Link className="text-[12px] text-accent hover:underline" to={diagnosisPath(one.ref)}>{t('diagnosis.hangs.open')}</Link> : null}
    </div>
  )
  return (
    <Section title={t('diagnosis.hangs.title')} testid="diagnosis-hangs">
      {page.above.length === 0 ? <p className="mb-2 text-[12.5px] text-muted">{t('diagnosis.hangs.nothing')}</p> : null}
      <div className="flex flex-col">
        {page.above.map((one) => (
          <div key={one.ref}>
            {node(one)}
            <div className="ml-5 h-3 w-px bg-line-strong" />
          </div>
        ))}
        {node({ ...page.subject, down: page.state === 'now' }, true)}
      </div>
      {page.below.length > 0 ? (
        <div className="mt-3">
          <p className="mb-1 text-[12px] text-muted">{t('diagnosis.hangs.carries')}</p>
          <ul className="flex flex-col gap-1 text-[12.5px]">
            {page.below.map((one) => (
              <li key={one.ref} className="flex items-center gap-2">
                <span className="dot flex-none" data-status={one.down ? 'bad' : 'ok'} aria-hidden="true" />
                <Link className="min-w-0 flex-1 truncate hover:underline" to={diagnosisPath(one.ref)}>{one.name}</Link>
                <span className="text-[11px] text-faint">{t(`diagnosis.kind.${one.kind}`, { defaultValue: one.kind })}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Section>
  )
}

function RunbookSection({ page, saved }: { page: Diagnosis; saved: () => Promise<void> }) {
  const { t, i18n } = useTranslation()
  const [runbook, setRunbook] = useState<Runbook>(page.runbook)
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(page.runbook.text)
  const [link, setLink] = useState(page.runbook.link)
  const [failure, setFailure] = useState('')
  const [html, setHtml] = useState('')
  useEffect(() => setRunbook(page.runbook), [page.runbook])
  useEffect(() => {
    let current = true
    if (!runbook.text) {
      setHtml('')
      return
    }
    void renderer().then((draw) => current && setHtml(draw(runbook.text))).catch(() => undefined)
    return () => {
      current = false
    }
  }, [runbook.text])
  const save = async () => {
    setFailure('')
    if (link.trim() && !/^https?:\/\//i.test(link.trim())) {
      setFailure(t('diagnosis.runbook.badLink'))
      return
    }
    try {
      setRunbook(await put<Runbook>('/diagnosis/runbook', { ref: page.subject.ref, text, link: link.trim() }))
      setEditing(false)
      void saved()
    } catch (error) {
      setFailure(error instanceof ApiError ? error.message : t('errors.network'))
    }
  }
  const start = () => {
    setText(runbook.text)
    setLink(runbook.link)
    setEditing(true)
  }
  const shownLink = safeUrl(runbook.link)
  return (
    <Section
      title={t('diagnosis.runbook.title')}
      aside={!editing && (runbook.text || runbook.link) ? <button type="button" className="btn h-7 normal-case tracking-normal" onClick={start}>{t('diagnosis.runbook.edit')}</button> : null}
      testid="diagnosis-runbook"
    >
      {editing ? (
        <div className="flex flex-col gap-2">
          <textarea className="input min-h-32 font-mono text-[12.5px]" value={text} onChange={(event) => setText(event.target.value)} aria-label={t('diagnosis.runbook.text')} maxLength={4000} />
          <input className="input text-[13px]" value={link} onChange={(event) => setLink(event.target.value)} placeholder={t('diagnosis.runbook.link')} aria-label={t('diagnosis.runbook.link')} />
          <p className="text-[11.5px] text-faint">{t('diagnosis.runbook.hint')}</p>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn" onClick={() => setEditing(false)}>{t('diagnosis.runbook.cancel')}</button>
            <button type="button" className="btn btn-accent" onClick={() => void save()}>{t('diagnosis.runbook.save')}</button>
          </div>
        </div>
      ) : runbook.text || runbook.link ? (
        <>
          {/* Sanitised by DOMPurify; the text is an administrator's, drawn in nexdeck's own origin. */}
          {html ? <div className="prose-card nd-runbook text-[13px]" dangerouslySetInnerHTML={{ __html: html }} /> : runbook.text ? <p className="whitespace-pre-wrap text-[13px]">{runbook.text}</p> : null}
          {shownLink ? (
            <a className="mt-2 inline-flex items-center gap-1.5 text-[12.5px] text-accent hover:underline" href={shownLink} target="_blank" rel="noopener noreferrer">
              <ExternalLink size={13} />{shownLink.replace(/^https?:\/\//, '')}
            </a>
          ) : null}
          {runbook.by && runbook.updated ? <p className="mt-2 text-[11px] text-faint">{t('diagnosis.runbook.by', { user: runbook.by, when: momentOf(runbook.updated, i18n.language, t) })}</p> : null}
        </>
      ) : (
        <>
          <p className="mb-2 text-[12.5px] text-muted">{t('diagnosis.runbook.empty')}</p>
          <button type="button" className="btn" onClick={start}>{t('diagnosis.runbook.write')}</button>
        </>
      )}
      {failure ? <p className="mt-2 text-[12px] text-bad" role="alert">{failure}</p> : null}
    </Section>
  )
}

function Buttons({ page, done }: { page: Diagnosis; done: () => Promise<void> }) {
  const { t } = useTranslation()
  const [pending, setPending] = useState<PendingAction | null>(null)
  const [said, setSaid] = useState<{ text: string; bad: boolean } | null>(null)
  const run = async (widgetId: number, action: Action) => {
    setPending(null)
    try {
      const result = await post<{ message: string }>(`/widgets/${widgetId}/actions/${action.id}`, { params: action.params ?? {} })
      setSaid({ text: tLabel(result.message) || t('diagnosis.buttons.done', { label: tLabel(action.label) }), bad: false })
      void done()
    } catch (error) {
      setSaid({ text: error instanceof ApiError ? error.message : t('errors.network'), bad: true })
    }
  }
  return (
    <Section title={t('diagnosis.buttons.title')} testid="diagnosis-buttons">
      {page.buttons.length === 0 ? <p className="text-[12.5px] text-muted">{t('diagnosis.buttons.none')}</p> : (
        <>
          {/* One container or guest, its buttons side by side. */}
          <p className="mb-2 truncate text-[13px] font-medium">{page.buttons[0].item}</p>
          <div className="flex flex-wrap gap-2">
            {page.buttons.map((one) => (
              <button
                key={`${one.widget_id}-${one.id}`}
                type="button"
                className={`btn h-8 ${one.danger ? 'text-bad' : ''}`}
                onClick={() => setPending({ widgetId: one.widget_id, action: { id: one.id, label: one.label, icon: one.icon, confirm: true, danger: one.danger, params: one.params }, values: {} })}
              >
                {tLabel(one.label)}
              </button>
            ))}
          </div>
          <p className="mt-2 text-[11.5px] text-faint">{t('diagnosis.buttons.from', { card: tLabel(page.buttons[0].card) })}</p>
        </>
      )}
      {said ? <p className={`mt-2 text-[12px] ${said.bad ? 'text-bad' : 'text-ok'}`} role="status">{said.text}</p> : null}
      <ActionSheet pending={pending} onChange={setPending} onCancel={() => setPending(null)} onRun={(widgetId, action) => void run(widgetId, action)} />
    </Section>
  )
}
