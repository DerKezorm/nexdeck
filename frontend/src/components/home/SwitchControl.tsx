import { useQuery } from '@tanstack/react-query'
import { Activity, Plug, Power, ShieldCheck, ToggleRight, Trash2 } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { get } from '../../api/client'
import { SWITCH_STYLES, totalPower, type ActionState, type HomeSwitch, type HomeSwitches, type SwitchStyle } from '../../lib/home'
import { Dialog } from '../ui'
import { Marquee } from './Marquee'
import { Rename } from './Rename'
import { SensorTools } from './SensorControl'

type Said = ActionState | undefined
const known = (said: Said) => (said && !said.missing ? said : null)

/** Watts as a page writes them: whole ones, kilowatts from a thousand. */
export function watts(value: number | null | undefined): string {
  if (value === null || value === undefined) return ''
  return value >= 1000 ? `${(value / 1000).toFixed(value >= 10_000 ? 0 : 1)} kW` : `${Math.round(value)} W`
}

/** How a switch stands, in the page's words: on with what it draws, off, switching, offline, or gone from Home Assistant. */
export function switchWords(said: Said, wanted: boolean | undefined, t: (key: string, options?: Record<string, unknown>) => string): { text: string; on: boolean; quiet: boolean; missing: boolean; pending: boolean } {
  if (!said) return { text: '…', on: false, quiet: true, missing: false, pending: false }
  if (said.missing) return { text: t('homePage.sensors.missing'), on: false, quiet: true, missing: true, pending: false }
  if (said.unavailable || said.on === null || said.on === undefined) return { text: t('homePage.offline'), on: false, quiet: true, missing: false, pending: false }
  if (wanted !== undefined && wanted !== said.on) return { text: t('homePage.switches.switching'), on: wanted, quiet: false, missing: false, pending: true }
  const power = said.on && typeof said.power === 'number' ? ` · ${watts(said.power)}` : ''
  return { text: `${said.on ? t('homePage.on') : t('homePage.off')}${power}`, on: said.on, quiet: false, missing: false, pending: false }
}

/** The sign of a switch: a plug for an outlet, a toggle for a helper, the power sign for the rest. */
function signOf(entity: string, said: Said, size = 14): ReactNode {
  const info = known(said)
  if (entity.startsWith('input_boolean.')) return <ToggleRight size={size} />
  return info?.device_class === 'outlet' ? <Plug size={size} /> : <Power size={size} />
}

/** An outlet drawn, green while it is on. */
function Outlet({ on }: { on: boolean }) {
  return (
    <svg width="96" height="96" viewBox="0 0 96 96" aria-hidden>
      <rect x="14" y="14" width="68" height="68" rx="16" fill="color-mix(in srgb, var(--nd-text) 6%, transparent)" stroke={on ? 'rgb(74, 222, 128)' : 'color-mix(in srgb, var(--nd-text) 35%, transparent)'}
        strokeWidth="2" style={on ? { filter: 'drop-shadow(0 0 8px rgba(74, 222, 128, 0.6))' } : undefined} />
      <circle cx="48" cy="48" r="20" fill="none" stroke="color-mix(in srgb, var(--nd-text) 40%, transparent)" strokeWidth="2" />
      <circle cx="40" cy="48" r="3" fill="color-mix(in srgb, var(--nd-text) 70%, transparent)" />
      <circle cx="56" cy="48" r="3" fill="color-mix(in srgb, var(--nd-text) 70%, transparent)" />
      {on && <circle cx="74" cy="22" r="4" fill="rgb(74, 222, 128)" data-lit />}
    </svg>
  )
}

/** A rocker as on the wall: I up while on, O down while off. */
function Rocker({ on }: { on: boolean }) {
  return (
    <svg width="96" height="96" viewBox="0 0 96 96" aria-hidden>
      <rect x="22" y="10" width="52" height="76" rx="10" fill="color-mix(in srgb, var(--nd-text) 6%, transparent)" stroke="color-mix(in srgb, var(--nd-text) 30%, transparent)" strokeWidth="2" />
      <rect x="30" y={on ? 18 : 48} width="36" height="30" rx="6" fill={on ? 'rgb(74, 222, 128)' : 'color-mix(in srgb, var(--nd-text) 25%, transparent)'} />
      <text x="48" y={on ? 38 : 68} textAnchor="middle" style={{ font: '600 11px Inter, sans-serif', fill: on ? '#062012' : 'color-mix(in srgb, var(--nd-text) 70%, transparent)' }}>{on ? 'I' : 'O'}</text>
    </svg>
  )
}

/** The toggle of a phone: a knob that slides right while on. */
export function Toggle({ on, label, disabled, onFlip, small = false }: { on: boolean; label: string; disabled: boolean; onFlip: () => void; small?: boolean }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled} className={`switch-toggle ${on ? 'is-on' : ''} ${small ? 'is-small' : ''}`}
      onClick={(event) => {
        event.stopPropagation()
        onFlip()
      }}>
      <i />
    </button>
  )
}

/** Asked before a switch goes off, when the element says so: the fridge, the server, the router this page comes through. */
export function ConfirmOff({ name, onYes, onNo }: { name: string; onYes: () => void; onNo: () => void }) {
  const { t } = useTranslation()
  return (
    <Dialog open onClose={onNo} title={t('homePage.switches.confirmTitle', { name })} size="sm"
      footer={
        <>
          <button type="button" className="btn" onClick={onNo}>{t('common.cancel')}</button>
          <button type="button" className="btn btn-danger" onClick={onYes}>{t('homePage.switches.switchOff')}</button>
        </>
      }>
      <p className="text-sm text-muted" data-confirm>{t('homePage.switches.confirmText')}</p>
    </Dialog>
  )
}

interface Props {
  element: HomeSwitch
  said: Said
  /** On or off asked and not yet answered. */
  wanted: boolean | undefined
  arranging: boolean
  wide: boolean
  width: number | null
  pageId: number
  /** Null for who may only look. */
  onSwitch: ((on: boolean) => void) | null
  onStyle: (style: SwitchStyle) => void
  onConfirm: (confirm: boolean) => void
  onRemove: () => void
  haName: string
  onLabel: (label: string) => void
}

/**
 * A switch or a helper in one of six styles: a tap switches it, asked first
 * before it goes off where the element says so; holding it or a right click
 * opens its details with what it draws and used today.
 */
export function SwitchControl({ element, said, wanted, arranging, wide, width, pageId, onSwitch, onStyle, onConfirm, onRemove, haName, onLabel }: Props) {
  const { t } = useTranslation()
  const info = known(said)
  const words = switchWords(said, wanted, t)
  const name = element.label || info?.name || element.name
  const live = Boolean(onSwitch) && !arranging && Boolean(info) && !info?.unavailable
  const [asking, setAsking] = useState(false)
  const [details, setDetails] = useState(false)
  const flip = () => {
    if (!live || words.pending) return
    if (words.on && element.confirm) {
      setAsking(true)
      return
    }
    onSwitch?.(!words.on)
  }
  const main = {
    onClick: () => (arranging ? undefined : flip()),
    onContextMenu: (event: React.MouseEvent) => {
      if (arranging) return
      event.preventDefault()
      setDetails(true)
    },
    role: 'switch',
    'aria-checked': words.on,
    tabIndex: arranging ? -1 : 0,
    onKeyDown: (event: React.KeyboardEvent) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        flip()
      }
    },
    'aria-label': `${name}: ${words.text}`,
    'data-main': '',
  }
  const state = `switch ${words.on ? 'is-on' : ''} ${words.pending ? 'is-pending' : ''} ${words.quiet && !words.missing ? 'is-offline' : ''} ${words.missing ? 'is-missing' : ''}`
  const sized = wide ? { width: '100%' } : width !== null ? { width } : undefined
  let face: ReactNode
  if (element.style === 'pill') {
    face = (
      <div className={`sensor-pill ${state} cursor-pointer`} style={sized} {...main}>
        <span className="sensor-icon switch-icon">{signOf(element.entity_id, said)}</span>
        <Marquee text={name} className="flex-1 font-medium" />
        <span className="sensor-state num" data-state>{words.text}</span>
      </div>
    )
  } else if (element.style === 'chip') {
    face = (
      <span className={`sensor-chip ${state} cursor-pointer`} style={sized} {...main}>
        <i aria-hidden />
        <Marquee text={name} />
        <span className="sr-only" data-state>{words.text}</span>
      </span>
    )
  } else if (element.style === 'toggle') {
    const sub = element.entity_id.startsWith('input_boolean.') ? t('homePage.switches.helper')
      : [info?.device_class === 'outlet' ? t('homePage.switches.outlet') : '', info?.on && typeof info.power === 'number' ? watts(info.power) : ''].filter(Boolean).join(' · ')
    face = (
      <div className={`sensor-tile switch-row ${state}`} style={sized} onContextMenu={main.onContextMenu}>
        <div className="flex-1 min-w-0">
          <Marquee text={name} className="text-[13px] font-medium" />
          <div className="text-[11px] text-muted truncate" data-state>{words.quiet || words.pending ? words.text : sub}</div>
        </div>
        <Toggle on={words.on} label={name} disabled={!live || words.pending} onFlip={flip} />
      </div>
    )
  } else if (element.style === 'tile') {
    face = (
      <div className={`sensor-tile reading ${state} cursor-pointer`} {...main}>
        <Marquee text={name} className="text-[11.5px] text-muted" />
        <span className="num text-[24px] font-semibold mt-1.5 leading-tight">{info && typeof info.power === 'number' ? watts(info.on ? info.power : 0) : words.on ? t('homePage.switches.onWord') : t('homePage.switches.offWord')}</span>
        <span className={`mt-auto text-[12px] ${words.on ? 'text-ok' : 'text-muted'}`} data-state>{words.quiet || words.pending ? words.text : words.on ? t('homePage.on') : t('homePage.off')}</span>
      </div>
    )
  } else {
    face = (
      <div className={`sensor-draw ${state} cursor-pointer`} {...main}>
        {element.style === 'outlet' ? <Outlet on={words.on} /> : <Rocker on={words.on} />}
        <Marquee text={name} className="text-[12px] mt-1" />
        <div className="sensor-state text-[11px] num" data-state>{words.text}</div>
      </div>
    )
  }
  return (
    <div className={`relative ${wide && (element.style === 'pill' || element.style === 'toggle') ? 'w-full' : 'w-fit'}`} data-switch={element.entity_id} data-style={element.style}
      data-on={words.on || undefined}>
      {face}
      {arranging && (
        <SensorTools styles={SWITCH_STYLES} current={element.style} group="switchStyles" onStyle={(style) => onStyle(style as SwitchStyle)} onRemove={onRemove}
          removeLabel={t('homePage.switches.remove')} width={width} wide={wide} rename={{ label: element.label ?? '', fallback: haName, onLabel }}
          extra={(
            <button type="button" className={`btn btn-icon h-6 w-6 rounded-full glass-strong ${element.confirm ? 'text-accent' : ''}`} onClick={() => onConfirm(!element.confirm)}
              aria-pressed={Boolean(element.confirm)} aria-label={t('homePage.switches.askFirst')} title={t('homePage.switches.askFirst')}>
              <ShieldCheck size={12} />
            </button>
          )} />
      )}
      {asking && <ConfirmOff name={name} onNo={() => setAsking(false)} onYes={() => {
        setAsking(false)
        onSwitch?.(false)
      }} />}
      {details && <SwitchDetails name={name} said={said} words={words} live={live} pageId={pageId} elementId={element.id} onFlip={flip} onClose={() => setDetails(false)} />}
    </div>
  )
}

/** N: a switch's details: what it draws now, used today, on since when, and the switch. */
export function SwitchDetails({ name, said, words, live, pageId, elementId, member, onFlip, onClose }: {
  name: string
  said: Said
  words: ReturnType<typeof switchWords>
  live: boolean
  pageId: number
  elementId: string
  member?: string
  onFlip: () => void
  onClose: () => void
}) {
  const { t, i18n } = useTranslation()
  const info = known(said)
  const energy = useQuery({
    queryKey: ['home-switch-energy', pageId, elementId, member ?? ''],
    queryFn: () => get<{ today: number | null }>(`/pages/${pageId}/home/switches/${elementId}/energy${member ? `?member=${member}` : ''}`),
    enabled: Boolean(info?.energy_entity),
  })
  const since = info?.since ? new Intl.DateTimeFormat(i18n.language, { hour: 'numeric', minute: '2-digit' }).format(new Date(info.since)) : ''
  return (
    <Dialog open onClose={onClose} title={name} size="sm">
      <div className="grid gap-4" data-switch-details>
        <div className="num flex flex-wrap gap-x-5 gap-y-1 text-[12.5px] text-muted">
          {typeof info?.power === 'number' && <span>{t('homePage.switches.now')} <b className="text-[var(--nd-text)]" data-power>{watts(info.on ? info.power : 0)}</b></span>}
          {energy.data?.today !== undefined && energy.data.today !== null && (
            <span>{t('homePage.switches.today')} <b className="text-[var(--nd-text)]" data-energy>{energy.data.today.toFixed(energy.data.today >= 10 ? 1 : 2)} kWh</b></span>
          )}
          {since && <span>{words.on ? t('homePage.switches.onSince') : t('homePage.switches.offSince')} <b className="text-[var(--nd-text)]">{since}</b></span>}
        </div>
        <div className="flex items-center justify-between">
          <span className="text-sm">{words.quiet ? words.text : t('homePage.switches.switch')}</span>
          <Toggle on={words.on} label={name} disabled={!live || words.pending} onFlip={onFlip} />
        </div>
      </div>
    </Dialog>
  )
}

interface CardProps {
  element: HomeSwitches
  actions: Record<string, ActionState>
  wanted: Record<string, boolean>
  arranging: boolean
  wide: boolean
  width: number | null
  pageId: number
  onSwitch: ((on: boolean, member?: string) => void) | null
  onConfirm: (confirm: boolean) => void
  onSensors: () => void
  onRemove: () => void
  onTitle: (title: string) => void
}

/** K: switches together, all on or all off, what they draw together, each with its own toggle and details. */
export function SwitchesCard({ element, actions, wanted, arranging, wide, width, pageId, onSwitch, onConfirm, onSensors, onRemove, onTitle }: CardProps) {
  const { t } = useTranslation()
  const [asking, setAsking] = useState<{ member?: string; name: string } | null>(null)
  const [details, setDetails] = useState<string | null>(null)
  const size = wide ? undefined : width !== null ? { width } : undefined
  const total = totalPower(element.sensors, actions)
  const live = Boolean(onSwitch) && !arranging
  const title = element.title || t('homePage.switches.group')
  const off = (member?: string, name = title) => (element.confirm ? setAsking({ member, name }) : onSwitch?.(false, member))
  const detailed = element.sensors.find((one) => one.entity_id === details)
  return (
    <div className={`relative ${wide ? 'w-full' : 'w-fit'}`} data-switches={element.id}>
      <div className="stat-card" style={size}>
        <div className="flex items-center gap-2">
          <b className="text-[13px] font-semibold truncate">{title}</b>
          {total !== null && <small className="num text-[11px] text-muted ml-auto whitespace-nowrap" data-total>{t('homePage.switches.total', { value: watts(total) })}</small>}
          {live && (
            <span className={`flex gap-1.5 ${total === null ? 'ml-auto' : ''}`}>
              <button type="button" className="switch-all" onClick={() => onSwitch?.(true)}>{t('homePage.switches.allOn')}</button>
              <button type="button" className="switch-all" onClick={() => off()}>{t('homePage.switches.allOff')}</button>
            </span>
          )}
        </div>
        <ul className="grid gap-2 mt-2.5">
          {element.sensors.map((sensor) => {
            const said = actions[sensor.entity_id]
            const info = known(said)
            const words = switchWords(said, wanted[sensor.entity_id], t)
            const name = info?.name || sensor.name
            return (
              <li key={sensor.entity_id} className={`flex items-center gap-2.5 text-[12.5px] ${words.quiet ? 'text-muted' : ''}`} data-member={sensor.entity_id}
                onContextMenu={(event) => {
                  if (arranging) return
                  event.preventDefault()
                  setDetails(sensor.entity_id)
                }}>
                <Toggle on={words.on} small label={name} disabled={!live || !info || info.unavailable || words.pending}
                  onFlip={() => (words.on ? off(sensor.entity_id, name) : onSwitch?.(true, sensor.entity_id))} />
                <button type="button" className="truncate flex-1 min-w-0 text-left" onClick={() => !arranging && setDetails(sensor.entity_id)} disabled={arranging}>{name}</button>
                <small className={`num text-[11px] whitespace-nowrap ${words.missing ? 'text-bad' : 'text-muted'}`}>
                  {words.quiet || words.pending ? words.text : words.on ? (typeof info?.power === 'number' ? watts(info.power) : t('homePage.on')) : t('homePage.off')}
                </small>
              </li>
            )
          })}
        </ul>
      </div>
      {arranging && (
        <>
          {!wide && <span className="home-grip" data-resize aria-hidden title={t('homePage.dragWidth')} />}
          <span className="absolute -top-3 -right-3 z-10 flex gap-1" data-element-tool>
            <button type="button" className={`btn btn-icon h-6 w-6 rounded-full glass-strong ${element.confirm ? 'text-accent' : ''}`} onClick={() => onConfirm(!element.confirm)}
              aria-pressed={Boolean(element.confirm)} aria-label={t('homePage.switches.askFirst')} title={t('homePage.switches.askFirst')}>
              <ShieldCheck size={12} />
            </button>
            <button type="button" className="btn btn-icon h-6 w-6 rounded-full glass-strong" onClick={onSensors} aria-label={t('homePage.stats.chooseSensors')} title={t('homePage.stats.chooseSensors')}>
              <Activity size={12} />
            </button>
            <Rename label={element.title} fallback={t('homePage.switches.group')} onLabel={onTitle} />
            <button type="button" className="btn btn-icon btn-danger h-6 w-6 rounded-full glass-strong" onClick={onRemove} aria-label={t('homePage.sensors.removeCard')} title={t('homePage.sensors.removeCard')}>
              <Trash2 size={12} />
            </button>
          </span>
        </>
      )}
      {asking && <ConfirmOff name={asking.name} onNo={() => setAsking(null)} onYes={() => {
        const member = asking.member
        setAsking(null)
        onSwitch?.(false, member)
      }} />}
      {detailed && (() => {
        const said = actions[detailed.entity_id]
        const words = switchWords(said, wanted[detailed.entity_id], t)
        const info = known(said)
        const name = info?.name || detailed.name
        return (
          <SwitchDetails name={name} said={said} words={words} live={live && Boolean(info) && !info?.unavailable} pageId={pageId} elementId={element.id} member={detailed.entity_id}
            onFlip={() => (words.on ? off(detailed.entity_id, name) : onSwitch?.(true, detailed.entity_id))} onClose={() => setDetails(null)} />
        )
      })()}
    </div>
  )
}
