import { useQuery } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { get } from '../../api/client'
import { MAX_SENSORS, ONE_SENSOR, reading, STAT_STYLES, type ClimateSensor, type HomeStat, type StatOffer, type StatSensorInfo, type StatStyle } from '../../lib/home'
import { Dialog, Select, Spinner } from '../ui'

interface Props {
  open: boolean
  pageId: number
  /** The card whose sensors are changed; null to add new cards. */
  card: HomeStat | null
  onClose: () => void
  /** New cards: one per sensor for a style that shows one, a single card for the rooms. */
  onAdd: (cards: { style: StatStyle; sensors: ClimateSensor[]; title: string }[]) => void
  onChange: (id: string, patch: { sensors: ClimateSensor[]; title: string }) => void
}

/** The style a browser last added cards in; a convenience, kept in the browser. */
const LAST_STYLE = 'nexdeck.homeStatStyle'

function lastStyle(): StatStyle {
  try {
    const kept = localStorage.getItem(LAST_STYLE)
    return (STAT_STYLES as readonly string[]).includes(kept ?? '') ? (kept as StatStyle) : 'line'
  } catch {
    return 'line'
  }
}

const kept = (one: StatSensorInfo): ClimateSensor => ({ rid: one.rid, entity_id: one.entity_id, name: one.name })

/**
 * Picking the sensors of a statistics card: by name, room or entity id, with
 * what each reads now and whether Home Assistant keeps statistics of it. A
 * house has hundreds; what is offered is the server's business
 * (``hass_stats.pick_sensors``).
 */
export function StatPicker({ open, pageId, card, onClose, onAdd, onChange }: Props) {
  const { t } = useTranslation()
  const offer = useQuery({ queryKey: ['home-sensors', pageId], queryFn: () => get<StatOffer>(`/pages/${pageId}/home/sensors`), enabled: open, staleTime: 30_000 })
  const [query, setQuery] = useState('')
  const [chosen, setChosen] = useState<string[]>([])
  const [style, setStyle] = useState<StatStyle>(lastStyle)
  const [title, setTitle] = useState('')
  useEffect(() => {
    if (!open) return
    setChosen(card ? card.sensors.map((sensor) => sensor.entity_id) : [])
    setTitle(card?.title ?? '')
    setQuery('')
  }, [open, card])
  const sensors = useMemo(() => offer.data?.sensors ?? [], [offer.data])
  const shown = useMemo(() => {
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
    return sensors.filter((one) => words.every((word) => `${one.name} ${one.area} ${one.entity_id} ${one.device_class}`.toLowerCase().includes(word)))
  }, [sensors, query])
  const problem = offer.data?.problem ?? null
  const cardStyle = card?.style ?? style
  // A card of one sensor takes one when it is changed; new cards of such a style are one per sensor.
  const single = card !== null && ONE_SENSOR.has(cardStyle)
  const limit = card !== null && !single ? MAX_SENSORS : style === 'rooms' ? MAX_SENSORS : Infinity
  const full = chosen.length >= limit

  const toggle = (one: StatSensorInfo, on: boolean) =>
    setChosen((now) => (single ? (on ? [one.entity_id] : []) : on ? [...now, one.entity_id] : now.filter((id) => id !== one.entity_id)))
  const close = () => {
    setChosen([])
    onClose()
  }
  const done = () => {
    const picked = chosen.map((id) => sensors.find((one) => one.entity_id === id)).filter((one): one is StatSensorInfo => Boolean(one)).map(kept)
    // A sensor of the card the house no longer offers stays, as it was kept: the card says it is gone.
    const gone = card ? card.sensors.filter((sensor) => chosen.includes(sensor.entity_id) && !sensors.some((one) => one.entity_id === sensor.entity_id)) : []
    setChosen([])
    if (card) {
      onChange(card.id, { sensors: [...picked, ...gone].slice(0, MAX_SENSORS), title: title.trim() })
      return
    }
    try {
      localStorage.setItem(LAST_STYLE, style)
    } catch {
      // Storage may be unavailable; the next pick starts from the line again.
    }
    onAdd(style === 'rooms' ? [{ style, sensors: picked.slice(0, MAX_SENSORS), title: title.trim() }] : picked.map((sensor) => ({ style, sensors: [sensor], title: picked.length === 1 ? title.trim() : '' })))
  }

  return (
    <Dialog
      open={open}
      onClose={close}
      title={card ? t('homePage.stats.pickEditTitle') : t('homePage.stats.pickTitle')}
      footer={
        <>
          {!card && (
            <label className="flex items-center gap-2 mr-auto text-sm text-muted">
              {t('homePage.style')}
              <Select value={style} onChange={(value) => setStyle(value as StatStyle)} options={STAT_STYLES.map((one) => ({ value: one, label: t(`homePage.stats.styles.${one}`) }))} />
            </label>
          )}
          <button type="button" className="btn btn-accent" disabled={chosen.length === 0} onClick={done}>
            {chosen.length === 0 ? t('homePage.stats.pickNone') : card ? t('homePage.stats.pickSave') : style === 'rooms' || chosen.length === 1 ? t('homePage.stats.pickOne') : t('homePage.stats.pickMany', { count: chosen.length })}
          </button>
        </>
      }
    >
      <div className="grid gap-3">
        {(card ? !single : style === 'rooms' || chosen.length <= 1) && (
          <label className="grid gap-1 text-sm">
            <span className="text-muted">{t('homePage.stats.cardTitle')}</span>
            <input className="input" value={title} maxLength={80} placeholder={t('homePage.stats.cardTitleHint')} onChange={(event) => setTitle(event.target.value)} />
          </label>
        )}
        <label className="input flex items-center gap-2">
          <Search size={14} className="text-muted flex-none" />
          <input className="flex-1 min-w-0 bg-transparent outline-none" autoFocus value={query} placeholder={t('homePage.pickSearch')} aria-label={t('homePage.pickSearch')} onChange={(event) => setQuery(event.target.value)} />
        </label>
        {offer.isLoading && (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        )}
        {problem && (
          <div className="rounded-xl border border-[color-mix(in_srgb,var(--nd-warn)_40%,transparent)] px-3 py-2.5" role="status">
            <p className="text-sm font-medium">{t(`homePage.problems.${problem.code}`, { defaultValue: problem.message })}</p>
            {problem.hint && <p className="text-xs text-muted mt-0.5">{t(`homePage.hints.${problem.code}`, { defaultValue: problem.hint })}</p>}
          </div>
        )}
        {limit !== Infinity && !single && <p className="text-[11.5px] text-faint -mt-1">{t('homePage.stats.upTo', { count: MAX_SENSORS })}</p>}
        {!offer.isLoading && !problem && shown.length === 0 && <p className="text-sm text-muted py-4 text-center">{t('homePage.stats.pickEmpty')}</p>}
        {shown.length > 0 && (
          <ul className="grid gap-0.5 max-h-[50vh] overflow-y-auto -mx-1" aria-label={t('homePage.stats.pickTitle')}>
            {shown.map((one) => {
              const on = chosen.includes(one.entity_id)
              return (
                <li key={one.rid || one.entity_id}>
                  <label className={`flex items-center gap-3 px-2 py-2 rounded-lg ${!on && full && !single ? 'opacity-50' : 'cursor-pointer hover:bg-surface-hover'}`}>
                    <input type={single ? 'radio' : 'checkbox'} name="stat-sensor" className="accent-[var(--nd-accent)] w-4 h-4 flex-none" checked={on} disabled={!on && full && !single} aria-label={one.name}
                      onChange={(event) => toggle(one, event.target.checked)} />
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium truncate">{one.name}</span>
                      <span className="block text-[11px] text-muted truncate">
                        {one.area ? `${one.area} · ` : ''}
                        <span className="font-mono">{one.entity_id}</span>
                      </span>
                    </span>
                    <span className="grid justify-items-end flex-none">
                      <span className="num text-[11.5px] whitespace-nowrap">{one.unavailable ? t('homePage.offline') : reading(one.current, one.unit)}</span>
                      <span className="text-[10.5px] text-faint whitespace-nowrap">{one.source === 'history' ? t('homePage.stats.onlyHistory') : one.kind === 'sum' ? t('homePage.stats.counter') : t('homePage.stats.statistics')}</span>
                    </span>
                  </label>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </Dialog>
  )
}
