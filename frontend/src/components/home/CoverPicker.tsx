import { useQuery } from '@tanstack/react-query'
import { Plus, Search, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { get } from '../../api/client'
import {
  COVER_STYLES, COVERS_STYLES, MAX_COVERS, MAX_SCENES,
  type ClimateSensor, type CoverInfo, type CoverOffer, type CoverScene, type CoverStyle, type CoversStyle, type HomeCover, type HomeCovers,
} from '../../lib/home'
import { Dialog, Select, Spinner } from '../ui'

/** A new cover element as the picker makes it; the page gives it an id and a place. */
export type FreshCover = Omit<HomeCover, 'id' | 'x' | 'y'> | Omit<HomeCovers, 'id' | 'x' | 'y'>

interface Props {
  open: boolean
  pageId: number
  /** The card whose covers and positions are changed; null to add new elements. */
  card: HomeCovers | null
  onClose: () => void
  onAdd: (elements: FreshCover[]) => void
  onChange: (id: string, patch: { sensors: ClimateSensor[]; title: string; scenes?: CoverScene[] }) => void
}

const LAST_STYLE = 'nexdeck.homeCoverStyle'

/** The positions a card of positions starts with, in the page's language. */
export function defaultScenes(t: (key: string) => string): CoverScene[] {
  return [{ name: t('homePage.covers.morning'), position: 100 }, { name: t('homePage.covers.shade'), position: 30 }, { name: t('homePage.covers.night'), position: 0 }]
}

/**
 * Picking shutters and blinds: by name, room or entity id, with where each
 * stands. A style of one cover makes one element each; a group and a card of
 * positions make one card of them all, the latter with positions of its own.
 */
export function CoverPicker({ open, pageId, card, onClose, onAdd, onChange }: Props) {
  const { t } = useTranslation()
  const offer = useQuery({ queryKey: ['home-covers', pageId], queryFn: () => get<CoverOffer>(`/pages/${pageId}/home/covers`), enabled: open, staleTime: 30_000 })
  const styles = [...COVER_STYLES, ...COVERS_STYLES] as string[]
  const [style, setStyle] = useState('pill')
  const [query, setQuery] = useState('')
  const [chosen, setChosen] = useState<string[]>([])
  const [title, setTitle] = useState('')
  const [scenes, setScenes] = useState<CoverScene[]>([])
  useEffect(() => {
    if (!open) return
    let kept = 'pill'
    try {
      kept = localStorage.getItem(LAST_STYLE) ?? 'pill'
    } catch {
      // Storage may be unavailable; the pill it is.
    }
    setStyle(styles.includes(kept) ? kept : 'pill')
    setQuery('')
    setTitle(card?.title ?? '')
    setChosen(card ? card.sensors.map((one) => one.entity_id) : [])
    setScenes(card?.scenes ?? defaultScenes(t))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, card])
  const covers = useMemo(() => offer.data?.covers ?? [], [offer.data])
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  const shown = covers.filter((one) => words.every((word) => `${one.name} ${one.area} ${one.entity_id} ${one.device_class}`.toLowerCase().includes(word)))
  const together = card !== null || (COVERS_STYLES as readonly string[]).includes(style)
  const withScenes = card ? card.style === 'scenes' : style === 'scenes'
  const full = together && chosen.length >= MAX_COVERS
  const problem = offer.data?.problem ?? null

  const done = () => {
    const picked = chosen.map((id) => covers.find((one) => one.entity_id === id)).filter((one): one is CoverInfo => Boolean(one))
      .map((one) => ({ rid: one.rid, entity_id: one.entity_id, name: one.name }))
    const named = scenes.map((scene) => ({ name: scene.name.trim(), position: Math.max(0, Math.min(100, Math.round(scene.position))) })).filter((scene) => scene.name)
    if (card) {
      // A cover the house no longer offers stays as it was kept: the card says it is gone.
      const gone = card.sensors.filter((one) => chosen.includes(one.entity_id) && !covers.some((offer_) => offer_.entity_id === one.entity_id))
      onChange(card.id, { sensors: [...picked, ...gone].slice(0, MAX_COVERS), title: title.trim(), ...(withScenes ? { scenes: named } : {}) })
      return
    }
    try {
      localStorage.setItem(LAST_STYLE, style)
    } catch {
      // Storage may be unavailable; the next pick starts from the pill again.
    }
    onAdd(together
      ? [{ type: 'covers', style: style as CoversStyle, sensors: picked.slice(0, MAX_COVERS), title: title.trim(), ...(withScenes ? { scenes: named } : {}) }]
      : picked.map((one) => ({ type: 'cover', ...one, style: style as CoverStyle })))
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={card ? t('homePage.stats.pickEditTitle') : t('homePage.covers.pickTitle')}
      footer={
        <>
          {!card && (
            <label className="flex items-center gap-2 mr-auto text-sm text-muted">
              {t('homePage.style')}
              <Select value={style} onChange={setStyle}
                options={styles.map((one) => ({ value: one, label: (COVERS_STYLES as readonly string[]).includes(one) ? t(`homePage.covers.cardStyles.${one}`) : t(`homePage.sensors.coverStyles.${one}`) }))} />
            </label>
          )}
          <button type="button" className="btn btn-accent" disabled={chosen.length === 0} onClick={done}>
            {chosen.length === 0 ? t('homePage.stats.pickNone') : card ? t('homePage.stats.pickSave') : together || chosen.length === 1 ? t('homePage.sensors.addOne') : t('homePage.sensors.addMany', { count: chosen.length })}
          </button>
        </>
      }
    >
      <div className="grid gap-3">
        {together && (
          <label className="grid gap-1 text-sm">
            <span className="text-muted">{t('homePage.stats.cardTitle')}</span>
            <input className="input" value={title} maxLength={80} placeholder={withScenes ? t('homePage.covers.allCovers') : t('homePage.covers.group')} onChange={(event) => setTitle(event.target.value)} />
          </label>
        )}
        {withScenes && (
          <div className="grid gap-1.5" data-scenes>
            <span className="text-sm text-muted">{t('homePage.covers.positions')}</span>
            {scenes.map((scene, index) => (
              <div key={index} className="flex items-center gap-2">
                <input className="input flex-1" value={scene.name} maxLength={40} aria-label={t('homePage.covers.positionName')}
                  onChange={(event) => setScenes((now) => now.map((one, at) => (at === index ? { ...one, name: event.target.value } : one)))} />
                <input className="input w-20 num" type="number" min={0} max={100} step={5} value={scene.position} aria-label={t('homePage.covers.positionValue')}
                  onChange={(event) => setScenes((now) => now.map((one, at) => (at === index ? { ...one, position: Number(event.target.value) } : one)))} />
                <span className="text-muted text-sm">%</span>
                <button type="button" className="btn btn-icon btn-flat" aria-label={t('homePage.covers.removePosition')} disabled={scenes.length === 1}
                  onClick={() => setScenes((now) => now.filter((_, at) => at !== index))}>
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            {scenes.length < MAX_SCENES && (
              <button type="button" className="btn btn-flat justify-self-start text-sm" onClick={() => setScenes((now) => [...now, { name: '', position: 50 }])}>
                <Plus size={14} /> {t('homePage.covers.addPosition')}
              </button>
            )}
          </div>
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
        {problem && <p className="text-sm font-medium" role="status">{t(`homePage.problems.${problem.code}`, { defaultValue: problem.message })}</p>}
        {!offer.isLoading && !problem && shown.length === 0 && <p className="text-sm text-muted py-4 text-center">{t('homePage.covers.pickEmpty')}</p>}
        <ul className="grid gap-0.5 max-h-[45vh] overflow-y-auto -mx-1" aria-label={t('homePage.covers.pickTitle')}>
          {shown.map((one) => {
            const on = chosen.includes(one.entity_id)
            return (
              <li key={one.rid || one.entity_id}>
                <label className={`flex items-center gap-3 px-2 py-2 rounded-lg ${!on && full ? 'opacity-50' : 'cursor-pointer hover:bg-surface-hover'}`}>
                  <input type="checkbox" className="accent-[var(--nd-accent)] w-4 h-4 flex-none" checked={on} disabled={!on && full} aria-label={one.name}
                    onChange={(event) => setChosen((now) => (event.target.checked ? [...now, one.entity_id] : now.filter((id) => id !== one.entity_id)))} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium truncate">{one.name}</span>
                    <span className="block text-[11px] text-muted truncate">{one.area ? `${one.area} · ` : ''}<span className="font-mono">{one.entity_id}</span></span>
                  </span>
                  <span className="num text-[11.5px] text-muted whitespace-nowrap">{one.unavailable || one.position === null ? t('homePage.offline') : `${one.position} %`}</span>
                </label>
              </li>
            )
          })}
        </ul>
      </div>
    </Dialog>
  )
}
