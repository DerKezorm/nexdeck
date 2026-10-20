import { ChevronDown, ChevronUp, Square } from 'lucide-react'
import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { COVER_STYLES, positionAt, type CoverState, type CoverStyle, type CoverWish, type HomeCover } from '../../lib/home'
import { Dialog } from '../ui'
import { Marquee } from './Marquee'
import { SensorTools } from './SensorControl'

/** How far a pointer travels before a press becomes a drag. */
const DRAG_PX = 6
/** How long a slider or the arrow keys rest before the position goes out. */
const GATHER_MS = 500

type Said = CoverState | undefined
type Known = CoverState & { missing: false }

const known = (said: Said): Known | null => (said && !said.missing ? said : null)

/** How a cover stands, in the page's words: where, moving, offline, or gone from Home Assistant. */
export function coverWords(said: Said, aim: number | undefined, t: (key: string, options?: Record<string, unknown>) => string): { text: string; quiet: boolean; missing: boolean; moving: boolean; position: number | null } {
  if (!said) return { text: '…', quiet: true, missing: false, moving: false, position: null }
  if (said.missing) return { text: t('homePage.sensors.missing'), quiet: true, missing: true, moving: false, position: null }
  if (said.unavailable || said.position === null || said.position === undefined) return { text: t('homePage.offline'), quiet: true, missing: false, moving: false, position: null }
  const position = aim ?? said.position
  if (aim === undefined && said.moving) return { text: t(said.moving === 'up' ? 'homePage.covers.opening' : 'homePage.covers.closing', { pct: position }), quiet: false, missing: false, moving: true, position }
  const text = position === 0 ? t('homePage.covers.closed') : position === 100 ? t('homePage.covers.open') : `${position} %`
  return { text, quiet: false, missing: false, moving: false, position }
}

/** A small shutter: the share of the window it covers, for the icon of a pill and the dot of a chip. */
export function ShutterIcon({ position }: { position: number | null }) {
  const down = Math.round((1 - (position ?? 0) / 100) * 11.6)
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden>
      <rect x="1.5" y="1.5" width="13" height="13" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <rect x="2.2" y="2.2" width="11.6" height={down} fill="currentColor" opacity=".55" />
    </svg>
  )
}

/**
 * Dragging a cover's drawing: across a pill, up a window or a slider. The
 * position follows the pointer and goes out when it lets go; a press that
 * did not move is a tap and belongs to the click.
 */
function useDrag(axis: 'x' | 'y', enabled: boolean, onAim: (position: number, done: boolean) => void) {
  const press = useRef<{ pointer: number; x: number; y: number; moved: boolean } | null>(null)
  const swallow = useRef(false)
  /** Whether the click that follows was the end of a drag, and so is no tap; asked once. */
  const dragged = () => {
    const was = swallow.current
    swallow.current = false
    return was
  }
  const at = (event: ReactPointerEvent<HTMLElement>) => {
    const box = event.currentTarget.getBoundingClientRect()
    const share = axis === 'x' ? (event.clientX - box.left) / (box.width || 1) : 1 - (event.clientY - box.top) / (box.height || 1)
    return positionAt(share)
  }
  return {
    dragged,
    handlers: {
      onPointerDown: (event: ReactPointerEvent<HTMLElement>) => {
        if (!enabled || event.button !== 0 || (event.target as HTMLElement).closest('[data-cover-button]')) return
        press.current = { pointer: event.pointerId, x: event.clientX, y: event.clientY, moved: false }
      },
      onPointerMove: (event: ReactPointerEvent<HTMLElement>) => {
        const held = press.current
        if (!held || held.pointer !== event.pointerId) return
        if (!held.moved && Math.hypot(event.clientX - held.x, event.clientY - held.y) < DRAG_PX) return
        if (!held.moved) {
          held.moved = true
          try {
            event.currentTarget.setPointerCapture(event.pointerId)
          } catch {
            // A pointer that is already gone has nothing to capture.
          }
        }
        onAim(at(event), false)
      },
      onPointerUp: (event: ReactPointerEvent<HTMLElement>) => {
        const held = press.current
        press.current = null
        if (!held || held.pointer !== event.pointerId || !held.moved) return
        swallow.current = true
        onAim(at(event), true)
      },
      onPointerCancel: () => {
        press.current = null
      },
    },
  }
}

interface Props {
  element: HomeCover
  said: Said
  /** A position asked and not yet answered. */
  aim: number | undefined
  arranging: boolean
  wide: boolean
  width: number | null
  /** Null for who may only look. */
  onWish: ((wish: CoverWish) => void) | null
  /** A position shown while a finger drags, not sent yet. */
  onAim: (position: number | undefined) => void
  onDetails: () => void
  onStyle: (style: CoverStyle) => void
  onRemove: () => void
  haName: string
  onLabel: (label: string) => void
}

/**
 * A shutter or blind in one of the styles of its board of sketches. The
 * arrows open and close it all the way and turn to a stop while it moves;
 * dragging sets a position; a tap or holding it opens its details.
 */
export function CoverControl({ element, said, aim, arranging, wide, width, onWish, onAim, onDetails, onStyle, onRemove, haName, onLabel }: Props) {
  const { t } = useTranslation()
  const info = known(said)
  const words = coverWords(said, aim, t)
  const name = element.label || info?.name || element.name
  const live = Boolean(onWish) && !arranging && Boolean(info) && !info?.unavailable
  const drag = useDrag(element.style === 'window' || element.style === 'slider' ? 'y' : 'x', live && Boolean(info?.settable), (position, done) => {
    if (done) {
      onWish?.({ position })
      return
    }
    onAim(position)
  })
  const gather = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(gather.current), [])
  const key = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (!live || !info?.settable || words.position === null) return
    const steps = event.key === 'ArrowUp' || event.key === 'ArrowRight' ? 1 : event.key === 'ArrowDown' || event.key === 'ArrowLeft' ? -1 : 0
    if (!steps) return
    event.preventDefault()
    const next = Math.max(0, Math.min(100, words.position + steps * 10))
    onAim(next)
    window.clearTimeout(gather.current)
    gather.current = window.setTimeout(() => onWish?.({ position: next }), GATHER_MS)
  }
  const state = `cover ${words.moving ? 'is-moving' : ''} ${words.quiet && !words.missing ? 'is-offline' : ''} ${words.missing ? 'is-missing' : ''}`
  const buttons = (className = '') => {
    if (!live || !info) return null
    if (info.moving && info.stoppable) {
      return (
        <button type="button" className={`cover-button is-stop ${className}`} data-cover-button onClick={() => onWish?.({ action: 'stop' })} aria-label={t('homePage.covers.stop', { name })}>
          <Square size={11} fill="currentColor" />
        </button>
      )
    }
    return (
      <>
        {info.can_open && (
          <button type="button" className={`cover-button ${className}`} data-cover-button onClick={() => onWish?.({ action: 'open' })} aria-label={t('homePage.covers.raise', { name })} disabled={words.position === 100}>
            <ChevronUp size={15} />
          </button>
        )}
        {element.style === 'tile' && info.stoppable && (
          <button type="button" className={`cover-button ${className}`} data-cover-button onClick={() => onWish?.({ action: 'stop' })} aria-label={t('homePage.covers.stop', { name })}>
            <Square size={10} fill="currentColor" />
          </button>
        )}
        {info.can_close && (
          <button type="button" className={`cover-button ${className}`} data-cover-button onClick={() => onWish?.({ action: 'close' })} aria-label={t('homePage.covers.lower', { name })} disabled={words.position === 0}>
            <ChevronDown size={15} />
          </button>
        )}
      </>
    )
  }
  const main = {
    ...drag.handlers,
    onClick: (event: React.MouseEvent<HTMLElement>) => {
      if (drag.dragged()) return
      if ((event.target as HTMLElement).closest('[data-cover-button]') || arranging) return
      onDetails()
    },
    onContextMenu: (event: React.MouseEvent<HTMLElement>) => {
      if (arranging) return
      event.preventDefault()
      onDetails()
    },
    onKeyDown: key,
    tabIndex: arranging ? -1 : 0,
    role: 'button',
    'aria-label': `${name}: ${words.text}`,
    'data-main': '',
  }
  const sized = wide ? { width: '100%' } : width !== null ? { width } : undefined
  const bar = words.position ?? 0
  let face: ReactNode
  if (element.style === 'pill' || element.style === 'tilt') {
    face = (
      <div className={element.style === 'tilt' ? 'grid gap-1' : ''} style={element.style === 'tilt' ? sized : undefined}>
        <div className={`sensor-pill ${state} ${live && info?.settable ? 'cursor-ew-resize touch-pan-y' : ''}`} style={element.style === 'tilt' ? undefined : sized} {...main}>
          <span className="sensor-icon cover-icon"><ShutterIcon position={words.position} /></span>
          <Marquee text={name} className="flex-1 font-medium" />
          <span className="sensor-state num" data-state>{words.text}</span>
          {buttons()}
          {!words.quiet && <span className="cover-bar" aria-hidden><i style={{ width: `${bar}%` }} /></span>}
        </div>
        {element.style === 'tilt' && <Slats element={element} info={info} live={live} onWish={onWish} />}
      </div>
    )
  } else if (element.style === 'chip') {
    face = (
      <span className={`sensor-chip ${state} cursor-pointer`} style={sized} {...main}>
        <span className="cover-mini" aria-hidden><i style={{ height: `${100 - bar}%` }} /></span>
        <Marquee text={name} />
        <span className="num text-muted" data-state>{words.text}</span>
      </span>
    )
  } else if (element.style === 'tile') {
    face = (
      <div className={`sensor-tile reading ${state} cursor-pointer`} {...main}>
        <Marquee text={name} className="text-[11.5px] text-muted" />
        <span className="num text-[24px] font-semibold mt-1 leading-tight" data-state>{words.position === 0 && !words.moving ? t('homePage.covers.closedWord') : words.position === 100 && !words.moving ? t('homePage.covers.openWord') : words.quiet || words.moving ? words.text : `${words.position} %`}</span>
        <span className="mt-auto flex gap-1.5">{buttons()}</span>
      </div>
    )
  } else if (element.style === 'window') {
    face = (
      <div className={`sensor-draw cover-window ${state} ${live && info?.settable ? 'cursor-ns-resize touch-none' : 'cursor-pointer'}`} {...main}>
        <WindowShutter position={words.position} moving={words.moving ? info?.moving ?? null : null} />
        <Marquee text={name} className="text-[12px] mt-1" />
        <div className="sensor-state text-[11px] num" data-state>{words.text}</div>
      </div>
    )
  } else {
    face = (
      <div className={`sensor-draw cover-slider ${state} cursor-pointer`}>
        <div className={`cover-track ${live && info?.settable ? 'touch-none cursor-ns-resize' : ''}`} {...main}>
          <span className="cover-track-down" style={{ height: `${100 - bar}%` }} />
          <span className="cover-track-handle" style={{ top: `calc(${100 - bar}% - 3px)` }} />
        </div>
        <Marquee text={name} className="text-[12px] mt-1" />
        <div className="sensor-state text-[11px] num" data-state>{words.text}</div>
      </div>
    )
  }
  return (
    <div className={`relative ${wide && (element.style === 'pill' || element.style === 'tilt') ? 'w-full' : 'w-fit'}`} data-cover={element.entity_id} data-style={element.style}
      data-position={words.position ?? undefined}>
      {face}
      {arranging && (
        <SensorTools styles={COVER_STYLES} current={element.style} group="coverStyles" onStyle={(style) => onStyle(style as CoverStyle)} onRemove={onRemove}
          removeLabel={t('homePage.covers.remove')} width={width} wide={wide} rename={{ label: element.label ?? '', fallback: haName, onLabel }} />
      )}
    </div>
  )
}

/** A window with its shutter let down, slats as lines; an arrow beside it while it moves. */
export function WindowShutter({ position, moving }: { position: number | null; moving: 'up' | 'down' | null }) {
  const top = 16
  const bottom = 96
  const down = (1 - (position ?? 0) / 100) * (bottom - top)
  const slats: number[] = []
  for (let y = top + 6; y < top + down; y += 6) slats.push(y)
  return (
    <svg width="110" height="108" viewBox="0 0 110 108" aria-hidden data-down={Math.round(down)}>
      <rect x="18" y="8" width="74" height="94" rx="3" fill="none" stroke="color-mix(in srgb, var(--nd-text) 30%, transparent)" strokeWidth="2" />
      <rect x="18" y="8" width="74" height="9" rx="2" fill="color-mix(in srgb, var(--nd-text) 22%, transparent)" />
      <rect x="24" y={top} width="62" height={bottom - top} fill="rgba(125, 211, 252, 0.16)" />
      <line x1="55" y1={top} x2="55" y2={bottom} stroke="color-mix(in srgb, var(--nd-text) 35%, transparent)" />
      <rect x="24" y={top} width="62" height={down} fill="rgba(203, 213, 225, 0.85)" />
      {slats.map((y) => <line key={y} x1="24" x2="86" y1={y} y2={y} stroke="rgba(15, 23, 42, 0.55)" strokeWidth="1" />)}
      <rect x="24" y={top + down - 3} width="62" height="3" fill="rgb(148, 163, 184)" />
      {moving && <text x="96" y={top + down + 4} style={{ fill: 'rgb(167, 139, 250)', fontSize: 13 }}>{moving === 'up' ? '▲' : '▼'}</text>}
    </svg>
  )
}

/** The slats of a blind under its pill: their angle, set by a slider and sent when it rests. */
function Slats({ element, info, live, onWish }: { element: HomeCover; info: Known | null; live: boolean; onWish: ((wish: CoverWish) => void) | null }) {
  const { t } = useTranslation()
  const [angle, setAngle] = useState<number | null>(null)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])
  if (!info?.tiltable) return <span className="text-[11px] text-faint pl-3" data-no-slats>{t('homePage.covers.noSlats')}</span>
  const shown = angle ?? info.tilt ?? 0
  return (
    <label className="flex items-center gap-2.5 text-[12px] text-muted pl-3" data-slats>
      {t('homePage.covers.slats')}
      <svg width="84" height="20" viewBox="0 0 84 20" aria-hidden>
        {[0, 1, 2, 3, 4, 5].map((index) => {
          // Closed slats stand upright, open ones lie flat: 0 is closed, 100 open, as in Home Assistant.
          const turn = 90 - shown * 0.9
          const cx = 8 + index * 14
          const dx = Math.cos((turn * Math.PI) / 180) * 5
          const dy = Math.sin((turn * Math.PI) / 180) * 5
          return <line key={index} x1={cx - dx} y1={10 - dy} x2={cx + dx} y2={10 + dy} stroke="rgba(203, 213, 225, 0.85)" strokeWidth="3" strokeLinecap="round" />
        })}
      </svg>
      <input type="range" min={0} max={100} step={5} value={shown} disabled={!live} className="lamp-range flex-1 max-w-28" aria-label={t('homePage.covers.slatsOf', { name: element.label || info.name })}
        onChange={(event) => {
          const next = Number(event.target.value)
          setAngle(next)
          window.clearTimeout(timer.current)
          timer.current = window.setTimeout(() => {
            onWish?.({ tilt: next })
            setAngle(null)
          }, GATHER_MS)
        }} />
      <span className="num text-[var(--nd-text)] w-10 text-right">{shown} %</span>
    </label>
  )
}

interface DetailsProps {
  name: string
  said: Said
  aim: number | undefined
  /** Null for who may only look. */
  onWish: ((wish: CoverWish) => void) | null
  onClose: () => void
}

/** A cover's details: where it stands, a slider for the position, open, stop and close, and its slats where it has them. */
export function CoverDetails({ name, said, aim, onWish, onClose }: DetailsProps) {
  const { t } = useTranslation()
  const info = known(said)
  const words = coverWords(said, aim, t)
  const [position, setPosition] = useState<number | null>(null)
  const [tilt, setTilt] = useState<number | null>(null)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])
  const live = Boolean(onWish) && Boolean(info) && !info?.unavailable
  const later = (send: () => void) => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(send, GATHER_MS)
  }
  return (
    <Dialog open onClose={onClose} title={name} size="sm">
      <div className="grid gap-5" data-cover-details>
        <div className="flex items-baseline gap-2.5">
          <span className="num text-3xl font-semibold" data-position>{words.position === null ? '–' : `${position ?? words.position} %`}</span>
          <span className={`text-sm ${words.moving ? 'cover-moving-text' : 'text-muted'}`}>
            {words.quiet ? words.text : words.moving ? t(info?.moving === 'up' ? 'homePage.covers.openingWord' : 'homePage.covers.closingWord')
              : (position ?? words.position) === 0 ? t('homePage.covers.closed') : t('homePage.covers.open')}
          </span>
        </div>
        {live && info?.settable && (
          <label className="grid gap-1.5">
            <span className="text-sm font-medium">{t('homePage.covers.position')}</span>
            <input type="range" className="lamp-range" min={0} max={100} step={5} value={position ?? words.position ?? 0} aria-label={t('homePage.covers.position')}
              onChange={(event) => {
                const next = Number(event.target.value)
                setPosition(next)
                later(() => {
                  onWish?.({ position: next })
                  setPosition(null)
                })
              }} />
          </label>
        )}
        {live && info && (
          <div className="flex flex-wrap gap-2">
            {info.can_open && <button type="button" className="btn" onClick={() => onWish?.({ action: 'open' })}><ChevronUp size={15} /> {t('homePage.covers.raiseWord')}</button>}
            {info.stoppable && <button type="button" className="btn" onClick={() => onWish?.({ action: 'stop' })}><Square size={11} fill="currentColor" /> {t('homePage.covers.stopWord')}</button>}
            {info.can_close && <button type="button" className="btn" onClick={() => onWish?.({ action: 'close' })}><ChevronDown size={15} /> {t('homePage.covers.lowerWord')}</button>}
          </div>
        )}
        {live && info?.tiltable && (
          <label className="grid gap-1.5">
            <span className="text-sm font-medium">{t('homePage.covers.slats')}</span>
            <input type="range" className="lamp-range" min={0} max={100} step={5} value={tilt ?? info.tilt ?? 0} aria-label={t('homePage.covers.slats')}
              onChange={(event) => {
                const next = Number(event.target.value)
                setTilt(next)
                later(() => {
                  onWish?.({ tilt: next })
                  setTilt(null)
                })
              }} />
          </label>
        )}
        {info && !info.tiltable && <p className="text-[11.5px] text-faint">{t('homePage.covers.noSlatsHere')}</p>}
      </div>
    </Dialog>
  )
}
