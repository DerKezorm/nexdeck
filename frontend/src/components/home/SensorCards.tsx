import { Activity, ListChecks, Palette, Trash2 } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import {
  CHECKS, CONTACTS_STYLES, reading, roomsOf, since, temperature,
  type Check, type ContactsStyle, type Hint, type HomeContacts, type HomeHints, type HomeReadings, type ReadingRow, type SensorState,
} from '../../lib/home'
import { MAX_LABEL } from './Rename'
import { DROP_ICON, WINDOW_ICON, contactWords, humidityColour, trendArrow } from './SensorControl'

interface CardTools {
  arranging: boolean
  wide: boolean
  width: number | null
  onRemove: () => void
  /** Opens the picker with this card's sensors. */
  onSensors?: () => void
}

/** A card's tools while arranging: a menu of its own (styles, checks), the sensors, the bin, and the grip for its width. */
function Tools({ arranging, wide, width, onRemove, onSensors, menu, menuLabel, menuIcon, removeLabel }: CardTools & { menu?: ReactNode; menuLabel?: string; menuIcon?: ReactNode; removeLabel: string }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  if (!arranging) return null
  return (
    <>
      {width !== null && !wide && <span className="home-grip" data-resize aria-hidden title={t('homePage.dragWidth')} />}
      <span className="absolute -top-3 -right-3 z-10 flex gap-1" data-element-tool>
        {menu && (
          <button type="button" className="btn btn-icon h-6 w-6 rounded-full glass-strong" onClick={() => setOpen((now) => !now)} aria-label={menuLabel} title={menuLabel} aria-haspopup="menu" aria-expanded={open}>
            {menuIcon}
          </button>
        )}
        {onSensors && (
          <button type="button" className="btn btn-icon h-6 w-6 rounded-full glass-strong" onClick={onSensors} aria-label={t('homePage.stats.chooseSensors')} title={t('homePage.stats.chooseSensors')}>
            <Activity size={12} />
          </button>
        )}
        <button type="button" className="btn btn-icon btn-danger h-6 w-6 rounded-full glass-strong" onClick={onRemove} aria-label={removeLabel} title={removeLabel}>
          <Trash2 size={12} />
        </button>
      </span>
      {open && menu && (
        <div className="absolute left-0 top-full mt-2 z-30 glass-strong rounded-xl p-1.5 shadow-2xl grid gap-1 w-64" role="menu" aria-label={menuLabel} data-element-tool onClick={() => setOpen(false)}>
          {menu}
        </div>
      )}
    </>
  )
}

const item = (on: boolean) => `text-left text-[13px] px-2.5 py-1.5 rounded-lg ${on ? 'bg-[var(--nd-accent-soft)] text-accent font-medium' : 'hover:bg-[var(--nd-surface-hover)]'}`

interface ContactsProps extends CardTools {
  element: HomeContacts
  sensors: Record<string, SensorState>
  now: number
  onStyle: (style: ContactsStyle) => void
}

/** What a card of contacts is called unless it was given a name: windows, doors, or both. */
function contactsTitle(element: HomeContacts, sensors: Record<string, SensorState>, t: (key: string) => string): string {
  if (element.title) return element.title
  const kinds = new Set(element.sensors.map((one) => sensors[one.entity_id]).map((said) => (said && !said.missing ? said.device_class : '')).filter(Boolean))
  if (kinds.size === 1 && kinds.has('window')) return t('homePage.sensors.windows')
  if (kinds.size > 0 && [...kinds].every((kind) => kind === 'door' || kind === 'garage_door')) return t('homePage.sensors.doors')
  return t('homePage.sensors.windowsAndDoors')
}

/** F: several doors and windows, only the open ones listed; G: the house, a field per room and a square per contact. */
export function ContactsCard({ element, sensors, now, onStyle, ...tools }: ContactsProps) {
  const { t } = useTranslation()
  const states = element.sensors.map((sensor) => ({ sensor, said: sensors[sensor.entity_id], words: contactWords(sensors[sensor.entity_id], now, t) }))
  const open = states.filter((one) => one.words.open)
  const odd = states.filter((one) => !one.words.open && one.words.quiet)
  const count = open.length === 0
    ? <span className="text-[12px] font-semibold text-ok" data-count>{t('homePage.sensors.allClosed')}</span>
    : <span className="text-[12px] font-semibold sensor-open-text" data-count>{element.style === 'house' ? t('homePage.sensors.someOpen', { count: open.length }) : t('homePage.sensors.openOf', { count: open.length, total: element.sensors.length })}</span>
  const size = tools.wide ? undefined : tools.width !== null ? { width: tools.width } : undefined
  return (
    <div className={`relative ${tools.wide ? 'w-full' : 'w-fit'}`} data-contacts={element.id} data-style={element.style}>
      <div className="stat-card" style={size}>
        <div className="flex items-baseline gap-2">
          <b className="text-[13px] font-semibold truncate">{contactsTitle(element, sensors, t)}</b>
          <span className="ml-auto whitespace-nowrap">{count}</span>
        </div>
        {element.style === 'house' ? (
          <div className="grid grid-cols-4 gap-2 mt-2.5">
            {roomsOf(element, sensors).map((room) => (
              <div key={room.area || '-'} className="rounded-[10px] bg-[color-mix(in_srgb,var(--nd-text)_4%,transparent)] px-2 py-1.5 text-[11px] text-muted min-w-0" data-room={room.area}>
                <span className="block truncate">{room.area || t('homePage.sensors.noRoom')}</span>
                <span className="flex flex-wrap gap-1 mt-1.5">
                  {room.contacts.map((contact) => {
                    const words = contactWords(sensors[contact.entity_id], now, t)
                    const said = sensors[contact.entity_id]
                    return (
                      <i key={contact.entity_id} className={`sensor-square ${words.open ? 'is-open' : ''} ${words.quiet ? (words.missing ? 'is-missing' : 'is-offline') : ''}`}
                        title={`${said && !said.missing && said.name ? said.name : contact.name}: ${words.text}`} data-square={words.open ? 'open' : words.quiet ? 'quiet' : 'closed'} />
                    )
                  })}
                </span>
              </div>
            ))}
          </div>
        ) : (
          (open.length > 0 || odd.length > 0) && (
            <ul className="grid gap-1.5 mt-2.5">
              {[...open, ...odd].map(({ sensor, said, words }) => (
                <li key={sensor.entity_id} className={`flex items-center gap-2 text-[12.5px] ${words.quiet ? 'text-muted' : ''}`} data-listed={sensor.entity_id}>
                  <i className={`w-[7px] h-[7px] rounded-full flex-none ${words.open ? 'sensor-dot' : 'bg-[color-mix(in_srgb,var(--nd-text)_25%,transparent)]'}`} />
                  <span className="truncate">{said && !said.missing && said.name ? said.name : sensor.name}</span>
                  <small className={`ml-auto num text-[11px] whitespace-nowrap ${words.missing ? 'text-bad' : 'text-muted'}`}>
                    {words.open && said && !said.missing ? since(said.since, now) : words.text}
                  </small>
                </li>
              ))}
            </ul>
          )
        )}
      </div>
      <Tools {...tools} removeLabel={t('homePage.sensors.removeCard')} menuLabel={t('homePage.chooseStyle')} menuIcon={<Palette size={12} />}
        menu={CONTACTS_STYLES.map((style) => (
          <button key={style} type="button" role="menuitemradio" aria-checked={element.style === style} className={item(element.style === style)} onClick={() => onStyle(style)}>
            {t(`homePage.sensors.contactsStyles.${style}`)}
          </button>
        ))} />
    </div>
  )
}

interface ReadingsProps extends CardTools {
  element: HomeReadings
  sensors: Record<string, SensorState>
  /** The rows with names of the page's own, typed while arranging. */
  onRows: (rows: ReadingRow[]) => void
}

/** L: rooms in rows, each with its temperature, the trend of the last hour, and its humidity. */
export function ReadingsCard({ element, sensors, onRows, ...tools }: ReadingsProps) {
  const { t } = useTranslation()
  const size = tools.wide ? undefined : tools.width !== null ? { width: tools.width } : undefined
  const roomOf = (row: ReadingRow) => {
    const said = [row.temperature, row.humidity].map((one) => (one ? sensors[one.entity_id] : undefined)).find((one) => one && !one.missing)
    return said && !said.missing ? said.area ?? '' : ''
  }
  const cell = (ref: { entity_id: string } | null, shown: (said: SensorState & { missing: false }) => ReactNode) => {
    if (!ref) return ''
    const said = sensors[ref.entity_id]
    if (!said) return '…'
    if (said.missing) return <span className="text-bad">{t('homePage.sensors.missing')}</span>
    if (said.unavailable) return <span className="text-muted">{t('homePage.offline')}</span>
    return shown(said)
  }
  return (
    <div className={`relative ${tools.wide ? 'w-full' : 'w-fit'}`} data-readings={element.id}>
      <div className="stat-card" style={size}>
        <b className="text-[13px] font-semibold">{element.title || t('homePage.sensors.rooms')}</b>
        <table className="w-full mt-2 text-[12.5px] border-collapse">
          <tbody>
            {element.rows.map((row, index) => (
              <tr key={index} className="border-t border-[var(--nd-border)]" data-row={index}>
                <td className="py-1.5 pr-2 truncate max-w-0 w-full">
                  {tools.arranging ? (
                    // While arranging each row's name can be the page's own; empty is the sensor's room.
                    <input className="input h-7 text-[12.5px] w-full" defaultValue={row.name} maxLength={MAX_LABEL} aria-label={t('homePage.sensors.rowName')}
                      placeholder={roomOf(row) || row.temperature?.name || row.humidity?.name} data-element-tool
                      onKeyDown={(event) => {
                        event.stopPropagation()
                        if (event.key === 'Enter') event.currentTarget.blur()
                      }}
                      onBlur={(event) => {
                        const name = event.currentTarget.value.trim()
                        if (name !== row.name) onRows(element.rows.map((one, at) => (at === index ? { ...one, name } : one)))
                      }} />
                  ) : (row.name || roomOf(row) || row.temperature?.name || row.humidity?.name)}
                </td>
                <td className="py-1.5 text-right num whitespace-nowrap" data-temperature>
                  {cell(row.temperature, (said) => (
                    <>
                      {temperature(said.current === null || said.current === undefined ? null : Math.round(said.current * 10) / 10)}
                      {said.trend !== undefined && <span className="text-[11px] text-faint ml-1" data-trend>{trendArrow(said.trend)}</span>}
                    </>
                  ))}
                </td>
                <td className="py-1.5 pl-4 text-right num whitespace-nowrap" data-humidity>
                  {cell(row.humidity, (said) => <span style={{ color: humidityColour(said.current) }}>{reading(said.current, '%')}</span>)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Tools {...tools} removeLabel={t('homePage.sensors.removeCard')} />
    </div>
  )
}

interface HintsProps extends CardTools {
  element: HomeHints
  hints: Hint[]
  now: number
  onChecks: (checks: Check[]) => void
}

/** M: a window open while its room heats, a room that wants airing; quiet when there is nothing to say. */
export function HintsCard({ element, hints, now, onChecks, ...tools }: HintsProps) {
  const { t } = useTranslation()
  const size = tools.wide ? undefined : tools.width !== null ? { width: tools.width } : undefined
  return (
    <div className={`relative ${tools.wide ? 'w-full' : 'w-fit'}`} data-hints={element.id}>
      <div className="stat-card grid gap-2" style={size}>
        <b className="text-[13px] font-semibold">{element.title || t('homePage.sensors.hints')}</b>
        {hints.map((hint) => (
          <div key={hint.key} className="flex gap-2.5 items-start text-[12.5px]" data-hint={hint.kind}>
            <span className={`grid place-items-center w-[26px] h-[26px] rounded-full flex-none ${hint.kind === 'heating' ? 'sensor-hint-open' : 'sensor-hint-wet'}`}>
              {hint.kind === 'heating' ? WINDOW_ICON : DROP_ICON}
            </span>
            <div className="min-w-0">
              {hint.kind === 'heating' ? t('homePage.sensors.openWhileHeating', { name: hint.name }) : t('homePage.sensors.airing', { name: hint.name })}
              <small className="block text-muted text-[11.5px]">
                {hint.kind === 'heating'
                  ? [hint.since ? t('homePage.sensors.forTime', { time: since(hint.since, now) }) : '', hint.target !== null && hint.target !== undefined ? t('homePage.sensors.targetIs', { value: temperature(hint.target) }) : ''].filter(Boolean).join(', ')
                  : t('homePage.sensors.humidityIs', { value: reading(hint.value, '%') })}
              </small>
            </div>
          </div>
        ))}
        {hints.length === 0 && (
          <div className="flex gap-2.5 items-center text-[12.5px] text-muted" data-quiet>
            <span className="grid place-items-center w-[26px] h-[26px] rounded-full flex-none bg-[color-mix(in_srgb,rgb(74,222,128)_14%,transparent)] text-ok">✓</span>
            {element.checks.length === 0 ? t('homePage.sensors.nothingChecked') : t('homePage.sensors.allQuiet')}
          </div>
        )}
      </div>
      <Tools {...tools} removeLabel={t('homePage.sensors.removeCard')} menuLabel={t('homePage.sensors.chooseChecks')} menuIcon={<ListChecks size={12} />}
        menu={CHECKS.map((check) => {
          const on = element.checks.includes(check)
          return (
            <button key={check} type="button" role="menuitemcheckbox" aria-checked={on} className={item(on)}
              onClick={() => onChecks(on ? element.checks.filter((one) => one !== check) : CHECKS.filter((one) => one === check || element.checks.includes(one)))}>
              {t(`homePage.sensors.checks.${check}`)}
            </button>
          )
        })} />
    </div>
  )
}
