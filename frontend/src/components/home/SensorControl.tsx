import { Palette, Trash2 } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { Marquee } from './Marquee'
import { Rename } from './Rename'
import {
  COMFORT, CONTACT_STYLES, LOW_BATTERY, READING_STYLES, reading, since, temperature,
  type ContactStyle, type HomeContact, type HomeReading, type ReadingStyle, type SensorState,
} from '../../lib/home'

/** The clock the "open for" of every door and window counts by; a tick every half minute is enough for minutes. */
export function useNow(every = 30_000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), every)
    return () => window.clearInterval(timer)
  }, [every])
  return now
}

export const WINDOW_ICON = (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><rect x="4" y="3" width="16" height="18" rx="1.5" /><path d="M12 3v18M4 12h16" /></svg>
)
export const DOOR_ICON = (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="M5 21V4a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v17M3 21h18" /><circle cx="15" cy="12" r="1" /></svg>
)
export const THERMO_ICON = (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="M14 14.76V3.5a2.5 2.5 0 0 0-5 0v11.26a4.5 4.5 0 1 0 5 0z" /></svg>
)
export const DROP_ICON = (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="M12 2.7s-6 6.4-6 11.3a6 6 0 0 0 12 0c0-4.9-6-11.3-6-11.3z" /></svg>
)

const isDoor = (said: SensorState | undefined) => Boolean(said && !said.missing && (said.device_class === 'door' || said.device_class === 'garage_door'))

/** How a door or window stands, in the page's words: open for how long, closed, offline, or gone from Home Assistant. */
export function contactWords(said: SensorState | undefined, now: number, t: (key: string, options?: Record<string, unknown>) => string): { open: boolean; text: string; quiet: boolean; missing: boolean } {
  if (!said || said.missing) return { open: false, text: said ? t('homePage.sensors.missing') : '…', quiet: true, missing: Boolean(said) }
  if (said.unavailable || said.open === null || said.open === undefined) return { open: false, text: t('homePage.offline'), quiet: true, missing: false }
  if (said.open) return { open: true, text: t('homePage.sensors.openFor', { time: since(said.since, now) }), quiet: false, missing: false }
  return { open: false, text: t('homePage.sensors.closed'), quiet: false, missing: false }
}

/** A battery that is running out, as a mark beside the state. */
export function Battery({ said }: { said: SensorState | undefined }) {
  const { t } = useTranslation()
  if (!said || said.missing || said.battery === null || said.battery === undefined || said.battery >= LOW_BATTERY) return null
  return <span className="sensor-battery num" title={t('homePage.sensors.battery', { pct: said.battery })} data-battery>▮ {said.battery} %</span>
}

/** When, as a tile writes it: the time today, "yesterday" and the time, or the date. */
function clock(moment: number | null | undefined, now: number, t: (key: string, options?: Record<string, unknown>) => string, language: string): string {
  if (!moment) return ''
  const time = new Intl.DateTimeFormat(language, { hour: 'numeric', minute: '2-digit' }).format(new Date(moment))
  const day = (value: number) => new Date(value).toDateString()
  if (day(moment) === day(now)) return time
  if (day(moment) === day(now - 86_400_000)) return t('homePage.sensors.yesterdayAt', { time })
  return `${new Intl.DateTimeFormat(language, { day: 'numeric', month: 'numeric' }).format(new Date(moment))} ${time}`
}

/** A window drawn: frame, and a sash tilted in while it is open. */
function WindowDrawing({ open }: { open: boolean }) {
  return (
    <svg width="96" height="96" viewBox="0 0 96 96" aria-hidden>
      <rect x="20" y="10" width="56" height="76" rx="3" fill="none" stroke="color-mix(in srgb, var(--nd-text) 30%, transparent)" strokeWidth="2" />
      {open ? (
        <>
          <polygon points="30,24 66,24 72,82 24,82" fill="color-mix(in srgb, var(--so) 18%, transparent)" stroke="var(--so)" strokeWidth="2.4" />
          <line x1="64" y1="48" x2="64" y2="56" stroke="var(--so)" strokeWidth="2.4" strokeLinecap="round" />
          <path d="M24 14 L30 24 M72 14 L66 24" stroke="var(--so)" strokeOpacity=".5" strokeWidth="1.5" strokeDasharray="2 2" />
        </>
      ) : (
        <>
          <rect x="24" y="14" width="48" height="68" rx="2" fill="color-mix(in srgb, rgb(147,197,253) 12%, transparent)" stroke="color-mix(in srgb, var(--nd-text) 55%, transparent)" strokeWidth="2" />
          <line x1="66" y1="44" x2="66" y2="52" stroke="color-mix(in srgb, var(--nd-text) 70%, transparent)" strokeWidth="2.4" strokeLinecap="round" />
        </>
      )}
    </svg>
  )
}

/** A door drawn: frame, and a leaf that opens toward the eye. */
function DoorDrawing({ open }: { open: boolean }) {
  const line = 'color-mix(in srgb, var(--nd-text) 30%, transparent)'
  return (
    <svg width="96" height="96" viewBox="0 0 96 96" aria-hidden>
      <path d="M24 90V8h48v82" fill="none" stroke={line} strokeWidth="2" />
      {open ? (
        <>
          <rect x="28" y="12" width="40" height="76" fill="color-mix(in srgb, black 30%, transparent)" />
          <polygon points="28,12 58,20 58,82 28,88" fill="color-mix(in srgb, var(--so) 18%, transparent)" stroke="var(--so)" strokeWidth="2.4" />
          <circle cx="52" cy="52" r="2.2" fill="var(--so)" />
        </>
      ) : (
        <>
          <rect x="28" y="12" width="40" height="76" rx="1.5" fill="color-mix(in srgb, var(--nd-text) 8%, transparent)" stroke="color-mix(in srgb, var(--nd-text) 55%, transparent)" strokeWidth="2" />
          <circle cx="61" cy="52" r="2.2" fill="color-mix(in srgb, var(--nd-text) 80%, transparent)" />
        </>
      )}
      <line x1="14" y1="90" x2="82" y2="90" stroke={line} strokeWidth="2" />
    </svg>
  )
}

interface ToolsProps {
  styles: readonly string[]
  current: string
  group: 'contactStyles' | 'readingStyles' | 'coverStyles'
  onStyle: (style: string) => void
  onRemove: () => void
  removeLabel: string
  width: number | null
  wide: boolean
  /** The pencil: the page's own name, and Home Assistant's to fall back to. */
  rename?: { label: string; fallback: string; onLabel: (label: string) => void }
}

/** The palette and the bin beside an element while arranging, and the grip for its width. */
export function SensorTools({ styles, current, group, onStyle, onRemove, removeLabel, width, wide, rename }: ToolsProps) {
  const { t } = useTranslation()
  const [choosing, setChoosing] = useState(false)
  return (
    <>
      {width !== null && !wide && <span className="home-grip" data-resize aria-hidden title={t('homePage.dragWidth')} />}
      <span className="absolute -top-3 -right-3 z-10 flex gap-1" data-element-tool>
        {styles.length > 1 && (
          <button type="button" className="btn btn-icon h-6 w-6 rounded-full glass-strong" onClick={() => setChoosing((open) => !open)}
            aria-label={t('homePage.chooseStyle')} title={t('homePage.chooseStyle')} aria-haspopup="menu" aria-expanded={choosing}>
            <Palette size={12} />
          </button>
        )}
        {rename && <Rename {...rename} />}
        <button type="button" className="btn btn-icon btn-danger h-6 w-6 rounded-full glass-strong" onClick={onRemove} aria-label={removeLabel} title={removeLabel}>
          <Trash2 size={12} />
        </button>
      </span>
      {choosing && (
        <div className="absolute left-0 top-full mt-2 z-30 glass-strong rounded-xl p-1.5 shadow-2xl grid grid-cols-2 gap-1 w-64" role="menu" aria-label={t('homePage.chooseStyle')} data-element-tool>
          {styles.map((style) => (
            <button key={style} type="button" role="menuitemradio" aria-checked={current === style}
              className={`text-left text-[13px] px-2.5 py-1.5 rounded-lg ${current === style ? 'bg-[var(--nd-accent-soft)] text-accent font-medium' : 'hover:bg-[var(--nd-surface-hover)]'}`}
              onClick={() => {
                setChoosing(false)
                onStyle(style)
              }}>
              {t(`homePage.sensors.${group}.${style}`)}
            </button>
          ))}
        </div>
      )}
    </>
  )
}

interface ContactProps {
  element: HomeContact
  said: SensorState | undefined
  now: number
  arranging: boolean
  wide: boolean
  width: number | null
  onStyle: (style: ContactStyle) => void
  onRemove: () => void
  onLabel: (label: string) => void
}

/** A door or window, in one of the five styles of its board of sketches; only shown, nothing to press. */
export function ContactControl({ element, said, now, arranging, wide, width, onStyle, onRemove, onLabel }: ContactProps) {
  const { t, i18n } = useTranslation()
  const words = contactWords(said, now, t)
  const haName = said && !said.missing && said.name ? said.name : element.name
  const name = element.label || haName
  const door = isDoor(said)
  const state = `${words.open ? 'is-open' : ''} ${words.quiet && !words.missing ? 'is-offline' : ''} ${words.missing ? 'is-missing' : ''}`
  const sized = wide ? { width: '100%' } : width !== null ? { width } : undefined
  let face: ReactNode
  if (element.style === 'pill' || element.style === 'chip') {
    face = element.style === 'pill' ? (
      <div className={`sensor-pill ${state}`} style={sized} title={name}>
        <span className="sensor-icon">{door ? DOOR_ICON : WINDOW_ICON}</span>
        <Marquee text={name} className="flex-1 font-medium" />
        <span className="sensor-state" data-state>{words.text}</span>
        <Battery said={said} />
      </div>
    ) : (
      <span className={`sensor-chip ${state}`} style={sized} title={`${name}: ${words.text}`}>
        <i aria-hidden />
        <Marquee text={name} />
        <span className="sr-only" data-state>{words.text}</span>
        <Battery said={said} />
      </span>
    )
  } else if (element.style === 'tile') {
    const changed = said && !said.missing ? said.since : null
    face = (
      <div className={`sensor-tile ${state}`} title={name}>
        <Marquee text={name} className="text-[11.5px] text-muted" />
        <span className="sensor-tile-value" data-state>{words.missing ? words.text : words.quiet ? t('homePage.offline') : words.open ? t('homePage.sensors.openWord') : t('homePage.sensors.closedWord')}</span>
        <span className="num text-[11px] text-faint">
          {!words.quiet && changed ? (words.open ? t('homePage.sensors.sinceTime', { time: clock(changed, now, t, i18n.language) }) : t('homePage.sensors.lastOpen', { time: clock(changed, now, t, i18n.language) })) : ''}
        </span>
        <Battery said={said} />
      </div>
    )
  } else {
    face = (
      <div className={`sensor-draw ${state}`} title={name}>
        {element.style === 'door' ? <DoorDrawing open={words.open} /> : <WindowDrawing open={words.open} />}
        <Marquee text={name} className="text-[12px] mt-1" />
        <div className="sensor-state text-[11px]" data-state>{words.text}</div>
        <Battery said={said} />
      </div>
    )
  }
  return (
    <div className={`relative ${wide && element.style === 'pill' ? 'w-full' : 'w-fit'}`} data-contact={element.entity_id} data-style={element.style} data-open={words.open || undefined}>
      {face}
      {arranging && (
        <SensorTools styles={CONTACT_STYLES} current={element.style} group="contactStyles" onStyle={(style) => onStyle(style as ContactStyle)} onRemove={onRemove}
          removeLabel={t('homePage.sensors.removeContact')} width={width} wide={wide} rename={{ label: element.label ?? '', fallback: haName, onLabel }} />
      )}
    </div>
  )
}

/** The colour of a humidity: dry below the band that feels right, wet above it. */
export function humidityColour(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'var(--nd-text-faint)'
  return value < COMFORT[0] ? 'rgb(245, 158, 11)' : value > COMFORT[1] ? 'rgb(56, 189, 248)' : 'rgb(74, 222, 128)'
}

/** A trend as an arrow: up, down, or level within a fifth of a degree. */
export function trendArrow(trend: number | undefined): string {
  if (trend === undefined) return ''
  return trend >= 0.2 ? '↑' : trend <= -0.2 ? '↓' : '→'
}

interface ReadingProps {
  element: HomeReading
  temperatureSaid: SensorState | undefined
  humiditySaid: SensorState | undefined
  arranging: boolean
  wide: boolean
  width: number | null
  onStyle: (style: ReadingStyle) => void
  onRemove: () => void
  /** The page's own name of the reading (its ``name``). */
  onLabel: (label: string) => void
}

function value(said: SensorState | undefined): { value: number | null; missing: boolean; offline: boolean; unit: string; trend?: number } {
  if (!said) return { value: null, missing: false, offline: false, unit: '' }
  if (said.missing) return { value: null, missing: true, offline: false, unit: '' }
  return { value: said.unavailable ? null : (said.current ?? null), missing: false, offline: Boolean(said.unavailable), unit: said.unit ?? '', trend: said.trend }
}

/** A temperature with the humidity of its device, in one of four styles. */
export function ReadingControl({ element, temperatureSaid, humiditySaid, arranging, wide, width, onStyle, onRemove, onLabel }: ReadingProps) {
  const { t } = useTranslation()
  const warm = value(temperatureSaid)
  const wet = value(humiditySaid)
  const fromSensor = (said: SensorState | undefined) => (said && !said.missing ? said.area || said.name : '')
  const haName = fromSensor(temperatureSaid) || fromSensor(humiditySaid) || element.temperature?.name || element.humidity?.name || ''
  const name = element.name || haName
  const named = [element.temperature ? warm : null, element.humidity ? wet : null].filter((one): one is ReturnType<typeof value> => one !== null)
  const gone = named.length > 0 && named.every((one) => one.missing)
  const offline = !gone && named.length > 0 && named.every((one) => one.offline || one.missing)
  const state = `${gone ? 'is-missing' : ''} ${offline ? 'is-offline' : ''}`
  const degrees = element.temperature ? (warm.missing ? t('homePage.sensors.missing') : temperature(warm.value === null ? null : Math.round(warm.value * 10) / 10)) : ''
  const percent = element.humidity ? (wet.missing ? t('homePage.sensors.missing') : reading(wet.value, '%')) : ''
  const battery = <Battery said={temperatureSaid && !temperatureSaid.missing && temperatureSaid.battery != null ? temperatureSaid : humiditySaid} />
  const sized = wide ? { width: '100%' } : width !== null ? { width } : undefined
  let face: ReactNode
  if (element.style === 'pill') {
    face = (
      <div className={`sensor-pill reading ${state}`} style={sized} title={name}>
        <span className="sensor-icon reading">{element.temperature ? THERMO_ICON : DROP_ICON}</span>
        <Marquee text={name} className="flex-1 font-medium" />
        {element.temperature && <span className="num text-[13px] font-semibold" data-temperature>{degrees}</span>}
        {element.humidity && <span className="num text-[12px] text-[rgb(56,189,248)] ml-2" data-humidity>{percent}</span>}
        {battery}
      </div>
    )
  } else if (element.style === 'tile') {
    face = (
      <div className={`sensor-tile reading ${state}`} title={name}>
        <Marquee text={name} className="text-[11.5px] text-muted" />
        <span className="num text-[28px] font-semibold leading-none mt-2 whitespace-nowrap" data-temperature>
          {element.temperature ? degrees : percent}
          {element.temperature && warm.trend !== undefined && Math.abs(warm.trend) >= 0.2 && (
            <sup className="text-[11px] ml-1 align-[8px]" style={{ color: warm.trend > 0 ? 'rgb(251, 146, 60)' : 'rgb(96, 165, 250)' }} data-trend>
              {trendArrow(warm.trend)} {Math.abs(warm.trend).toFixed(1)}
            </sup>
          )}
        </span>
        {element.temperature && element.humidity && (
          <span className="mt-auto flex items-center gap-1.5 text-[12.5px] text-[rgb(56,189,248)] num" data-humidity>
            {DROP_ICON}{percent}
            <span className="flex-1 h-1 rounded-full bg-[color-mix(in_srgb,var(--nd-text)_8%,transparent)] overflow-hidden">
              <i className="block h-full rounded-full bg-[rgb(56,189,248)]" style={{ width: `${Math.max(0, Math.min(100, wet.value ?? 0))}%` }} />
            </span>
          </span>
        )}
        {battery}
      </div>
    )
  } else if (element.style === 'thermometer') {
    const top = 14
    const bottom = 92
    const at = (v: number) => bottom - ((Math.min(30, Math.max(10, v)) - 10) / 20) * (bottom - top)
    const level = warm.value === null ? bottom : at(warm.value)
    face = (
      <div className={`sensor-draw ${state}`} title={name}>
        <svg width="88" height="120" viewBox="0 0 88 120" aria-hidden>
          <rect x="36" y="8" width="16" height="92" rx="8" fill="color-mix(in srgb, var(--nd-text) 6%, transparent)" stroke="color-mix(in srgb, var(--nd-text) 25%, transparent)" />
          <rect x="40" y={level} width="8" height={100 - level} rx="4" fill="rgb(251, 146, 60)" data-level={Math.round(level)} />
          <circle cx="44" cy="104" r="11" fill={warm.value === null ? 'color-mix(in srgb, var(--nd-text) 20%, transparent)' : 'rgb(251, 146, 60)'} />
          {[10, 20, 30].map((mark) => (
            <g key={mark}>
              <line x1="56" x2="62" y1={at(mark)} y2={at(mark)} stroke="color-mix(in srgb, var(--nd-text) 35%, transparent)" />
              <text x="65" y={at(mark) + 3} className="stat-tick">{mark}</text>
            </g>
          ))}
        </svg>
        <Marquee text={name} className="text-[12px]" />
        <div className="num text-[15px] font-semibold" data-temperature>{element.temperature ? degrees : percent}</div>
        {element.temperature && element.humidity && <div className="num text-[11.5px] text-[rgb(56,189,248)]" data-humidity>{percent}</div>}
        {battery}
      </div>
    )
  } else {
    const r = 40
    const round = 2 * Math.PI * r
    const arc = round * 0.75
    const share = (v: number) => (Math.min(100, Math.max(0, v)) / 100) * arc
    const colour = humidityColour(wet.value)
    face = (
      <div className={`sensor-draw sensor-ring ${state}`} title={name}>
        <svg width="120" height="104" viewBox="0 0 120 104" aria-hidden>
          <g transform="rotate(135 60 56)">
            <circle cx="60" cy="56" r={r} fill="none" stroke="color-mix(in srgb, var(--nd-text) 8%, transparent)" strokeWidth="9" strokeDasharray={`${arc} ${round}`} strokeLinecap="round" />
            <circle cx="60" cy="56" r={r} fill="none" stroke="rgba(74, 222, 128, .22)" strokeWidth="9" strokeDasharray={`0 ${share(COMFORT[0])} ${share(COMFORT[1]) - share(COMFORT[0])} ${round}`} />
            {wet.value !== null && <circle cx="60" cy="56" r={r} fill="none" stroke={colour} strokeWidth="5" strokeDasharray={`${share(wet.value)} ${round}`} strokeLinecap="round" data-ring />}
          </g>
          <text x="60" y="58" textAnchor="middle" className="num" style={{ fontSize: 20, fontWeight: 600, fill: 'var(--nd-text)' }} data-humidity>{element.humidity ? percent : degrees}</text>
          {element.humidity && element.temperature && <text x="60" y="74" textAnchor="middle" className="stat-tick" data-temperature>{degrees}</text>}
        </svg>
        <Marquee text={name} className="text-[12px]" />
        {battery}
      </div>
    )
  }
  return (
    <div className={`relative ${wide && element.style === 'pill' ? 'w-full' : 'w-fit'}`} data-reading={element.id} data-style={element.style}>
      {face}
      {arranging && (
        <SensorTools styles={READING_STYLES} current={element.style} group="readingStyles" onStyle={(style) => onStyle(style as ReadingStyle)} onRemove={onRemove}
          removeLabel={t('homePage.sensors.removeReading')} width={width} wide={wide} rename={{ label: element.name, fallback: haName, onLabel }} />
      )}
    </div>
  )
}
