import { useQuery } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { get } from '../../api/client'
import {
  CONTACT_STYLES, CONTACTS_STYLES, pairReadings, READING_STYLES, reading, temperature,
  type ClimateSensor, type ContactInfo, type ContactStyle, type ReadingStyle, type ContactOffer, type HomeContacts, type HomeReadings, type HomeSensorElement, type ReadingInfo, type ReadingOffer,
  type ReadingPair, type ReadingRow,
} from '../../lib/home'
import { Dialog, Select, Spinner } from '../ui'

/** A new element as the picker makes it; the page gives it an id and a place. */
export type FreshSensor = { [K in HomeSensorElement['type']]: Omit<Extract<HomeSensorElement, { type: K }>, 'id' | 'x' | 'y'> }[HomeSensorElement['type']]

/** How many contacts one card takes (``MAX_CONTACTS`` on the server), and rooms one list. */
const MAX_CONTACTS = 60
const MAX_ROWS = 12

interface Props {
  /** What is picked: doors and windows, or temperatures and humidity; null closed. */
  mode: 'contacts' | 'readings' | null
  pageId: number
  /** The card whose sensors are changed; null to add new elements. */
  card: HomeContacts | HomeReadings | null
  onClose: () => void
  onAdd: (elements: FreshSensor[]) => void
  onChange: (id: string, patch: { sensors?: ClimateSensor[]; rows?: ReadingRow[]; title: string }) => void
}

const ref = (one: ContactInfo | ReadingInfo): ClimateSensor => ({ rid: one.rid, entity_id: one.entity_id, name: one.name })

function remembered(key: string, styles: readonly string[], fallback: string): string {
  try {
    const kept = localStorage.getItem(key)
    return kept && styles.includes(kept) ? kept : fallback
  } catch {
    return fallback
  }
}

/**
 * Picking doors and windows, or temperatures with the humidity of their
 * device: by name, room or entity id. A style of one sensor makes one element
 * each; the list, the house and the rooms make one card of them all.
 */
export function SensorPicker({ mode, pageId, card, onClose, onAdd, onChange }: Props) {
  const { t } = useTranslation()
  const contacts = useQuery({ queryKey: ['home-contacts', pageId], queryFn: () => get<ContactOffer>(`/pages/${pageId}/home/contacts`), enabled: mode === 'contacts', staleTime: 30_000 })
  const readings = useQuery({ queryKey: ['home-readings', pageId], queryFn: () => get<ReadingOffer>(`/pages/${pageId}/home/readings`), enabled: mode === 'readings', staleTime: 30_000 })
  const contactStyles = [...CONTACT_STYLES, ...CONTACTS_STYLES] as string[]
  const readingStyles = [...READING_STYLES, 'rooms'] as string[]
  const styles = mode === 'contacts' ? contactStyles : readingStyles
  const storeKey = mode === 'contacts' ? 'nexdeck.homeContactStyle' : 'nexdeck.homeReadingStyle'
  const [style, setStyle] = useState('pill')
  const [query, setQuery] = useState('')
  const [chosen, setChosen] = useState<string[]>([])
  const [title, setTitle] = useState('')
  const pairs = useMemo(() => pairReadings(readings.data?.readings ?? []), [readings.data])
  const offered = useMemo(() => contacts.data?.contacts ?? [], [contacts.data])
  useEffect(() => {
    if (!mode) return
    setStyle(remembered(mode === 'contacts' ? 'nexdeck.homeContactStyle' : 'nexdeck.homeReadingStyle', mode === 'contacts' ? contactStyles : readingStyles, 'pill'))
    setQuery('')
    setTitle(card?.title ?? '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, card])
  useEffect(() => {
    if (!mode) return
    if (card?.type === 'contacts') setChosen(card.sensors.map((one) => one.entity_id))
    else if (card?.type === 'readings') {
      const placed = new Set(card.rows.flatMap((row) => [row.temperature?.entity_id, row.humidity?.entity_id]).filter(Boolean))
      setChosen(pairs.filter((pair) => placed.has(pair.temperature?.entity_id) || placed.has(pair.humidity?.entity_id)).map((pair) => pair.key))
    } else setChosen([])
  }, [mode, card, pairs])

  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  const matches = (text: string) => words.every((word) => text.toLowerCase().includes(word))
  const shownContacts = offered.filter((one) => matches(`${one.name} ${one.area} ${one.entity_id} ${one.device_class}`))
  const shownPairs = pairs.filter((pair) => matches(`${pair.name} ${pair.area} ${pair.temperature?.entity_id ?? ''} ${pair.humidity?.entity_id ?? ''}`))
  const together = card !== null || style === 'list' || style === 'house' || style === 'rooms'
  const limit = !together ? Infinity : mode === 'contacts' ? MAX_CONTACTS : MAX_ROWS
  const full = chosen.length >= limit
  const problem = (mode === 'contacts' ? contacts.data?.problem : readings.data?.problem) ?? null
  const loading = mode === 'contacts' ? contacts.isLoading : readings.isLoading

  const close = () => {
    setChosen([])
    onClose()
  }
  const done = () => {
    const name = title.trim()
    if (mode === 'contacts') {
      const picked = chosen.map((id) => offered.find((one) => one.entity_id === id)).filter((one): one is ContactInfo => Boolean(one)).map(ref)
      if (card?.type === 'contacts') {
        // A contact the house no longer offers stays as it was kept: the card says it is gone.
        const gone = card.sensors.filter((one) => chosen.includes(one.entity_id) && !offered.some((offer) => offer.entity_id === one.entity_id))
        onChange(card.id, { sensors: [...picked, ...gone].slice(0, MAX_CONTACTS), title: name })
        return
      }
      onAdd(style === 'list' || style === 'house'
        ? [{ type: 'contacts', style, sensors: picked.slice(0, MAX_CONTACTS), title: name }]
        : picked.map((one) => ({ type: 'contact', rid: one.rid, entity_id: one.entity_id, name: one.name, style: style as ContactStyle })))
    } else {
      const picked = chosen.map((key) => pairs.find((pair) => pair.key === key)).filter((one): one is ReadingPair => Boolean(one))
      const rowOf = (pair: ReadingPair): ReadingRow => ({ name: pair.area || pair.name, temperature: pair.temperature ? ref(pair.temperature) : null, humidity: pair.humidity ? ref(pair.humidity) : null })
      if (card?.type === 'readings') {
        const offeredIds = new Set(pairs.flatMap((pair) => [pair.temperature?.entity_id, pair.humidity?.entity_id]))
        const gone = card.rows.filter((row) => ![row.temperature, row.humidity].some((one) => one && offeredIds.has(one.entity_id)))
        onChange(card.id, { rows: [...picked.map(rowOf), ...gone].slice(0, MAX_ROWS), title: name })
        return
      }
      onAdd(style === 'rooms'
        ? [{ type: 'readings', rows: picked.slice(0, MAX_ROWS).map(rowOf), title: name }]
        : picked.map((pair) => ({ type: 'reading', style: style as ReadingStyle, name: '', temperature: pair.temperature ? ref(pair.temperature) : null,
          humidity: pair.humidity ? ref(pair.humidity) : null })))
    }
    try {
      localStorage.setItem(storeKey, style)
    } catch {
      // Storage may be unavailable; the next pick starts from the pill again.
    }
    setChosen([])
  }
  const toggle = (key: string, on: boolean) => setChosen((now) => (on ? [...now, key] : now.filter((one) => one !== key)))
  const group = mode === 'contacts' ? (CONTACTS_STYLES as readonly string[]).includes(style) ? 'contactsStyles' : 'contactStyles' : 'readingStyles'

  return (
    <Dialog
      open={mode !== null}
      onClose={close}
      title={card ? t('homePage.stats.pickEditTitle') : mode === 'contacts' ? t('homePage.sensors.pickContacts') : t('homePage.sensors.pickReadings')}
      footer={
        <>
          {!card && (
            <label className="flex items-center gap-2 mr-auto text-sm text-muted">
              {t('homePage.style')}
              <Select value={style} onChange={setStyle}
                options={styles.map((one) => ({ value: one, label: one === 'rooms' ? t('homePage.sensors.readingStyles.rooms') : t(`homePage.sensors.${mode === 'contacts' && (CONTACTS_STYLES as readonly string[]).includes(one) ? 'contactsStyles' : mode === 'contacts' ? 'contactStyles' : 'readingStyles'}.${one}`) }))} />
            </label>
          )}
          <button type="button" className="btn btn-accent" disabled={chosen.length === 0} onClick={done} data-group={group}>
            {chosen.length === 0 ? t('homePage.stats.pickNone') : card ? t('homePage.stats.pickSave') : together || chosen.length === 1 ? t('homePage.sensors.addOne') : t('homePage.sensors.addMany', { count: chosen.length })}
          </button>
        </>
      }
    >
      <div className="grid gap-3">
        {together && (
          <label className="grid gap-1 text-sm">
            <span className="text-muted">{t('homePage.stats.cardTitle')}</span>
            <input className="input" value={title} maxLength={80} placeholder={mode === 'contacts' ? t('homePage.sensors.contactsTitleHint') : t('homePage.sensors.rooms')} onChange={(event) => setTitle(event.target.value)} />
          </label>
        )}
        <label className="input flex items-center gap-2">
          <Search size={14} className="text-muted flex-none" />
          <input className="flex-1 min-w-0 bg-transparent outline-none" autoFocus value={query} placeholder={t('homePage.pickSearch')} aria-label={t('homePage.pickSearch')} onChange={(event) => setQuery(event.target.value)} />
        </label>
        {loading && (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        )}
        {problem && (
          <div className="rounded-xl border border-[color-mix(in_srgb,var(--nd-warn)_40%,transparent)] px-3 py-2.5" role="status">
            <p className="text-sm font-medium">{t(`homePage.problems.${problem.code}`, { defaultValue: problem.message })}</p>
          </div>
        )}
        {together && limit !== Infinity && <p className="text-[11.5px] text-faint -mt-1">{t('homePage.stats.upTo', { count: limit === MAX_ROWS ? MAX_ROWS : MAX_CONTACTS })}</p>}
        {!loading && !problem && (mode === 'contacts' ? shownContacts : shownPairs).length === 0 && <p className="text-sm text-muted py-4 text-center">{t('homePage.sensors.pickEmpty')}</p>}
        <ul className="grid gap-0.5 max-h-[50vh] overflow-y-auto -mx-1" aria-label={t('homePage.pickSearch')}>
          {mode === 'contacts' && shownContacts.map((one) => {
            const on = chosen.includes(one.entity_id)
            return (
              <li key={one.rid || one.entity_id}>
                <label className={`flex items-center gap-3 px-2 py-2 rounded-lg ${!on && full ? 'opacity-50' : 'cursor-pointer hover:bg-surface-hover'}`}>
                  <input type="checkbox" className="accent-[var(--nd-accent)] w-4 h-4 flex-none" checked={on} disabled={!on && full} aria-label={one.name} onChange={(event) => toggle(one.entity_id, event.target.checked)} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium truncate">{one.name}</span>
                    <span className="block text-[11px] text-muted truncate">{one.area ? `${one.area} · ` : ''}<span className="font-mono">{one.entity_id}</span></span>
                  </span>
                  <span className={`text-[11.5px] whitespace-nowrap ${one.open ? 'sensor-open-text font-semibold' : 'text-muted'}`}>
                    {one.unavailable || one.open === null ? t('homePage.offline') : one.open ? t('homePage.sensors.openWord') : t('homePage.sensors.closedWord')}
                  </span>
                </label>
              </li>
            )
          })}
          {mode === 'readings' && shownPairs.map((pair) => {
            const on = chosen.includes(pair.key)
            return (
              <li key={pair.key}>
                <label className={`flex items-center gap-3 px-2 py-2 rounded-lg ${!on && full ? 'opacity-50' : 'cursor-pointer hover:bg-surface-hover'}`}>
                  <input type="checkbox" className="accent-[var(--nd-accent)] w-4 h-4 flex-none" checked={on} disabled={!on && full} aria-label={pair.name} onChange={(event) => toggle(pair.key, event.target.checked)} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium truncate">{pair.name}</span>
                    <span className="block text-[11px] text-muted truncate">{pair.area ? `${pair.area} · ` : ''}<span className="font-mono">{pair.temperature?.entity_id ?? pair.humidity?.entity_id}</span></span>
                  </span>
                  <span className="num text-[11.5px] whitespace-nowrap">
                    {pair.temperature && temperature(pair.temperature.current)}
                    {pair.humidity && <span className="text-[rgb(56,189,248)] ml-2">{reading(pair.humidity.current, '%')}</span>}
                  </span>
                </label>
              </li>
            )
          })}
        </ul>
      </div>
    </Dialog>
  )
}
