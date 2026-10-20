import { Minus, Plus } from 'lucide-react'
import type { CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'

import { temperature, type ClimateView, type ClimateWish } from '../../lib/home'
import { Dialog } from '../ui'
import { climateLook, COOLING, HEATING } from './ClimateControl'
import { ClimateHistory } from './ClimateHistory'

interface Props {
  info: ClimateView
  /** The target shown: what was just asked, or what the thermostat says. */
  target: number | null
  setting: boolean
  /** Null for those who may look and nothing more. */
  onStep: ((steps: number) => void) | null
  /** A target from the slider, gathered like the taps. */
  onSlide: ((value: number) => void) | null
  onWish: ((wish: ClimateWish) => void) | null
  onClose: () => void
  /** Where its history is asked: the page and the element. */
  history?: { pageId: number; elementId: string }
}

/**
 * A thermostat's details: the room's temperature and where it is read, the
 * target, and the modes and presets the device names. Nothing is offered
 * that Home Assistant does not say it has.
 */
export function ClimateDetails({ info, target, setting, onStep, onSlide, onWish, onClose, history }: Props) {
  const { t } = useTranslation()
  const { colour, icon } = climateLook(info)
  const steppable = Boolean(onStep) && info.on && info.settable && !info.unavailable
  const words = (group: 'modes' | 'actions', value: string) => t(`homePage.${group}.${value}`, { defaultValue: value.replace(/_/g, ' ') })
  const source = !info.sensor ? t('homePage.fromThermostat')
    : info.sensor.state === 'ok' ? t('homePage.fromSensor', { name: info.sensor.name })
    : t('homePage.sensorFallback', { name: info.sensor.name })

  return (
    <Dialog open onClose={onClose} title={info.name} size={history ? "md" : "sm"}>
      <div className="grid gap-5" data-climate-details>
        <div className="flex items-center gap-3">
          <span className="grid place-items-center w-12 h-12 rounded-full flex-none"
            style={colour ? { background: colour, color: '#1b1206', boxShadow: `0 0 28px -6px ${colour}` } : { background: 'color-mix(in srgb, var(--nd-text) 9%, transparent)' }}>
            {icon}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm text-muted truncate">{info.area || info.entity_id}</p>
            <p className="num text-2xl font-semibold leading-tight" data-reading>{temperature(info.reading)}</p>
            <p className={`text-[11.5px] ${info.sensor && info.sensor.state !== 'ok' ? 'text-warn' : 'text-faint'}`}>{source}</p>
          </div>
          {info.action && <span className="text-xs font-medium px-2.5 py-1 rounded-full glass" data-action>{words('actions', info.action)}</span>}
        </div>

        {history && <ClimateHistory pageId={history.pageId} elementId={history.elementId} />}

        <div className="grid gap-1.5">
          <span className="text-sm font-medium">{t('homePage.target')}</span>
          <div className="flex items-center justify-center gap-4">
            {steppable && (
              <button type="button" className="btn btn-icon h-11 w-11 rounded-full" onClick={() => onStep?.(-1)} aria-label={t('homePage.colder', { name: info.name })} disabled={target !== null && target <= info.min}>
                <Minus size={18} />
              </button>
            )}
            <span className={`num text-3xl font-semibold min-w-[6rem] text-center ${setting ? 'animate-pulse' : ''} ${info.on ? '' : 'text-muted'}`} data-target aria-live="polite">
              {!info.on ? t('homePage.off') : info.settable ? temperature(target) : `${temperature(info.target_low)}–${temperature(info.target_high)}`}
            </span>
            {steppable && (
              <button type="button" className="btn btn-icon h-11 w-11 rounded-full" onClick={() => onStep?.(1)} aria-label={t('homePage.warmer', { name: info.name })} disabled={target !== null && target >= info.max}>
                <Plus size={18} />
              </button>
            )}
          </div>
          {steppable && onSlide && (
            <input type="range" className="lamp-range mt-1" min={info.min} max={info.max} step={info.step} value={target ?? info.min}
              aria-label={t('homePage.target')} aria-valuetext={temperature(target)}
              style={{ '--track': `linear-gradient(to right, ${COOLING}, color-mix(in srgb, var(--nd-text) 20%, transparent) 45%, ${HEATING})` } as CSSProperties}
              onChange={(event) => onSlide(Number(event.target.value))} />
          )}
          <p className="text-center text-[11.5px] text-faint">{setting ? t('homePage.setting') : t('homePage.bounds', { min: temperature(info.min), max: temperature(info.max) })}</p>
        </div>

        {info.modes.length > 0 && (
          <div className="grid gap-1.5">
            <span className="text-sm font-medium">{t('homePage.mode')}</span>
            <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label={t('homePage.mode')}>
              {info.modes.map((mode) => (
                <button key={mode} type="button" role="radio" aria-checked={info.mode === mode} disabled={!onWish}
                  className={`h-8 px-3 rounded-full text-sm font-medium border transition-colors ${info.mode === mode ? 'bg-[var(--nd-accent)] text-[var(--nd-on-accent)] border-transparent' : 'border-[var(--nd-border)] text-muted hover:text-[var(--nd-text)]'}`}
                  onClick={() => info.mode !== mode && onWish?.({ mode })}>
                  {words('modes', mode)}
                </button>
              ))}
            </div>
          </div>
        )}

        {info.presets.length > 0 && (
          <div className="grid gap-1.5">
            <span className="text-sm font-medium">{t('homePage.preset')}</span>
            <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label={t('homePage.preset')}>
              {info.presets.map((preset) => (
                <button key={preset} type="button" role="radio" aria-checked={info.preset === preset} disabled={!onWish}
                  className={`h-8 px-3 rounded-full text-sm border transition-colors ${info.preset === preset ? 'border-[var(--nd-accent)] text-accent font-medium' : 'border-[var(--nd-border)] text-muted hover:text-[var(--nd-text)]'}`}
                  onClick={() => info.preset !== preset && onWish?.({ preset })}>
                  {t(`homePage.presets.${preset}`, { defaultValue: preset.replace(/_/g, ' ') })}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </Dialog>
  )
}
