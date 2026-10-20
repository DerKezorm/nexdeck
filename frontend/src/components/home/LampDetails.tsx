import { Lightbulb, Power } from 'lucide-react'
import { useState, type CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'

import { hsToRgb, lampColour, rgbToHs, type LampInfo, type LampWish } from '../../lib/home'
import { Dialog } from '../ui'

interface Props {
  /** The lamp as it will stand once what was asked is done (``withWish``). */
  info: LampInfo
  onWish: (wish: LampWish) => void
  onClose: () => void
}

/** A few colours to reach in one tap, as hue and saturation. */
const SWATCHES: [number, number][] = [[30, 70], [0, 85], [330, 70], [280, 75], [235, 85], [195, 80], [140, 70], [55, 85]]

/** The colour of a white, for the slider's track; the same arithmetic as ``lampColour``. */
const whiteOf = (kelvin: number) => lampColour({ on: true, rgb: null, kelvin }) ?? 'white'

/**
 * A lamp's details: on or off, how bright, and the white or the colour it
 * has, as far as Home Assistant says it can. Every change goes out as it
 * is made, gathered and spaced by the page (``lampSender``).
 */
export function LampDetails({ info, onWish, onClose }: Props) {
  const { t } = useTranslation()
  const [mode, setMode] = useState<'white' | 'colour'>(() => (info.colour && (!info.temperature || (info.rgb && !info.kelvin)) ? 'colour' : 'white'))
  const colour = lampColour(info)
  const pct = info.on ? (info.pct ?? 100) : 0
  // On whole fifties, so the slider says 2250 K rather than 2252 K; the server keeps the lamp's own ends.
  const low = Math.ceil((info.kelvin_min ?? 2000) / 50) * 50
  const high = Math.floor((info.kelvin_max ?? 6535) / 50) * 50
  const kelvin = Math.min(high, Math.max(low, info.kelvin ?? Math.round((low + high) / 2)))
  // Home Assistant names hue and saturation; a lamp that says only rgb gets them reckoned back.
  const [hue, saturation] = info.hs ?? (info.rgb && !info.kelvin ? rgbToHs(info.rgb) : [30, 70])
  const both = info.temperature && info.colour

  return (
    <Dialog open onClose={onClose} title={info.name} size="sm">
      <div className="grid gap-5" data-lamp-details>
        <div className="flex items-center gap-3">
          <span className="grid place-items-center w-12 h-12 rounded-full flex-none transition-colors duration-200"
            style={colour ? { background: colour, color: '#1b1206', boxShadow: `0 0 28px -6px ${colour}` } : { background: 'color-mix(in srgb, var(--nd-text) 9%, transparent)' }}>
            <Lightbulb size={22} className={colour ? '' : 'text-muted'} />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm text-muted truncate">{info.area || info.entity_id}</p>
            <p className="num text-lg font-semibold">{info.on ? (info.dims ? `${pct} %` : t('homePage.on')) : t('homePage.off')}</p>
          </div>
          <button type="button" className={`btn btn-icon h-11 w-11 rounded-full ${info.on ? 'btn-accent' : ''}`} aria-pressed={info.on}
            aria-label={info.on ? t('homePage.turnOff') : t('homePage.turnOn')} title={info.on ? t('homePage.turnOff') : t('homePage.turnOn')}
            onClick={() => onWish({ on: !info.on })}>
            <Power size={18} />
          </button>
        </div>

        {info.dims && (
          <Slider label={t('homePage.brightness')} value={pct} min={1} max={100} shown={`${pct} %`}
            track={`linear-gradient(to right, color-mix(in srgb, var(--nd-text) 14%, transparent), ${colour ?? 'rgb(255, 196, 120)'})`}
            onChange={(value) => onWish({ brightness_pct: value })} />
        )}

        {both && (
          <div className="grid grid-cols-2 gap-1 p-1 rounded-full glass" role="radiogroup" aria-label={t('homePage.lightKind')}>
            {(['white', 'colour'] as const).map((kind) => (
              <button key={kind} type="button" role="radio" aria-checked={mode === kind}
                className={`h-8 rounded-full text-sm font-medium transition-colors ${mode === kind ? 'bg-[var(--nd-accent)] text-[var(--nd-on-accent)]' : 'text-muted'}`}
                onClick={() => setMode(kind)}>
                {t(kind === 'white' ? 'homePage.white' : 'homePage.colour')}
              </button>
            ))}
          </div>
        )}

        {info.temperature && (!both || mode === 'white') && (
          <Slider label={t('homePage.white')} value={kelvin} min={low} max={high} step={50} shown={`${kelvin} K`}
            track={`linear-gradient(to right, ${whiteOf(low)}, ${whiteOf(high)})`}
            ends={[t('homePage.warm'), t('homePage.cool')]}
            onChange={(value) => onWish({ kelvin: value })} />
        )}

        {info.colour && (!both || mode === 'colour') && (
          <div className="grid gap-4">
            <div className="flex flex-wrap gap-2" role="group" aria-label={t('homePage.colour')}>
              {SWATCHES.map(([h, s]) => {
                const [r, g, b] = hsToRgb(h, s)
                const chosen = info.hs !== null && info.hs !== undefined && Math.abs(info.hs[0] - h) < 1 && Math.abs(info.hs[1] - s) < 1
                return (
                  <button key={`${h}-${s}`} type="button" className={`w-8 h-8 rounded-full border transition-transform hover:scale-110 ${chosen ? 'ring-2 ring-[var(--nd-accent)] ring-offset-2 ring-offset-[var(--nd-surface)]' : ''}`}
                    style={{ background: `rgb(${r}, ${g}, ${b})`, borderColor: 'color-mix(in srgb, var(--nd-text) 15%, transparent)' }}
                    aria-label={t('homePage.swatch', { hue: h })} aria-pressed={chosen} onClick={() => onWish({ hs: [h, s] })} />
                )
              })}
            </div>
            <Slider label={t('homePage.hue')} value={Math.round(hue)} min={0} max={360} shown={`${Math.round(hue)}°`}
              track="linear-gradient(to right, #f00, #ff0 17%, #0f0 33%, #0ff 50%, #00f 67%, #f0f 83%, #f00)"
              onChange={(value) => onWish({ hs: [value, saturation] })} />
            <Slider label={t('homePage.saturation')} value={Math.round(saturation)} min={0} max={100} shown={`${Math.round(saturation)} %`}
              track={`linear-gradient(to right, #fff, rgb(${hsToRgb(hue, 100).join(', ')}))`}
              onChange={(value) => onWish({ hs: [hue, value] })} />
          </div>
        )}
      </div>
    </Dialog>
  )
}

function Slider({ label, value, min, max, step = 1, shown, track, ends, onChange }: {
  label: string
  value: number
  min: number
  max: number
  step?: number
  shown: string
  track: string
  ends?: [string, string]
  onChange: (value: number) => void
}) {
  return (
    <label className="grid gap-1.5">
      <span className="flex items-baseline justify-between text-sm">
        <span className="font-medium">{label}</span>
        <span className="num text-muted text-[12.5px]">{shown}</span>
      </span>
      <input type="range" className="lamp-range" min={min} max={max} step={step} value={value} aria-valuetext={shown}
        style={{ '--track': track } as CSSProperties} onChange={(event) => onChange(Number(event.target.value))} />
      {ends && (
        <span className="flex justify-between text-[11.5px] text-faint">
          <span>{ends[0]}</span>
          <span>{ends[1]}</span>
        </span>
      )}
    </label>
  )
}
