import type { CSSProperties, ReactNode } from 'react'

import { shareOf, temperature, type ClimateStyle, type ClimateView } from '../../lib/home'
import { Marquee } from './Marquee'

export interface ClimateFaceInput {
  style: ClimateStyle
  info: ClimateView | null
  name: string
  /** The target shown: what is being asked, or what the thermostat says. */
  target: number | null
  /** The words for the target: "22°", "off", "offline", "gone". */
  aim: string
  quiet: boolean
  /** Its colour: heating, cooling, idle or off (``climateLook``). */
  colour: string
  /** Heating or cooling right now, so the drawing glows. */
  working: boolean
  icon: ReactNode
  /** A sensor that went: the reading is the thermostat's own, marked. */
  fallback: boolean
  /** A target being asked and not yet confirmed. */
  setting?: boolean
}

/** What the control around a thermostat's drawing wears, and what is inside it. */
export interface ClimateFace {
  className: string
  style?: CSSProperties
  children: ReactNode
  /** Turned in a circle rather than swiped sideways: the dial and the valve head. */
  round: boolean
}

/**
 * Nine drawings of the thermostats' board of sketches (``heizung.html``,
 * 20.10.2026), with its sizes; the tenth, the pill, is drawn by
 * ``ClimateControl`` itself, with its plus and minus.
 */
export function climateFace({ style, info, name, target, aim, quiet, colour, working, icon, fallback, setting = false }: ClimateFaceInput): ClimateFace {
  const on = Boolean(info?.on) && !quiet
  const reading = temperature(info?.reading ?? null)
  const lc = { '--lc': colour } as CSSProperties
  const mark = fallback ? <span aria-hidden> *</span> : null
  const range = info ?? { min: 7, max: 35 }
  const caption = (width: number, drawing: ReactNode, below: ReactNode = <Marquee text={name} />) => ({
    className: `climate-stack ${quiet ? 'lamp-quiet' : ''}`,
    style: { ...lc, width },
    round: false,
    children: (
      <>
        {drawing}
        <span className="lamp-cap">{below}</span>
      </>
    ),
  })

  switch (style) {
    case 'round':
      return caption(84, (
        <span className={`climate-round ${working ? 'is-working' : on ? 'is-on' : ''}`}>
          <span className="num climate-round-v" data-reading>{reading}{mark}</span>
          <span className="num climate-round-s" data-target>{on ? `→ ${aim}` : aim}</span>
        </span>
      ))
    case 'chip':
      return {
        className: `lamp-chip climate-chip ${working ? 'is-on' : ''} ${on ? 'is-lit' : ''} ${quiet ? 'is-quiet' : ''}`,
        style: lc,
        round: false,
        children: (
          <>
            <i aria-hidden />
            <Marquee text={name} className="flex-1" />
            <span className="lamp-p num">
              <span data-reading>{reading}{mark}</span> <span data-target>{on ? `→ ${aim}` : `· ${aim}`}</span>
            </span>
          </>
        ),
      }
    case 'tile':
      return {
        className: `climate-tile ${working ? 'is-on' : ''} ${quiet ? 'is-quiet' : ''}`,
        style: lc,
        round: false,
        children: (
          <>
            <span className="num climate-tile-v" data-reading>{reading}{mark}</span>
            <b>{name}</b>
            <span className={`num climate-tile-s ${on ? '' : 'is-off'}`} data-target>{aim}</span>
          </>
        ),
      }
    case 'slider':
      return {
        className: `lamp-slide climate-slide ${on ? 'is-on' : ''} ${quiet ? 'lamp-quiet' : ''}`,
        style: lc,
        round: false,
        children: (
          <>
            {on && <span className="lamp-fill" style={{ width: `${shareOf(range, target) * 100}%` }} data-fill />}
            {on && info?.reading !== null && info?.reading !== undefined && <span className="climate-now" style={{ left: `${shareOf(range, info.reading) * 100}%` }} aria-hidden />}
            <span className="climate-slide-icon">{icon}</span>
            <Marquee text={name} className="flex-1 lamp-slide-name" />
            <span className="lamp-p num">
              <span className="text-muted" data-reading>{reading}{mark}</span> <span data-target>{aim}</span>
            </span>
          </>
        ),
      }
    case 'dial':
      return { ...caption(100, (
        <span className="climate-dial">
          <Arc share={on ? shareOf(range, target) : 0} now={info?.reading === null || info?.reading === undefined ? null : shareOf(range, info.reading)} />
          <span className="climate-dial-in">
            <span className={`num climate-dial-v ${on ? '' : 'is-off'}`} data-target>{aim}</span>
            {info && info.reading !== null && <span className="num climate-dial-s" data-reading>{reading}{mark}</span>}
          </span>
        </span>
      )), round: true }
    case 'valve': {
      // The marks of a radiator's valve head: 3 is about 20 °C, a mark about 4 degrees. While it is
      // being turned it says the degrees, or nobody would know where it lands.
      const level = target === null ? null : Math.max(1, Math.min(5, Math.round((target - 8) / 4)))
      return { ...caption(84, (
        <span className={`climate-valve ${working ? 'is-on' : ''}`}>
          <span className="climate-valve-ribs" />
          <span className="climate-valve-mark" style={{ transform: `translateX(-50%) rotate(${-135 + 270 * shareOf(range, target)}deg)` }} />
          <span className={`num climate-valve-num ${setting && on ? 'is-setting' : ''}`} data-target>{quiet ? '–' : !on ? '❄' : setting ? aim : level}</span>
        </span>
      ), <><Marquee text={name} /><span className="num" data-reading>{reading}{mark}</span></>), round: true }
    }
    case 'thermometer':
      return caption(100, (
        <span className="climate-thermo" style={{ '--lc': on ? colour : 'var(--nd-text-faint)' } as CSSProperties}>
          <span className="climate-thermo-tube"><span className="climate-thermo-fill" style={{ height: `${shareOf(range, info?.reading) * 100}%` }} /></span>
          <span className="climate-thermo-bulb" />
          {on && <span className="climate-thermo-aim" style={{ top: `${(1 - shareOf(range, target)) * 76}px` }} />}
        </span>
      ), <><Marquee text={name} /><span className="num"><span data-reading>{reading}{mark}</span>{on ? <> → <span data-target>{aim}</span></> : <> · <span data-target>{aim}</span></>}</span></>)
    case 'radiator':
      return caption(96, (
        <span className={`climate-radiator ${working ? 'is-on' : ''}`}>
          {working && (
            <svg className="climate-waves" viewBox="0 0 84 20" aria-hidden>
              {[18, 42, 66].map((x) => <path key={x} d={`M${x} 18 C${x - 5} 13 ${x + 5} 9 ${x} 3`} fill="none" strokeWidth="1.6" strokeLinecap="round" />)}
            </svg>
          )}
          <span className="climate-ribs">{Array.from({ length: 6 }, (_, index) => <i key={index} />)}</span>
        </span>
      ), <><Marquee text={name} /><span className="num"><span data-reading>{reading}{mark}</span> · <span data-target>{aim}</span></span></>)
    case 'digits':
      return {
        className: `climate-digits ${working ? 'is-on' : ''} ${quiet ? 'lamp-quiet' : ''}`,
        style: lc,
        round: false,
        children: (
          <>
            <span className="num climate-digits-v" data-reading>{reading}{mark}</span>
            <span className="climate-digits-s">
              <Marquee text={name} className="flex-1" />
              <span className="num" data-target>{aim}</span>
            </span>
          </>
        ),
      }
    default:
      return { className: '', round: false, children: null }
  }
}

/** Three quarters of a circle from the minimum to the maximum, filled to the target, a dot at the room's temperature. */
function Arc({ share, now }: { share: number; now: number | null }) {
  const size = 100
  const r = 42
  const around = 2 * Math.PI * r
  const arc = around * 0.75
  const at = (fraction: number) => {
    const angle = ((135 + 270 * fraction) * Math.PI) / 180
    return [size / 2 + r * Math.cos(angle), size / 2 + r * Math.sin(angle)]
  }
  const dot = now === null ? null : at(now)
  return (
    <svg className="climate-arc" viewBox={`0 0 ${size} ${size}`} aria-hidden>
      <circle cx="50" cy="50" r={r} fill="none" className="lamp-arc-track" strokeWidth="6" strokeLinecap="round" strokeDasharray={`${arc} ${around}`} transform="rotate(135 50 50)" />
      {share > 0 && <circle cx="50" cy="50" r={r} fill="none" className="lamp-arc-lit" strokeWidth="6" strokeLinecap="round" strokeDasharray={`${arc * share} ${around}`} transform="rotate(135 50 50)" />}
      {dot && <circle cx={dot[0]} cy={dot[1]} r="4" className="climate-arc-now" />}
    </svg>
  )
}
