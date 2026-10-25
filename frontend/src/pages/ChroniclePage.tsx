/**
 * The chronicle (roadmap M2): what changed, newest first, one heading a day.
 * Administrators see everything, others the lines about their boards; the
 * server decides that, the page only shows the filter that makes sense.
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, get } from '../api/client'
import { AppShell } from '../components/AppShell'
import { ChronicleRow } from '../components/ChronicleLines'
import { Spinner } from '../components/ui'
import { dayOf, type ChronicleLine } from '../lib/chronicle'
import { useAuth } from '../stores/auth'

const GROUPS = ['all', 'cards', 'versions', 'nexdeck'] as const
const WINDOWS = [1, 7, 30, 365] as const

interface Answer {
  events: ChronicleLine[]
  more: boolean
}

export function ChroniclePage() {
  const { t, i18n } = useTranslation()
  const admin = useAuth((state) => state.user?.role === 'admin')
  const [group, setGroup] = useState<(typeof GROUPS)[number]>('all')
  const [days, setDays] = useState<(typeof WINDOWS)[number]>(7)
  const [words, setWords] = useState('')
  const [asked, setAsked] = useState('')
  const [lines, setLines] = useState<ChronicleLine[]>([])
  const [more, setMore] = useState(false)
  const [busy, setBusy] = useState(true)
  const [failure, setFailure] = useState('')

  const address = (before?: number) => {
    const query = new URLSearchParams({ days: String(days), group, limit: '100' })
    if (asked) query.set('q', asked)
    if (before) query.set('before', String(before))
    return `/chronicle?${query.toString()}`
  }

  useEffect(() => {
    let current = true
    setBusy(true)
    setFailure('')
    get<Answer>(address())
      .then((answer) => {
        if (!current) return
        setLines(answer.events)
        setMore(answer.more)
      })
      .catch((error) => current && setFailure(error instanceof ApiError ? error.message : t('errors.network')))
      .finally(() => current && setBusy(false))
    return () => {
      current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [group, days, asked])

  const older = async () => {
    const last = lines[lines.length - 1]
    if (!last?.id) return
    setBusy(true)
    try {
      const answer = await get<Answer>(address(last.id))
      setLines((now) => [...now, ...answer.events])
      setMore(answer.more)
    } catch (error) {
      setFailure(error instanceof ApiError ? error.message : t('errors.network'))
    } finally {
      setBusy(false)
    }
  }

  // One heading a day, in the order the lines come.
  const blocks: { day: string; lines: ChronicleLine[] }[] = []
  for (const line of lines) {
    const day = dayOf(line.when, t, i18n.language)
    const last = blocks[blocks.length - 1]
    if (last && last.day === day) last.lines.push(line)
    else blocks.push({ day, lines: [line] })
  }

  const shownGroups = GROUPS.filter((one) => one !== 'nexdeck' || admin)
  return (
    <AppShell title={t('chronicle.title')}>
      <div className="max-w-3xl mx-auto px-4 py-6" data-testid="chronicle-page">
        <h1 className="text-lg font-semibold">{t('chronicle.title')}</h1>
        <p className="text-sm text-muted mt-1 mb-4">{admin ? t('chronicle.helpAdmin') : t('chronicle.help')}</p>
        <div className="flex flex-wrap items-center gap-2 mb-5 text-xs">
          <span className="inline-flex flex-wrap rounded-lg bg-surface p-0.5 gap-0.5" role="group" aria-label={t('chronicle.which')}>
            {shownGroups.map((one) => (
              <button key={one} type="button" className={`px-2.5 py-1 rounded-md ${group === one ? 'bg-accent-soft text-ink' : 'text-muted'}`} aria-pressed={group === one} onClick={() => setGroup(one)}>
                {t(`chronicle.group.${one}`)}
              </button>
            ))}
          </span>
          <span className="inline-flex flex-wrap rounded-lg bg-surface p-0.5 gap-0.5" role="group" aria-label={t('chronicle.window')}>
            {WINDOWS.map((one) => (
              <button key={one} type="button" className={`px-2.5 py-1 rounded-md ${days === one ? 'bg-accent-soft text-ink' : 'text-muted'}`} aria-pressed={days === one} onClick={() => setDays(one)}>
                {t(`chronicle.days.${one}`)}
              </button>
            ))}
          </span>
          <form
            className="flex-1 min-w-40"
            onSubmit={(event) => {
              event.preventDefault()
              setAsked(words.trim())
            }}
          >
            <input className="input h-8 w-full text-xs" type="search" value={words} onChange={(event) => setWords(event.target.value)} placeholder={t('chronicle.search')} aria-label={t('chronicle.search')} />
          </form>
        </div>
        {failure ? <p className="text-bad text-sm" role="alert">{failure}</p> : null}
        {!busy && !failure && lines.length === 0 ? <p className="text-sm text-muted" data-testid="chronicle-empty">{t('chronicle.empty')}</p> : null}
        <div className="flex flex-col gap-5">
          {blocks.map((block) => (
            <section key={block.day} aria-label={block.day}>
              <h2 className="text-[11px] uppercase tracking-wide text-faint mb-1.5">{block.day}</h2>
              <div className="flex flex-col gap-0.5">
                {block.lines.map((line) => <ChronicleRow key={line.id ?? `${line.kind}-${line.when}`} line={line} />)}
              </div>
            </section>
          ))}
        </div>
        {busy ? <div className="py-6 flex justify-center"><Spinner /></div> : null}
        {more && !busy ? (
          <button type="button" className="btn mt-5" onClick={() => void older()}>{t('chronicle.older')}</button>
        ) : null}
      </div>
    </AppShell>
  )
}
