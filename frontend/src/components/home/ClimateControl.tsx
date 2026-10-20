import { useQuery } from '@tanstack/react-query'
import { Flame, Minus, Palette, Plus, Power, Snowflake, Thermometer, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { get } from '../../api/client'
import { byHand, CLIMATE_STYLES, STEP_PX, stepTarget, targetAt, temperature, type ClimateOffer, type ClimateSensor, type ClimateStyle, type ClimateView, type HomeClimate } from '../../lib/home'
import { climateFace } from './ClimateFace'
import { Marquee } from './Marquee'
import { Rename } from './Rename'

/** The colours of what a thermostat is doing, on the icon and the pill's edge. */
export const HEATING = 'rgb(251, 146, 60)'
export const COOLING = 'rgb(96, 165, 250)'

/** The icon and the light of a thermostat: flame while heating, snow while cooling, power when off. */
export function climateLook(info: ClimateView | null): { colour: string | null; icon: ReactNode } {
  if (!info || info.unavailable) return { colour: null, icon: <Thermometer size={15} className="text-muted" /> }
  if (!info.on) return { colour: null, icon: <Power size={14} className="text-muted" /> }
  if (info.action === 'heating' || info.action === 'preheating') return { colour: HEATING, icon: <Flame size={15} /> }
  if (info.action === 'cooling') return { colour: COOLING, icon: <Snowflake size={15} /> }
  return { colour: null, icon: <Thermometer size={15} className="text-accent" /> }
}

interface Props {
  element: HomeClimate
  info: ClimateView | null
  missing: boolean
  arranging: boolean
  wide: boolean
  /** Its width on the surface (``controlWidth``), for the pill, the chip and the slider; null for the others. */
  width: number | null
  pageId: number
  /** The target shown: what was just asked, or what the thermostat says. */
  target: number | null
  /** A target asked and not yet confirmed: "setting". */
  setting: boolean
  /** Plus and minus, for those who may act on the board, while the thermostat takes a target. */
  onStep?: (steps: number) => void
  /** A target from a swipe: shown while the finger moves, sent when it lets go. */
  onAim?: (value: number, send: boolean) => void
  onDetails: () => void
  onRemove: () => void
  onSensor: (sensor: ClimateSensor | null) => void
  onStyle: (style: ClimateStyle) => void
  /** Home Assistant's name, for the pencil's field. */
  haName: string
  onLabel: (label: string) => void
}

/** How far a pointer travels before a press becomes a swipe. */
const SWIPE_PX = 6

/**
 * A thermostat, drawn in its style: what it does, the room's temperature,
 * and its target. Swiping sideways sets the target (the dial and the valve
 * head are turned, the finger's place on the circle is the target); plus,
 * minus and the arrow keys move it a step. A tap opens its details rather
 * than switching anything: a heating turned off by a brushed finger is not
 * noticed until it is cold.
 */
export function ClimateControl({ element, info, missing, arranging, wide, width, pageId, target, setting, onStep, onAim, onDetails, onRemove, onSensor, onStyle, haName, onLabel }: Props) {
  const { t } = useTranslation()
  const [choosing, setChoosing] = useState<'sensor' | 'style' | null>(null)
  const tools = useRef<HTMLDivElement>(null)
  const press = useRef<{ pointer: number; x: number; y: number; from: number; centre: [number, number]; swiping: boolean; last: number } | null>(null)
  /** Set when a press ended as a swipe, so the click that follows it opens nothing. */
  const swallow = useRef(false)
  useEffect(() => {
    if (!choosing) return
    const away = (event: PointerEvent) => {
      if (!tools.current?.contains(event.target as Node)) setChoosing(null)
    }
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setChoosing(null)
    }
    window.addEventListener('pointerdown', away, true)
    window.addEventListener('keydown', key)
    return () => {
      window.removeEventListener('pointerdown', away, true)
      window.removeEventListener('keydown', key)
    }
  }, [choosing])

  const name = element.label || info?.name || element.name || element.entity_id
  const quiet = missing || Boolean(info?.unavailable)
  const { colour, icon } = climateLook(info)
  const reading = info ? temperature(info.reading) : ''
  const aim = !info ? '' : info.unavailable ? t('homePage.offline') : !info.on ? t('homePage.off') : info.settable ? temperature(target) : info.target_low !== null && info.target_high !== null ? `${temperature(info.target_low)}–${temperature(info.target_high)}` : '–'
  const state = missing ? t('homePage.gone') : aim
  const fallback = info?.sensor && info.sensor.state !== 'ok' ? t('homePage.sensorFallback', { name: info.sensor.name }) : ''
  const lit: CSSProperties | undefined = colour
    ? { borderColor: `color-mix(in srgb, ${colour} 50%, transparent)`, background: `color-mix(in srgb, ${colour} 12%, var(--nd-surface))`, boxShadow: `0 0 22px -8px ${colour}` }
    : undefined
  const label = [name, reading && t('homePage.reading', { value: reading }), state && t('homePage.targetIs', { value: state }), setting ? t('homePage.setting') : ''].filter(Boolean).join(', ')
  const steppable = Boolean(onStep) && !quiet && Boolean(info?.on) && Boolean(info?.settable) && !arranging
  const pill = element.style === 'pill' || !CLIMATE_STYLES.includes(element.style)
  const face = pill ? null : climateFace({
    style: element.style, info, name, target, aim: state, quiet, icon, fallback: Boolean(fallback), setting,
    colour: colour ?? (info?.on && !quiet ? 'var(--nd-accent)' : 'var(--nd-text-faint)'), working: Boolean(colour),
  })
  const round = face?.round ?? false
  const sized: CSSProperties = !wide && width ? { width, maxWidth: 'none' } : {}

  // -- swiping ---------------------------------------------------------------

  const down = (event: ReactPointerEvent<HTMLButtonElement>) => {
    if (!steppable || !info || event.button !== 0) return
    swallow.current = false
    const rect = event.currentTarget.getBoundingClientRect()
    const from = target ?? info.target ?? info.reading ?? (info.min + info.max) / 2
    press.current = { pointer: event.pointerId, x: event.clientX, y: event.clientY, from, centre: [rect.left + rect.width / 2, rect.top + Math.min(rect.width, rect.height) / 2], swiping: false, last: from }
  }
  const move = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const held = press.current
    if (!held || held.pointer !== event.pointerId || !info) return
    const dx = event.clientX - held.x
    const dy = event.clientY - held.y
    if (!held.swiping) {
      if (round ? Math.hypot(dx, dy) < SWIPE_PX : Math.abs(dx) < SWIPE_PX || Math.abs(dx) < Math.abs(dy)) return
      held.swiping = true
      swallow.current = true
      try {
        event.currentTarget.setPointerCapture(event.pointerId)
      } catch {
        // A pointer that is already gone has nothing to capture.
      }
    }
    let value: number
    if (round) {
      // Turned like a dial: the angle on its three quarters of a circle, from bottom left round to bottom right.
      const angle = (Math.atan2(event.clientY - held.centre[1], event.clientX - held.centre[0]) * 180) / Math.PI
      const turned = (((angle - 135) % 360) + 360) % 360
      value = targetAt(byHand(info), turned > 270 ? (turned > 315 ? 0 : 1) : turned / 270)
    } else {
      value = stepTarget(byHand(info), held.from, Math.round(dx / STEP_PX))
    }
    if (value === held.last) return
    held.last = value
    onAim?.(value, false)
  }
  const up = () => {
    const held = press.current
    press.current = null
    if (held?.swiping) onAim?.(held.last, true)
  }
  const key = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (!steppable) return
    const steps = event.key === 'ArrowRight' || event.key === 'ArrowUp' ? 1 : event.key === 'ArrowLeft' || event.key === 'ArrowDown' ? -1 : 0
    if (!steps) return
    event.preventDefault()
    onStep?.(steps)
  }
  const mainProps = {
    type: 'button' as const,
    disabled: !info || arranging,
    'aria-label': label,
    'aria-haspopup': 'dialog' as const,
    'data-main': '',
    onPointerDown: down,
    onPointerMove: move,
    onPointerUp: up,
    onPointerCancel: up,
    onKeyDown: key,
    onClick: () => {
      if (swallow.current) {
        swallow.current = false
        return
      }
      onDetails()
    },
  }
  const title = [name, info?.area, fallback, missing ? t('homePage.missing') : info?.unavailable ? t('homePage.unavailable') : steppable ? t('homePage.swipeHint') : ''].filter(Boolean).join(' · ')
  const stepButton = (steps: number, extra = '') => (
    <button type="button" className={`btn btn-icon btn-flat h-7 w-7 rounded-full ${extra}`} onClick={() => onStep?.(steps)}
      aria-label={t(steps > 0 ? 'homePage.warmer' : 'homePage.colder', { name })} title={t(steps > 0 ? 'homePage.warmer' : 'homePage.colder', { name })}
      disabled={target !== null && info !== null && (steps > 0 ? target >= info.max : target <= info.min)}>
      {steps > 0 ? <Plus size={14} /> : <Minus size={14} />}
    </button>
  )

  return (
    // ⚠️ The tools stand beside the drawing, not in it: a pill clips what reaches past its edge.
    <div ref={tools} className={`relative ${wide ? 'w-full' : 'w-fit'}`}>
      {pill ? (
        <div
          className={`glass lamp-pill lamp-control ${wide ? 'w-full h-12' : 'h-10'} ${quiet ? 'lamp-quiet' : ''} !pr-1.5`}
          style={{ ...sized, ...lit }}
          data-climate={element.entity_id}
          data-style="pill"
          title={title}
        >
          <button {...mainProps} className={`flex items-center gap-2.5 min-w-0 flex-1 h-full text-left cursor-pointer disabled:cursor-default ${steppable ? 'touch-pan-y select-none' : ''}`}>
            <span className="relative grid place-items-center w-7 h-7 rounded-full flex-none transition-colors duration-200"
              style={colour ? { background: colour, color: '#1b1206' } : { background: 'color-mix(in srgb, var(--nd-text) 9%, transparent)' }}>
              {icon}
            </span>
            <Marquee text={name} className="flex-1 text-[13px] font-medium" />
            {reading && (
              <span className={`num text-[12px] whitespace-nowrap flex-none ${fallback ? 'text-warn' : 'text-muted'}`} data-reading>
                {reading}
                {fallback && <span aria-hidden> *</span>}
              </span>
            )}
          </button>
          <span className="flex items-center gap-0.5 flex-none ml-auto">
            {steppable && stepButton(-1)}
            <span className={`num text-[13px] font-semibold whitespace-nowrap min-w-[3.25rem] text-center ${setting ? 'animate-pulse' : ''} ${info?.on && !quiet ? '' : 'text-muted font-medium'}`}
              data-target aria-live="polite" title={setting ? t('homePage.setting') : undefined}>
              {state}
            </span>
            {steppable && stepButton(1)}
          </span>
        </div>
      ) : (
        <button
          {...mainProps}
          className={`lamp-control ${face!.className} ${steppable ? 'cursor-pointer select-none' : ''} ${round ? 'touch-none' : 'touch-pan-y'} ${setting ? 'is-setting' : ''}`}
          style={{ ...face!.style, ...sized }}
          data-climate={element.entity_id}
          data-style={element.style}
          title={title}
        >
          {face!.children}
        </button>
      )}
      {!pill && element.style === 'tile' && steppable && (
        // The tile's plus and minus, beside its drawing: a button holds no buttons.
        <>
          {stepButton(-1, 'absolute left-1 bottom-1 h-6 w-6')}
          {stepButton(1, 'absolute right-1 bottom-1 h-6 w-6')}
        </>
      )}
      {arranging && width !== null && !wide && <span className="home-grip" data-resize aria-hidden title={t('homePage.dragWidth')} />}
      {arranging && (
        <span className="absolute -top-3 -right-3 z-10 flex gap-1" data-element-tool>
          <button type="button" className="btn btn-icon h-6 w-6 rounded-full glass-strong" onClick={() => setChoosing((open) => (open === 'style' ? null : 'style'))}
            aria-label={t('homePage.chooseStyle')} title={t('homePage.chooseStyle')} aria-haspopup="menu" aria-expanded={choosing === 'style'}>
            <Palette size={12} />
          </button>
          <button type="button" className="btn btn-icon h-6 w-6 rounded-full glass-strong" onClick={() => setChoosing((open) => (open === 'sensor' ? null : 'sensor'))}
            aria-label={t('homePage.chooseSensor')} title={t('homePage.chooseSensor')} aria-haspopup="menu" aria-expanded={choosing === 'sensor'}>
            <Thermometer size={12} />
          </button>
          <Rename label={element.label ?? ''} fallback={haName} onLabel={onLabel} />
          <button type="button" className="btn btn-icon btn-danger h-6 w-6 rounded-full glass-strong" onClick={onRemove} aria-label={t('homePage.removeClimate')} title={t('homePage.removeClimate')}>
            <Trash2 size={12} />
          </button>
        </span>
      )}
      {arranging && choosing === 'sensor' && <SensorMenu pageId={pageId} chosen={element.sensor} onChoose={(sensor) => { setChoosing(null); onSensor(sensor) }} />}
      {arranging && choosing === 'style' && (
        <div className="absolute left-0 top-full mt-2 z-30 glass-strong rounded-xl p-1.5 shadow-2xl grid grid-cols-2 gap-1 w-64" role="menu" aria-label={t('homePage.chooseStyle')} data-element-tool>
          {CLIMATE_STYLES.map((style) => (
            <button key={style} type="button" role="menuitemradio" aria-checked={element.style === style}
              className={`text-left text-[13px] px-2.5 py-1.5 rounded-lg ${element.style === style ? 'bg-[var(--nd-accent-soft)] text-accent font-medium' : 'hover:bg-[var(--nd-surface-hover)]'}`}
              onClick={() => {
                setChoosing(null)
                onStyle(style)
              }}>
              {t(`homePage.climateStyles.${style}`)}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/** Which temperature the room is read by: the thermostat's own, or one of the house's temperature sensors. */
function SensorMenu({ pageId, chosen, onChoose }: { pageId: number; chosen: ClimateSensor | null; onChoose: (sensor: ClimateSensor | null) => void }) {
  const { t } = useTranslation()
  const offer = useQuery({ queryKey: ['home-climates', pageId], queryFn: () => get<ClimateOffer>(`/pages/${pageId}/home/climates`), staleTime: 30_000 })
  const item = (selected: boolean) => `w-full text-left text-[13px] px-2.5 py-1.5 rounded-lg ${selected ? 'bg-[var(--nd-accent-soft)] text-accent font-medium' : 'hover:bg-[var(--nd-surface-hover)]'}`
  return (
    <div className="absolute left-0 top-full mt-2 z-30 glass-strong rounded-xl p-1.5 shadow-2xl w-72 max-h-72 overflow-y-auto" role="menu" aria-label={t('homePage.chooseSensor')} data-element-tool>
      <button type="button" role="menuitemradio" aria-checked={!chosen} className={item(!chosen)} onClick={() => onChoose(null)}>
        {t('homePage.thermostatReading')}
      </button>
      {offer.isLoading && <p className="text-xs text-muted px-2.5 py-2">…</p>}
      {(offer.data?.sensors ?? []).map((sensor) => (
        <button key={sensor.rid || sensor.entity_id} type="button" role="menuitemradio" aria-checked={chosen?.rid === sensor.rid} className={item(chosen?.rid === sensor.rid)}
          onClick={() => onChoose({ rid: sensor.rid, entity_id: sensor.entity_id, name: sensor.name })}>
          <span className="flex items-baseline justify-between gap-2">
            <span className="truncate">{sensor.name}</span>
            <span className="num text-[11.5px] text-muted flex-none">{sensor.unavailable ? t('homePage.offline') : temperature(sensor.current)}</span>
          </span>
          {sensor.area && <span className="block text-[11px] text-faint truncate">{sensor.area}</span>}
        </button>
      ))}
      {offer.data && offer.data.sensors.length === 0 && <p className="text-xs text-muted px-2.5 py-2">{t('homePage.noSensors')}</p>}
    </div>
  )
}
