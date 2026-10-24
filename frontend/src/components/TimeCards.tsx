/**
 * The countdown and the timer. Both count in the browser, from options the
 * server checked once (``countdown_meta``, ``timer_meta`` in core.py), and
 * load only when a board has one of them.
 *
 * A timer belongs to the browser it runs in: started on the kitchen tablet,
 * it rings there, and a phone on the same board keeps a timer of its own.
 * Its state is kept in this browser, so a reload does not lose it.
 */
import { Pause, Play, Plus, RotateCcw } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import type { RenderProps } from './renderers'

const DAY = 86_400_000

export interface CountdownMeta {
  event: string
  date: string
  time: string
  yearly: boolean
  show: 'auto' | 'days' | 'all'
  after: 'since' | 'here'
}

/** What the countdown says right now. */
export type Reading =
  | { state: 'unset' }
  | { state: 'today' }
  | { state: 'days'; days: number }
  | { state: 'clock'; days: number; hours: number; minutes: number; seconds: number }
  | { state: 'since'; days: number }
  | { state: 'here' }

function leap(year: number): boolean {
  return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0
}

/** The moment a date and time stand for in this browser's zone, in another year if asked. */
function momentOf(date: string, time: string, year?: number): Date {
  const [y, m, d] = date.split('-').map(Number)
  const [hours, minutes] = time ? time.split(':').map(Number) : [0, 0]
  const when = year ?? y
  // A birthday on 29 February comes on the 28th in the other years.
  const day = m === 2 && d === 29 && !leap(when) ? 28 : d
  return new Date(when, m - 1, day, hours, minutes)
}

/**
 * Whole days between two dates by the calendar, not by stretches of 24 hours.
 *
 * ⚠️ The day the clocks go forward has 23 hours. Dividing by 24 hours, a
 * countdown that crossed it read one day short for the hour after midnight.
 */
function calendarDays(from: Date, to: Date): number {
  return Math.round((Date.UTC(to.getFullYear(), to.getMonth(), to.getDate()) - Date.UTC(from.getFullYear(), from.getMonth(), from.getDate())) / DAY)
}

/** The moment counted to: the date, or with ``yearly`` its next return that has not ended yet. */
export function targetOf(meta: CountdownMeta, now: Date): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(meta.date)) return null
  if (!meta.yearly) return momentOf(meta.date, meta.time)
  const thisYear = momentOf(meta.date, meta.time, now.getFullYear())
  // A day without a time lasts until its end: a birthday is today all day.
  const over = meta.time ? thisYear : new Date(thisYear.getFullYear(), thisYear.getMonth(), thisYear.getDate() + 1)
  return over <= now ? momentOf(meta.date, meta.time, now.getFullYear() + 1) : thisYear
}

export function readCountdown(meta: CountdownMeta, now: Date): Reading {
  const target = targetOf(meta, now)
  if (!target) return { state: 'unset' }
  const days = calendarDays(now, target)
  const left = target.getTime() - now.getTime()
  const past = meta.time ? left <= 0 : days < 0
  if (past) {
    const since = calendarDays(target, now)
    // On the day itself a moment just past is here, not "0 days ago".
    return meta.after === 'here' || since === 0 ? { state: 'here' } : { state: 'since', days: since }
  }
  if (days === 0 && (!meta.time || meta.show === 'days')) return { state: 'today' }
  const clock = meta.show === 'all' || (meta.show === 'auto' && meta.time !== '' && left < 2 * DAY)
  if (!clock) return { state: 'days', days }
  const seconds = Math.max(0, Math.ceil(left / 1000))
  return {
    state: 'clock',
    days: Math.floor(seconds / 86_400),
    hours: Math.floor((seconds % 86_400) / 3600),
    minutes: Math.floor((seconds % 3600) / 60),
    seconds: seconds % 60,
  }
}

function countdownMeta(raw: Record<string, unknown> | undefined): CountdownMeta {
  return {
    event: String(raw?.event ?? ''),
    date: String(raw?.date ?? ''),
    time: String(raw?.time ?? ''),
    yearly: Boolean(raw?.yearly),
    show: raw?.show === 'days' || raw?.show === 'all' ? raw.show : 'auto',
    after: raw?.after === 'here' ? 'here' : 'since',
  }
}

/** Ticks once a second while mounted. */
function useNow(): Date {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  return now
}

export function CountdownCard({ widget, data }: RenderProps) {
  const { t } = useTranslation()
  const now = useNow()
  // The card's own options until the server's checked copy arrives, so it never opens on "pick a date".
  const meta = countdownMeta(data?.meta ?? widget.options)
  const reading = readCountdown(meta, now)
  if (reading.state === 'unset') {
    return <div className="flex-1 flex items-center justify-center px-4 text-center text-xs text-muted">{t('countdown.unset')}</div>
  }
  const target = targetOf(meta, now)!
  const when = target.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'long', year: target.getFullYear() === now.getFullYear() ? undefined : 'numeric' })
  const at = meta.time ? ` ${target.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}` : ''
  const ahead = reading.state === 'days' || reading.state === 'clock'
  const line = [meta.event ? (ahead ? t('countdown.until', { event: meta.event }) : meta.event) : '', `${when}${at}`].filter(Boolean).join(' · ')
  let big: ReactNode
  if (reading.state === 'today') big = t('countdown.today')
  else if (reading.state === 'here') big = t('countdown.here')
  else if (reading.state === 'days')
    big = (
      <>
        {reading.days}
        <small>{t('countdown.days', { count: reading.days })}</small>
      </>
    )
  else if (reading.state === 'since') {
    // "vor 4 Tagen", "4 days ago": the number stands where the language puts it, and large.
    const words = t('countdown.ago', { count: reading.days })
    const at = words.indexOf(String(reading.days))
    big =
      at < 0 ? (
        words
      ) : (
        <>
          {at > 0 && <small className="nd-before">{words.slice(0, at).trim()}</small>}
          {reading.days}
          <small>{words.slice(at + String(reading.days).length).trim()}</small>
        </>
      )
  }
  else {
    const parts: [number, string][] = reading.days
      ? [[reading.days, 'd'], [reading.hours, 'h'], [reading.minutes, 'min']]
      : reading.hours
        ? [[reading.hours, 'h'], [reading.minutes, 'min']]
        : [[reading.minutes, 'min'], [reading.seconds, 's']]
    big = parts.map(([value, unit]) => (
      <span key={unit} className="nd-part">
        {value}
        <small>{t(`countdown.unit.${unit}`)}</small>
      </span>
    ))
  }
  return (
    <div className="nd-countdown" data-state={reading.state}>
      <div className="nd-countdown-big num">{big}</div>
      <div className="nd-countdown-line">{line}</div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Timer
// ---------------------------------------------------------------------------

/** What a timer keeps in this browser: its length, what is left when it stands, and when it ends while it runs. */
export interface TimerState {
  total: number
  left: number
  endsAt: number | null
}

const RING_SECONDS = 60
const timerKey = (id: number) => `nexdeck.timer.${id}`

function readTimer(id: number, start: number): TimerState {
  try {
    const raw = JSON.parse(localStorage.getItem(timerKey(id)) ?? 'null') as Partial<TimerState> | null
    if (raw && Number.isFinite(raw.total) && Number.isFinite(raw.left) && (raw.endsAt === null || Number.isFinite(raw.endsAt))) {
      return { total: Number(raw.total), left: Number(raw.left), endsAt: raw.endsAt === null ? null : Number(raw.endsAt) }
    }
  } catch {
    // A private window or a full store: the timer simply starts fresh.
  }
  return { total: start, left: start, endsAt: null }
}

function keepTimer(id: number, state: TimerState): void {
  try {
    localStorage.setItem(timerKey(id), JSON.stringify(state))
  } catch {
    // Not kept; it runs on until the page is reloaded.
  }
}

/** Seconds left, whole and rounded up: a timer at 9:59.4 still shows 10:00. */
export function secondsLeft(state: TimerState, now: number): number {
  if (state.endsAt === null) return Math.max(0, Math.ceil(state.left))
  return Math.max(0, Math.ceil((state.endsAt - now) / 1000))
}

export function clockText(seconds: number): string {
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const rest = String(seconds % 60).padStart(2, '0')
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${String(minutes).padStart(2, '0')}:${rest}`
}

/** The time a press happened. Only the handlers of the buttons read it, never the drawing. */
const pressedAt = () => Date.now()

let audio: AudioContext | null = null

/**
 * The sound is made ready by a press. Browsers let a page play sound only
 * after somebody touched it, and the press on Start is that touch.
 */
function wakeSound(): void {
  try {
    const Context = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!Context) return
    audio = audio ?? new Context()
    void audio.resume?.()
  } catch {
    audio = null
  }
}

function beep(): void {
  if (!audio) return
  try {
    const tone = audio.createOscillator()
    const volume = audio.createGain()
    tone.frequency.value = 880
    volume.gain.value = 0.15
    tone.connect(volume)
    volume.connect(audio.destination)
    tone.start()
    tone.stop(audio.currentTime + 0.25)
  } catch {
    // No sound; the card still flashes.
  }
}

export function TimerCard({ widget, data, editing }: RenderProps) {
  const { t } = useTranslation()
  const own = data?.meta ?? widget.options
  const start = Math.round(Number(own?.minutes ?? 10) * 60) || 600
  const presets = Array.isArray(data?.meta?.presets) ? (data!.meta!.presets as unknown[]).map(Number).filter((one) => one > 0) : []
  const loud = own?.end !== 'flash'
  const [state, setState] = useState<TimerState>(() => readTimer(widget.id, start))
  const [now, setNow] = useState(() => Date.now())
  const root = useRef<HTMLDivElement>(null)
  const lastBeep = useRef(0)

  const change = useCallback(
    (next: TimerState) => {
      setState(next)
      setNow(Date.now())
      keepTimer(widget.id, next)
    },
    [widget.id],
  )

  // A new start in the settings is taken over while the timer stands untouched.
  // ⚠️ Only when the setting changes: compared on every change, a minute
  // added to a standing timer was taken back at once.
  const setStart = useRef(start)
  useEffect(() => {
    if (setStart.current === start) return
    setStart.current = start
    if (state.endsAt === null && state.left === state.total) change({ total: start, left: start, endsAt: null })
  }, [start, state, change])

  const left = secondsLeft(state, now)
  const running = state.endsAt !== null && left > 0
  const ringing = state.endsAt !== null && left === 0

  useEffect(() => {
    if (state.endsAt === null) return
    const timer = window.setInterval(() => setNow(Date.now()), 250)
    return () => window.clearInterval(timer)
  }, [state.endsAt])

  // Ringing: the card flashes until somebody stops it, the sound stops by itself after a minute.
  useEffect(() => {
    const card = root.current?.closest('.card')
    card?.classList.toggle('nd-ringing', ringing)
    return () => card?.classList.remove('nd-ringing')
  }, [ringing])
  useEffect(() => {
    if (!ringing || !loud || state.endsAt === null) return
    if (now - state.endsAt > RING_SECONDS * 1000 || now - lastBeep.current < 1000) return
    lastBeep.current = now
    beep()
  }, [ringing, loud, now, state.endsAt])

  const go = () => {
    wakeSound()
    change({ ...state, left, endsAt: pressedAt() + left * 1000 })
  }
  const pause = () => change({ ...state, left, endsAt: null })
  const reset = () => change({ total: state.total, left: state.total, endsAt: null })
  const more = () => {
    wakeSound()
    // Ringing, a minute more starts it again for a minute: a snooze.
    const base = ringing ? 0 : left
    const total = Math.max(state.total, base + 60)
    change(running || ringing ? { total, left: base + 60, endsAt: pressedAt() + (base + 60) * 1000 } : { total, left: base + 60, endsAt: null })
  }
  const pick = (minutes: number) => {
    wakeSound()
    const seconds = Math.round(minutes * 60)
    // A quick pick runs at once: on a wall tablet one tap is the whole point.
    change({ total: seconds, left: seconds, endsAt: pressedAt() + seconds * 1000 })
  }

  const share = state.total ? Math.min(1, left / state.total) : 0
  return (
    <div
      ref={root}
      className="nd-timer"
      data-state={ringing ? 'ringing' : running ? 'running' : left < state.total ? 'paused' : 'idle'}
      // Ringing, a tap anywhere stops it; a button keeps its own meaning (a minute more is a snooze).
      onClick={ringing ? (event) => !(event.target as HTMLElement).closest('button') && reset() : undefined}
    >
      <div className="nd-timer-time num" role="timer" aria-live={ringing ? 'assertive' : 'off'}>
        {clockText(left)}
      </div>
      <div className="nd-timer-track" aria-hidden="true">
        <i style={{ width: `${share * 100}%` }} />
      </div>
      {ringing && <div className="nd-timer-done">{t('timer.done')}</div>}
      <div className="nd-timer-row no-drag">
        {ringing ? (
          <button type="button" className="btn btn-accent" onClick={reset} disabled={editing}>
            {t('timer.stop')}
          </button>
        ) : running ? (
          <button type="button" className="btn" onClick={pause} disabled={editing}>
            <Pause size={14} aria-hidden="true" />
            {t('timer.pause')}
          </button>
        ) : (
          <button type="button" className="btn btn-accent" onClick={go} disabled={editing || left === 0}>
            <Play size={14} aria-hidden="true" />
            {left < state.total ? t('timer.resume') : t('timer.start')}
          </button>
        )}
        <button type="button" className="btn" onClick={more} disabled={editing} aria-label={t('timer.oneMore')} title={t('timer.oneMore')}>
          <Plus size={14} aria-hidden="true" />1
        </button>
        <button type="button" className="btn" onClick={reset} disabled={editing || (!running && !ringing && left === state.total)} aria-label={t('timer.reset')} title={t('timer.reset')}>
          <RotateCcw size={14} aria-hidden="true" />
        </button>
      </div>
      {presets.length > 0 && (
        <div className="nd-timer-row nd-timer-picks no-drag">
          {presets.map((minutes) => (
            <button key={minutes} type="button" className="btn" onClick={() => pick(minutes)} disabled={editing}>
              {minutes < 1 ? t('timer.seconds', { count: Math.round(minutes * 60) }) : t('timer.minutes', { count: minutes })}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
