/**
 * The attention card (roadmap M1): what needs a look, from every board of the
 * board's owner, or "All good". Built as the mock-up that was agreed on 24.10.2026:
 * a sentence on top with the count of red and yellow, red before yellow and
 * the newest first, a row leads to its card (or its service), what does not
 * fit becomes "Show 16 more" and opens the whole list. Updates and what is in
 * maintenance stand on quiet lines below and never colour the card.
 */
import { Check, Wrench, X } from 'lucide-react'
import { useLayoutEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

import { momentOf } from '../lib/chronicle'
import { focusCard } from '../lib/focusCard'
import { safeUrl } from '../lib/safeUrl'
import { useDisguise } from '../lib/showcase'
import { useBoxSize } from '../lib/useBoxSize'
import { useAuth } from '../stores/auth'
import { useNotices } from '../stores/notices'
import type { RenderProps } from './renderers'
import { wordedSubtitle } from './renderers'
import { ServiceIcon } from './ServiceIcon'
import { WhyLink } from './WhyLink'
import { Dialog } from './ui'

interface Row {
  title: string
  status: 'bad' | 'warn'
  source: 'card' | 'check' | 'bell'
  since?: number
  value?: string
  icon?: string
  url?: string
  notice?: number
  target?: { board: string; page: string; widget: number }
  /** Whom "Why?" asks about (roadmap M6). */
  subject?: string
  [key: string]: unknown
}

/** Below this height the card says its sentence and the worst row, no more. */
const SMALL = 130

export function AttentionCard({ data }: RenderProps) {
  const { t, i18n } = useTranslation()
  const disguise = useDisguise()
  const navigate = useNavigate()
  const user = useAuth((state) => state.user)
  const markRead = useNotices((state) => state.markRead)
  const openBell = useNotices((state) => state.setOpen)
  const [read, setRead] = useState<Set<number>>(() => new Set())
  const [whole, setWhole] = useState(false)
  const [note, setNote] = useState('')
  const frame = useRef<HTMLDivElement>(null)
  const list = useRef<HTMLDivElement>(null)
  const size = useBoxSize(frame)
  const [fit, setFit] = useState(Number.POSITIVE_INFINITY)

  const meta = data?.meta ?? {}
  const rows = ((data?.items ?? []) as Row[]).filter((row) => !(row.notice && read.has(row.notice)))
  const updates = Array.isArray(meta.updates) ? (meta.updates as { title: string; value: string }[]) : []
  const away = Array.isArray(meta.maintenance) ? (meta.maintenance as { title: string; until: string }[]) : []
  const counted = (meta.counted ?? {}) as { cards?: number; checks?: number; boards?: number }
  const opensService = meta.opens === 'service'
  const mayRead = user != null && meta.owner === user.id
  const small = size.height > 0 && size.height < SMALL
  const bad = rows.filter((row) => row.status === 'bad').length

  // Whole rows only: a row that would be cut in half goes under "N more".
  useLayoutEffect(() => {
    const box = list.current
    if (!box) return
    const limit = box.clientHeight
    let fits = 0
    for (const child of Array.from(box.children) as HTMLElement[]) {
      if (child.offsetTop + child.offsetHeight > limit + 1) break
      fits += 1
    }
    setFit(fits)
  }, [rows.length, size.height, size.width, small])

  const hiddenRows = Math.max(0, rows.length - fit)
  const time = (iso: string) => new Date(iso).toLocaleTimeString(i18n.language, { hour: '2-digit', minute: '2-digit' })

  const open = (row: Row) => {
    setNote('')
    if (row.source === 'bell') {
      const url = safeUrl(row.url)
      if (url) window.open(url, '_blank', 'noopener,noreferrer')
      else if (user) openBell(true)
      return
    }
    const url = safeUrl(row.url)
    if (opensService || !row.target) {
      if (url) window.open(url, '_blank', 'noopener,noreferrer')
      return
    }
    setWhole(false)
    if (focusCard(row.target.widget)) return
    // A wall display behind a kiosk link has no other board to go to.
    if (!user) {
      if (url) window.open(url, '_blank', 'noopener,noreferrer')
      else setNote(t('attention.elsewhere'))
      return
    }
    navigate(`/b/${row.target.board}/${row.target.page}`, { state: { focus: row.target.widget } })
  }

  const dismiss = (row: Row) => {
    if (!row.notice) return
    const number = row.notice
    setRead((old) => new Set(old).add(number))
    void markRead([number]).catch(() => setRead((old) => {
      const back = new Set(old)
      back.delete(number)
      return back
    }))
  }

  const line = (row: Row, compact: boolean) => {
    const when = row.since ? momentOf(row.since, i18n.language, t) : ''
    const place = row.source === 'bell' ? t('attention.notice') : row.value || ''
    const said = row.source === 'bell' ? when : when ? t('attention.since', { when }) : ''
    const meta = [place, t(`attention.source.${row.source}`), said].filter(Boolean).join(' · ')
    const subtitle = wordedSubtitle(row, t, i18n.language)
    return (
      <div key={`${row.source}-${row.notice ?? row.target?.widget ?? row.title}`} className="nd-att-row group" data-status={row.status}>
        <button type="button" className="nd-att-open" onClick={() => open(row)}>
          <span className="dot flex-none mt-[6px]" data-status={row.status} aria-hidden="true" />
          {row.icon ? <ServiceIcon icon={row.icon} size={16} className="flex-none mt-[1px]" /> : null}
          <span className="min-w-0 flex-1">
            <span className="block text-[13px] leading-snug">
              <b className="font-semibold">{disguise.free(row.title)}</b> {disguise.free(subtitle)}
            </span>
            {!compact && meta ? <span className="block text-[11px] text-muted truncate mt-px">{meta}</span> : null}
          </span>
        </button>
        {row.source !== 'bell' ? <WhyLink subject={row.subject} name={row.title} className="self-center px-1" /> : null}
        {row.source === 'bell' && mayRead ? (
          <button type="button" className="btn btn-icon h-6 w-6 btn-flat nd-att-read" onClick={() => dismiss(row)} aria-label={t('attention.markRead')} title={t('attention.markRead')}>
            <X size={13} />
          </button>
        ) : null}
      </div>
    )
  }

  const quiet = (
    <>
      {updates.length > 0 ? (
        <p className="nd-att-quiet" data-testid="attention-updates">
          <span className="text-accent font-bold" aria-hidden="true">↑</span>
          <span className="truncate">{t('attention.updates', { count: updates.length, list: updates.map((one) => `${one.title} ${one.value}`).join(', ') })}</span>
        </p>
      ) : null}
      {away.length > 0 ? (
        <p className="nd-att-quiet" data-testid="attention-away">
          <Wrench size={12} className="flex-none" aria-hidden="true" />
          <span className="truncate">{t('attention.away', { list: away.map((one) => t('attention.until', { name: one.title, time: time(one.until) })).join(', ') })}</span>
        </p>
      ) : null}
    </>
  )

  // ⚠️ Both faces start with the same element, so React keeps it and the
  // measured size follows the card from "All good" to a list and back.
  if (!rows.length) {
    const looked = [
      counted.cards != null ? t('attention.cards', { count: counted.cards }) : '',
      counted.checks ? t('attention.checks', { count: counted.checks }) : '',
      counted.boards && counted.boards > 1 ? t('attention.boards', { count: counted.boards }) : '',
    ].filter(Boolean).join(', ')
    return (
      <div ref={frame} className="flex-1 min-h-0 flex flex-col px-3 pb-3" data-testid="attention-fine">
        <div className={`flex-1 min-h-0 flex ${small ? 'flex-row items-center gap-2.5' : 'flex-col justify-center gap-1.5'}`}>
          <span className="nd-att-check" aria-hidden="true"><Check size={small ? 15 : 18} strokeWidth={3} /></span>
          <div className="min-w-0">
            <p className={`font-semibold leading-tight ${small ? 'text-[15px]' : 'text-[19px]'}`}>{t('attention.fine')}</p>
            {!small && looked ? <p className="text-[12px] text-muted mt-0.5">{looked}</p> : null}
          </div>
        </div>
        <div className="flex-none flex flex-col gap-1 mt-1">{quiet}</div>
      </div>
    )
  }

  return (
    <div ref={frame} className="flex-1 min-h-0 flex flex-col px-3 pb-2.5" data-testid="attention-rows">
      <div className={`flex-none flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5 ${small ? 'mb-0.5' : 'mb-1.5'}`}>
        <p className="text-[15px] font-bold leading-snug" data-testid="attention-head">{t('attention.need', { count: rows.length })}</p>
        {!small ? (
          <span className="flex gap-2 text-[11px] text-muted">
            {bad > 0 ? <span className="inline-flex items-center gap-1"><span className="dot" data-status="bad" aria-hidden="true" />{t('attention.red', { count: bad })}</span> : null}
            {rows.length - bad > 0 ? <span className="inline-flex items-center gap-1"><span className="dot" data-status="warn" aria-hidden="true" />{t('attention.yellow', { count: rows.length - bad })}</span> : null}
          </span>
        ) : null}
      </div>
      <div ref={list} className="relative flex-1 min-h-0 overflow-hidden -mx-1.5" data-testid="attention-list">
        {rows.map((row, index) => (
          <div key={index} className={index >= fit ? 'invisible' : ''} aria-hidden={index >= fit || undefined}>
            {line(row, small)}
          </div>
        ))}
      </div>
      <div className="flex-none flex flex-col gap-1 mt-1">
        {hiddenRows > 0 ? (
          <button type="button" className="nd-att-more" onClick={() => setWhole(true)} data-testid="attention-more">
            {t('attention.more', { count: hiddenRows })}
          </button>
        ) : null}
        {note ? <p className="text-[11px] text-muted">{note}</p> : null}
        {!small ? quiet : null}
      </div>
      {/* A dialog hangs at the page itself: a card with glass or tilt would hold a sheet inside it. */}
      <Dialog open={whole} onClose={() => setWhole(false)} title={t('attention.need', { count: rows.length })}>
        <div className="flex flex-col gap-0.5 -mx-2" data-testid="attention-whole">{rows.map((row) => line(row, false))}</div>
      </Dialog>
    </div>
  )
}
