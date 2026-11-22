/**
 * A checklist or a row of notes, for the cards of a notes app (nexnotes): one note with its items to tick off, or the
 * pinned notes, each opening itself.
 *
 * What the server hands over (``meta.mode``):
 * - ``note``: ``items`` are the checklist items (``checked``, ``depth``, an ``actions`` entry when it may be ticked
 *   here), the open ones first; ``meta.title``, ``meta.done``/``meta.total``, ``meta.more`` (items that did not fit),
 *   ``meta.lines`` (a note without a checklist), ``meta.check_note`` (why nothing can be ticked).
 * - ``pinned``: ``items`` are notes (``title``, ``subtitle`` = first line, ``url``, ``done``/``total``, ``owner``);
 *   ``meta.more`` the pinned notes that did not fit.
 *
 * ⚠️ Drawn anew only when what it shows changed (``drawnAs``): the card asks every 30 seconds, and on a kitchen
 * tablet a list that redraws itself twice a minute flickers under a finger. While the service cannot be reached
 * (``meta.offline``) the last state stays with an orange line saying since when, and nothing can be ticked.
 */
import { CheckCircle2, Circle } from 'lucide-react'
import { memo, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { tLabel } from '../i18n/texts'
import { safeUrl } from '../lib/safeUrl'
import { useDisguise } from '../lib/showcase'
import type { Action } from '../lib/types'
import type { RenderProps } from './renderers'

/** How long a tick stays drawn as pressed when no new answer with a new stamp arrives. */
const HOLD_MS = 4000

type Row = Record<string, unknown>

function numberOf(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/** When the shown state was read, in the viewer's words: the time today, with the day before that. */
export function asOfText(seconds: number | null, language: string): string {
  if (seconds === null) return ''
  const when = new Date(seconds * 1000)
  const sameDay = when.toDateString() === new Date().toDateString()
  return sameDay
    ? when.toLocaleTimeString(language, { hour: '2-digit', minute: '2-digit' })
    : when.toLocaleString(language, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

/** Everything the card draws, as one string: the same string, the same picture. */
export function drawnAs({ data, canAct, editing }: RenderProps): string {
  const meta = data?.meta ?? {}
  const rows = (data?.items ?? []).map((item) => `${String(item.id)}:${item.checked ? 1 : 0}:${Array.isArray(item.actions) && item.actions.length ? 1 : 0}:${String(item.title ?? '')}`)
  return JSON.stringify([
    meta.stamp, meta.mode, meta.title, meta.done, meta.total, meta.more, meta.lines, meta.check_note, meta.offline,
    meta.as_of, data?.error ?? '', canAct ? 1 : 0, editing ? 1 : 0, rows,
  ])
}

/** How far a checklist is: "3 of 8" beside a note's title, "3/8" on a row of pinned notes, where the title needs the room. */
function Progress({ done, total, compact = false }: { done: number; total: number; compact?: boolean }) {
  const { t } = useTranslation()
  const share = total ? Math.round((done / total) * 100) : 0
  const words = t('checklist.progress', { done, total })
  return (
    <span className="flex items-center gap-1.5 shrink-0" data-testid="checklist-progress" title={compact ? words : undefined}>
      <span className="num text-[11px] text-muted whitespace-nowrap">{compact ? `${done}/${total}` : words}</span>
      <span className={`bar ${compact ? 'w-6' : 'w-10'}`} data-status={done === total ? 'ok' : 'unknown'} aria-hidden="true">
        <i style={{ width: `${share}%` }} />
      </span>
    </span>
  )
}

function Footer({ data, name }: { data: RenderProps['data']; name: string }) {
  const { t, i18n } = useTranslation()
  const meta = data?.meta ?? {}
  const more = numberOf(meta.more) ?? 0
  const offline = meta.offline === true
  const asOf = numberOf(meta.as_of) ?? numberOf(meta.stale_since)
  const note = typeof meta.check_note === 'string' && meta.check_note ? tLabel(meta.check_note) : ''
  if (!more && !offline && !note) return null
  return (
    <div className="px-3 pb-2 pt-0.5 flex flex-col gap-0.5">
      {more > 0 ? <p className="text-[11px] text-muted" data-testid="checklist-more">{t('checklist.more', { count: more })}</p> : null}
      {note && !offline ? <p className="text-[10px] text-faint leading-snug" data-testid="checklist-note">{note}</p> : null}
      {offline ? (
        <p className="text-[11px] text-warn leading-snug" role="status" data-testid="checklist-offline">
          {t('checklist.offline', { name, time: asOfText(asOf, i18n.language) })}
        </p>
      ) : null}
    </div>
  )
}

function NoteList(props: RenderProps & { name: string }) {
  const { data, onAction, canAct, name } = props
  const { t } = useTranslation()
  const disguise = useDisguise()
  const meta = data?.meta ?? {}
  const items = (data?.items ?? []) as Row[]
  const offline = meta.offline === true
  const stamp = String(meta.stamp ?? '')
  // What a finger just pressed, drawn at once; it goes when the next answer (a new stamp) says how it really is.
  const [pressed, setPressed] = useState<Record<string, boolean>>({})
  const timers = useRef<number[]>([])
  useEffect(() => setPressed({}), [stamp])
  useEffect(() => () => timers.current.forEach((id) => window.clearTimeout(id)), [])
  const done = numberOf(meta.done)
  const total = numberOf(meta.total)
  const lines = Array.isArray(meta.lines) ? (meta.lines as unknown[]).map(String) : []
  const title = typeof meta.title === 'string' && meta.title ? meta.title : meta.mode === 'note' ? t('checklist.untitled') : ''

  const press = (id: string, checked: boolean, action: Action) => {
    if (!onAction || id in pressed) return
    setPressed((now) => ({ ...now, [id]: !checked }))
    const pending = onAction(action)
    const release = () => {
      timers.current.push(window.setTimeout(() => setPressed((now) => {
        const rest = { ...now }
        delete rest[id]
        return rest
      }), HOLD_MS))
    }
    if (pending) pending.then(release, release)
    else release()
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col" data-testid="checklist">
      {title || (done !== null && total) ? (
        <div className="px-3 pb-1.5 flex items-center gap-2 min-w-0">
          <span className="text-[14px] font-semibold truncate flex-1" title={disguise.free(title)}>{disguise.free(title)}</span>
          {done !== null && total ? <Progress done={done} total={total} /> : null}
        </div>
      ) : null}
      {items.length ? (
        <ul className="flex-1 min-h-0 scroll px-1.5 pb-1">
          {items.map((item) => {
            const id = String(item.id ?? '')
            const checked = id in pressed ? pressed[id] : item.checked === true
            const depth = Math.min(4, numberOf(item.depth) ?? 0)
            const text = disguise.free(String(item.title ?? ''))
            const action = Array.isArray(item.actions) ? (item.actions[0] as Action | undefined) : undefined
            const tickable = Boolean(action && canAct && onAction && !offline)
            const Mark = checked ? CheckCircle2 : Circle
            const body = (
              <>
                <Mark size={20} className={`shrink-0 ${checked ? 'text-ok' : 'text-faint'}`} aria-hidden="true" />
                <span className={`text-[14px] leading-snug text-left min-w-0 [overflow-wrap:anywhere] ${checked ? 'line-through text-muted' : ''}`}>{text}</span>
              </>
            )
            const shape = 'w-full flex items-center gap-2.5 min-h-10 px-1.5 py-1.5 rounded-lg'
            return (
              <li key={id} style={depth ? { paddingLeft: `${depth * 14}px` } : undefined} data-checked={checked ? 'true' : 'false'}>
                {tickable && action ? (
                  <button
                    type="button"
                    className={`${shape} hover:bg-surface-hover active:bg-surface-hover`}
                    aria-pressed={checked}
                    aria-label={t(checked ? 'checklist.untick' : 'checklist.tick', { text })}
                    disabled={id in pressed}
                    onClick={(event) => {
                      event.stopPropagation()
                      press(id, checked, action)
                    }}
                  >
                    {body}
                  </button>
                ) : (
                  <div className={shape}>{body}</div>
                )}
              </li>
            )
          })}
        </ul>
      ) : lines.length ? (
        <div className="flex-1 min-h-0 scroll px-3 pb-1 text-[13px] leading-snug flex flex-col gap-1" data-testid="checklist-lines">
          {lines.map((line, index) => <p key={index} className="[overflow-wrap:anywhere]">{disguise.free(line)}</p>)}
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center text-xs text-faint px-3 pb-3">
          {meta.empty ? tLabel(String(meta.empty)) : t('card.nothing')}
        </div>
      )}
      <Footer data={data} name={name} />
    </div>
  )
}

function PinnedList({ data, name }: RenderProps & { name: string }) {
  const { t } = useTranslation()
  const disguise = useDisguise()
  const items = (data?.items ?? []) as Row[]
  return (
    <div className="flex-1 min-h-0 flex flex-col" data-testid="checklist-pinned">
      {items.length ? (
        <ul className="flex-1 min-h-0 scroll px-1.5 pb-1">
          {items.map((item) => {
            const done = numberOf(item.done)
            const total = numberOf(item.total)
            const owner = typeof item.owner === 'string' && item.owner ? t('checklist.from', { name: disguise.free(item.owner) }) : ''
            const first = disguise.free(String(item.subtitle ?? ''))
            const url = safeUrl(String(item.url ?? ''))
            const inner = (
              <>
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] font-medium truncate">{String(item.title ?? '') ? disguise.free(String(item.title)) : t('checklist.untitled')}</div>
                  {first || owner ? <div className="text-[11px] text-muted truncate">{[first, owner].filter(Boolean).join(' · ')}</div> : null}
                </div>
                {done !== null && total ? <Progress done={done} total={total} compact /> : null}
              </>
            )
            return (
              <li key={String(item.id ?? '')}>
                {url ? (
                  <a href={url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-2.5 min-h-10 px-1.5 py-1.5 rounded-lg hover:bg-surface-hover">
                    {inner}
                  </a>
                ) : (
                  <div className="flex items-center gap-2.5 min-h-10 px-1.5 py-1.5">{inner}</div>
                )}
              </li>
            )
          })}
        </ul>
      ) : (
        <div className="flex-1 flex items-center justify-center text-xs text-faint px-3 pb-3">
          {data?.meta?.empty ? tLabel(String(data.meta.empty)) : t('card.nothing')}
        </div>
      )}
      <Footer data={data} name={name} />
    </div>
  )
}

function Checklist(props: RenderProps) {
  // The service's name for the line about reaching it: the part of the kind before the dot (nexnotes.note).
  const name = props.widget.kind.split('.')[0] || props.widget.kind
  return props.data?.meta?.mode === 'pinned' ? <PinnedList {...props} name={name} /> : <NoteList {...props} name={name} />
}

export const ChecklistCard = memo(Checklist, (before, after) => before.widget.id === after.widget.id && before.onAction === after.onAction && drawnAs(before) === drawnAs(after))
