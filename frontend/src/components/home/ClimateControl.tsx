import { useQuery } from '@tanstack/react-query'
import { Flame, Minus, Plus, Power, Snowflake, Thermometer, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { get } from '../../api/client'
import { temperature, type ClimateOffer, type ClimateSensor, type ClimateView, type HomeClimate } from '../../lib/home'

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
  pageId: number
  /** The target shown: what was just asked, or what the thermostat says. */
  target: number | null
  /** A target asked and not yet confirmed: "setting". */
  setting: boolean
  /** Plus and minus, for those who may act on the board, while the thermostat takes a target. */
  onStep?: (steps: number) => void
  onDetails: () => void
  onRemove: () => void
  onSensor: (sensor: ClimateSensor | null) => void
}

/**
 * A thermostat as a pill in the look of the lamps: what it does, its name,
 * the room's temperature, and its target between minus and plus. A tap on
 * the pill opens its details (mode, presets) rather than switching anything:
 * a heating turned off by a brushed finger is not noticed until it is cold.
 */
export function ClimateControl({ element, info, missing, arranging, wide, pageId, target, setting, onStep, onDetails, onRemove, onSensor }: Props) {
  const { t } = useTranslation()
  const [choosing, setChoosing] = useState(false)
  const tools = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!choosing) return
    const away = (event: PointerEvent) => {
      if (!tools.current?.contains(event.target as Node)) setChoosing(false)
    }
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setChoosing(false)
    }
    window.addEventListener('pointerdown', away, true)
    window.addEventListener('keydown', key)
    return () => {
      window.removeEventListener('pointerdown', away, true)
      window.removeEventListener('keydown', key)
    }
  }, [choosing])

  const name = info?.name || element.name || element.entity_id
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
  const steppable = Boolean(onStep) && !quiet && info?.on && info.settable && !arranging

  return (
    // ⚠️ The tools stand beside the pill, not in it: the pill clips what reaches past its edge.
    <div ref={tools} className={`relative ${wide ? 'w-full' : 'w-fit'}`}>
      <div
        className={`glass lamp-pill lamp-control ${wide ? 'w-full h-12' : 'h-10 max-w-[320px]'} ${quiet ? 'lamp-quiet' : ''} !pr-1.5`}
        style={lit}
        data-climate={element.entity_id}
        title={[name, info?.area, fallback, missing ? t('homePage.missing') : info?.unavailable ? t('homePage.unavailable') : ''].filter(Boolean).join(' · ')}
      >
        <button
          type="button"
          className="flex items-center gap-2.5 min-w-0 flex-1 h-full text-left cursor-pointer disabled:cursor-default"
          disabled={!info || arranging}
          onClick={onDetails}
          aria-label={label}
          aria-haspopup="dialog"
        >
          <span className="relative grid place-items-center w-7 h-7 rounded-full flex-none transition-colors duration-200"
            style={colour ? { background: colour, color: '#1b1206' } : { background: 'color-mix(in srgb, var(--nd-text) 9%, transparent)' }}>
            {icon}
          </span>
          <span className="text-[13px] font-medium whitespace-nowrap min-w-0 truncate">{name}</span>
          {reading && (
            <span className={`num text-[12px] whitespace-nowrap flex-none ${fallback ? 'text-warn' : 'text-muted'}`} data-reading>
              {reading}
              {fallback && <span aria-hidden> *</span>}
            </span>
          )}
        </button>
        <span className="flex items-center gap-0.5 flex-none ml-auto">
          {steppable && (
            <button type="button" className="btn btn-icon btn-flat h-7 w-7 rounded-full" onClick={() => onStep?.(-1)} aria-label={t('homePage.colder', { name })} title={t('homePage.colder', { name })}
              disabled={target !== null && info !== null && target <= info.min}>
              <Minus size={14} />
            </button>
          )}
          <span className={`num text-[13px] font-semibold whitespace-nowrap min-w-[3.25rem] text-center ${setting ? 'animate-pulse' : ''} ${info?.on && !quiet ? '' : 'text-muted font-medium'}`}
            data-target aria-live="polite" title={setting ? t('homePage.setting') : undefined}>
            {state}
          </span>
          {steppable && (
            <button type="button" className="btn btn-icon btn-flat h-7 w-7 rounded-full" onClick={() => onStep?.(1)} aria-label={t('homePage.warmer', { name })} title={t('homePage.warmer', { name })}
              disabled={target !== null && info !== null && target >= info.max}>
              <Plus size={14} />
            </button>
          )}
        </span>
      </div>
      {arranging && (
        <span className="absolute -top-3 -right-3 z-10 flex gap-1" data-element-tool>
          <button type="button" className="btn btn-icon h-6 w-6 rounded-full glass-strong" onClick={() => setChoosing((open) => !open)}
            aria-label={t('homePage.chooseSensor')} title={t('homePage.chooseSensor')} aria-haspopup="menu" aria-expanded={choosing}>
            <Thermometer size={12} />
          </button>
          <button type="button" className="btn btn-icon btn-danger h-6 w-6 rounded-full glass-strong" onClick={onRemove} aria-label={t('homePage.removeClimate')} title={t('homePage.removeClimate')}>
            <Trash2 size={12} />
          </button>
        </span>
      )}
      {arranging && choosing && <SensorMenu pageId={pageId} chosen={element.sensor} onChoose={(sensor) => { setChoosing(false); onSensor(sensor) }} />}
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
