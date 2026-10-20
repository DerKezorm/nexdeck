import { Lightbulb } from 'lucide-react'
import type { CSSProperties, ReactNode } from 'react'

import { lampColour, type LampInfo, type LampStyle } from '../../lib/home'

/** A warm white, for the parts of a drawing that show the lamp's light while it is off. */
export const WARM = 'rgb(255, 176, 96)'

export interface FaceInput {
  style: LampStyle
  info: LampInfo | null
  name: string
  /** The words for how it stands: "62 %", "off", "offline", "gone". */
  state: string
  /** Gone or out of reach: drawn faint, never as off. */
  quiet: boolean
  /** The brightness under a finger while it drags, shown instead of what the lamp says. */
  dimming: number | null
  /** In the phone's list, where a pill, a chip or a slider runs the width of the screen. */
  wide: boolean
}

/** What the control around a drawing wears, and what is inside it. */
export interface Face {
  className: string
  style?: CSSProperties
  children: ReactNode
}

/**
 * The ten drawings of the board of sketches (``knoepfe.html``, approved
 * 19.10.2026), with its sizes. The control that wears a face (a button for
 * those who may act, a box otherwise) does the switching; a face only draws.
 */
export function lampFace({ style, info, name, state, quiet, dimming, wide }: FaceInput): Face {
  const colour = lampColour(info)
  const on = Boolean(colour)
  const lc = { '--lc': colour ?? WARM } as CSSProperties
  const pct = dimming ?? (info?.on ? (info.pct ?? 100) : 0)
  const shown = dimming !== null ? `${dimming} %` : state
  const caption = (drawing: ReactNode) => ({
    className: `lamp-stack ${quiet ? 'lamp-quiet' : ''}`,
    style: lc,
    children: (
      <>
        {drawing}
        <span className="lamp-cap">{dimming !== null ? shown : name}</span>
      </>
    ),
  })

  switch (style) {
    case 'round':
      return caption(<span className={`lamp-round ${on ? 'is-on' : ''} ${quiet ? 'is-quiet' : ''}`}><Lightbulb size={18} /></span>)
    case 'chip':
      return {
        className: `lamp-chip ${on ? 'is-on' : ''} ${quiet ? 'is-quiet' : ''} ${wide ? 'w-full max-w-none h-11' : ''}`,
        style: lc,
        children: (
          <>
            <i aria-hidden />
            <span className="min-w-0 truncate">{name}</span>
            <span className="lamp-p num">{shown}</span>
          </>
        ),
      }
    case 'tile':
      return {
        className: `lamp-tile ${on ? 'is-on' : ''} ${quiet ? 'is-quiet' : ''}`,
        style: lc,
        children: (
          <>
            <Lightbulb size={18} />
            <span className="lamp-p num">{shown}</span>
            <b>{name}</b>
          </>
        ),
      }
    case 'slider':
      return {
        className: `lamp-slide ${on || dimming !== null ? 'is-on' : ''} ${quiet ? 'lamp-quiet' : ''} ${wide ? 'w-full h-12' : ''}`,
        style: lc,
        children: (
          <>
            {(on || dimming !== null) && <span className="lamp-fill" style={{ width: `${pct}%` }} />}
            <Lightbulb size={18} />
            <span className="min-w-0 truncate">{name}</span>
            <span className="lamp-p num">{shown}</span>
          </>
        ),
      }
    case 'ring':
      return caption(
        <span className={`lamp-ring ${on ? 'is-on' : ''}`}>
          <Arc fraction={on || dimming !== null ? pct / 100 : 0} />
          <Lightbulb size={18} />
        </span>,
      )
    case 'rocker':
      return caption(
        <span className={`lamp-plate ${on ? 'is-on' : ''}`}>
          <span className="lamp-rk">
            <span className="lamp-sl" />
          </span>
        </span>,
      )
    case 'dots':
      return caption(<Dots on={on} />)
    case 'bulb':
      return caption(<Bulb on={on} colour={colour ?? WARM} />)
    case 'knob':
      return caption(<Knob on={on || dimming !== null} pct={pct} />)
    default:
      return {
        className: `glass lamp-pill ${wide ? 'w-full h-12' : 'h-10 max-w-[256px]'} ${quiet ? 'lamp-quiet' : ''}`,
        style: colour
          ? { borderColor: `color-mix(in srgb, ${colour} 50%, transparent)`, background: `color-mix(in srgb, ${colour} 14%, var(--nd-surface))`, boxShadow: `0 0 22px -8px ${colour}` }
          : undefined,
        children: (
          <>
            {dimming !== null && (
              // While dragging, the pill fills to the brightness under the finger.
              <span aria-hidden className="absolute inset-y-0 left-0 pointer-events-none" style={{ width: `${dimming}%`, background: `color-mix(in srgb, ${colour ?? WARM} 30%, transparent)` }} />
            )}
            <span className="relative grid place-items-center w-7 h-7 rounded-full flex-none transition-colors duration-200" style={colour ? { background: colour, color: '#1b1206' } : { background: 'color-mix(in srgb, var(--nd-text) 9%, transparent)' }}>
              <Lightbulb size={15} className={colour ? '' : 'text-muted'} />
            </span>
            <span className="relative text-[13px] font-medium whitespace-nowrap min-w-0 truncate">{name}</span>
            {state && <span className={`relative num text-[11.5px] whitespace-nowrap flex-none ${colour ? '' : 'text-muted'}`}>{state}</span>}
          </>
        ),
      }
  }
}

/** Three quarters of a circle, filled as far as the lamp is bright (F ring). */
function Arc({ fraction }: { fraction: number }) {
  const r = 24
  const around = 2 * Math.PI * r
  const arc = around * 0.75
  return (
    <svg className="lamp-arc" viewBox="0 0 56 56" aria-hidden>
      <circle cx="28" cy="28" r={r} fill="none" className="lamp-arc-track" strokeWidth="3.5" strokeLinecap="round" strokeDasharray={`${arc} ${around}`} />
      {fraction > 0 && (
        <circle cx="28" cy="28" r={r} fill="none" className="lamp-arc-lit" strokeWidth="3.5" strokeLinecap="round" strokeDasharray={`${arc * fraction} ${around}`} />
      )}
    </svg>
  )
}

/** A light bulb drawn in nine by ten dots (H dots); the glass fills when it is on. */
const GLYPH = ['..XXXXX..', '.XoooooX.', 'XoooooooX', 'XoooooooX', 'XoooooooX', '.XoooooX.', '..XoooX..', '...XXX...', '...XXX...', '....X....']

function Dots({ on }: { on: boolean }) {
  return (
    <span className={`lamp-dots ${on ? 'is-on' : ''}`} aria-hidden>
      {GLYPH.flatMap((row, y) => [...row].map((cell, x) => <i key={`${x}-${y}`} className={cell === 'X' ? 'o' : cell === 'o' && on ? 'f' : ''} />))}
    </span>
  )
}

/** A bulb hanging from its cord (I bulb), its filament glowing in the lamp's colour. */
function Bulb({ on, colour }: { on: boolean; colour: string }) {
  return (
    <svg className="lamp-bulb" viewBox="0 0 46 66" width="46" height="66" aria-hidden>
      {on && <circle cx="23" cy="44" r="22" style={{ fill: colour, filter: 'blur(5px)' }} opacity=".22" />}
      <line x1="23" y1="0" x2="23" y2="14" className="lamp-bulb-cord" strokeWidth="1.2" />
      <rect x="18" y="13" width="10" height="10" rx="1.5" className="lamp-bulb-cap" />
      <path d="M18.5 23 L18.5 27 C11 31 8 37 8 43 C8 52 15 59 23 59 C31 59 38 52 38 43 C38 37 35 31 27.5 27 L27.5 23 Z"
        className={on ? 'lamp-bulb-glass is-on' : 'lamp-bulb-glass'} strokeWidth="1" />
      <path d="M19.5 44 C20.5 39 22 47 23 43 C24 39 25.5 47 26.5 44" fill="none" strokeWidth="1.3"
        style={{ stroke: on ? colour : 'rgba(150, 120, 100, 0.6)', filter: on ? `drop-shadow(0 0 2px ${colour})` : undefined }} />
    </svg>
  )
}

/** A turning knob with fifteen lights around it (J knob), turned as far as the lamp is bright. */
function Knob({ on, pct }: { on: boolean; pct: number }) {
  const count = 15
  const lit = on ? pct / 100 : 0
  return (
    <span className={`lamp-knob ${on ? 'is-on' : ''}`}>
      <svg viewBox="0 0 58 58" aria-hidden>
        {Array.from({ length: count }, (_, index) => {
          const share = index / (count - 1)
          const angle = ((-135 + 270 * share - 90) * Math.PI) / 180
          return <circle key={index} cx={29 + 26 * Math.cos(angle)} cy={29 + 26 * Math.sin(angle)} r="1.6" className={on && share <= lit ? 'lamp-led is-on' : 'lamp-led'} />
        })}
      </svg>
      <span className="lamp-k" style={{ transform: `rotate(${-135 + 270 * (on ? pct / 100 : 0.3)}deg)` }} />
    </span>
  )
}
