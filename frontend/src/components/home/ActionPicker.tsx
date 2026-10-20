import { useQuery } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { get } from '../../api/client'
import {
  MAX_ACTIONS, SCENE_STYLES, SCENES_STYLES, SWITCH_STYLES,
  type ActionInfo, type ActionOffer, type ClimateSensor, type HomeScene, type HomeScenes, type HomeSwitch, type HomeSwitches, type SceneStyle, type ScenesStyle, type SwitchStyle,
} from '../../lib/home'
import { Dialog, Select, Spinner } from '../ui'
import { watts } from './SwitchControl'

/** A new element as the picker makes it; the page gives it an id and a place. */
export type FreshAction = Omit<HomeScene, 'id' | 'x' | 'y'> | Omit<HomeScenes, 'id' | 'x' | 'y'> | Omit<HomeSwitch, 'id' | 'x' | 'y'> | Omit<HomeSwitches, 'id' | 'x' | 'y'>

interface Props {
  /** What is picked: scenes and scripts, or switches and helpers; null closed. */
  mode: 'scenes' | 'switches' | null
  pageId: number
  /** The card whose scenes or switches change; null to add new elements. */
  card: HomeScenes | HomeSwitches | null
  onClose: () => void
  onAdd: (elements: FreshAction[]) => void
  onChange: (id: string, patch: { sensors: ClimateSensor[]; title: string }) => void
}

const ref = (one: ActionInfo): ClimateSensor => ({ rid: one.rid, entity_id: one.entity_id, name: one.name })

/**
 * Picking scenes and scripts, or switches and helpers, by name, room or
 * entity id. A style of one makes one element each; the bar of a room makes
 * one bar for each room the chosen scenes are in, the grid and the card of
 * switches one card of them all.
 */
export function ActionPicker({ mode, pageId, card, onClose, onAdd, onChange }: Props) {
  const { t } = useTranslation()
  const offer = useQuery({ queryKey: ['home-actions', pageId, mode], queryFn: () => get<ActionOffer>(`/pages/${pageId}/home/${mode}`), enabled: mode !== null, staleTime: 30_000 })
  const styles = mode === 'scenes' ? [...SCENE_STYLES, ...SCENES_STYLES] as string[] : [...SWITCH_STYLES, 'group']
  const together = (style: string) => (SCENES_STYLES as readonly string[]).includes(style) || style === 'group'
  const storeKey = mode === 'scenes' ? 'nexdeck.homeSceneStyle' : 'nexdeck.homeSwitchStyle'
  const [style, setStyle] = useState('pill')
  const [query, setQuery] = useState('')
  const [chosen, setChosen] = useState<string[]>([])
  const [title, setTitle] = useState('')
  const [confirm, setConfirm] = useState(false)
  useEffect(() => {
    if (!mode) return
    let kept = 'pill'
    try {
      kept = localStorage.getItem(storeKey) ?? 'pill'
    } catch {
      // Storage may be unavailable; the pill it is.
    }
    setStyle(styles.includes(kept) ? kept : 'pill')
    setQuery('')
    setTitle(card?.title ?? '')
    setChosen(card ? card.sensors.map((one) => one.entity_id) : [])
    setConfirm(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, card])
  const things = useMemo(() => (mode === 'scenes' ? offer.data?.scenes : offer.data?.switches) ?? [], [offer.data, mode])
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  const shown = things.filter((one) => words.every((word) => `${one.name} ${one.area} ${one.entity_id}`.toLowerCase().includes(word)))
  const many = card !== null || together(style)
  const full = many && chosen.length >= MAX_ACTIONS
  const problem = offer.data?.problem ?? null
  const label = (one: string) => (one === 'group' ? t('homePage.switches.cardStyles.group')
    : mode === 'scenes' && (SCENES_STYLES as readonly string[]).includes(one) ? t(`homePage.scenes.cardStyles.${one}`)
    : t(`homePage.sensors.${mode === 'scenes' ? 'sceneStyles' : 'switchStyles'}.${one}`))

  const done = () => {
    const picked = chosen.map((id) => things.find((one) => one.entity_id === id)).filter((one): one is ActionInfo => Boolean(one))
    const name = title.trim()
    if (card) {
      // One the house no longer offers stays as it was kept: the card says it is gone.
      const gone = card.sensors.filter((one) => chosen.includes(one.entity_id) && !things.some((thing) => thing.entity_id === one.entity_id))
      onChange(card.id, { sensors: [...picked.map(ref), ...gone].slice(0, MAX_ACTIONS), title: name })
      return
    }
    try {
      localStorage.setItem(storeKey, style)
    } catch {
      // Storage may be unavailable; the next pick starts from the pill again.
    }
    if (mode === 'scenes' && style === 'bar') {
      // A bar for each room, in the order the rooms first come; the name only when there is one bar.
      const rooms = new Map<string, ActionInfo[]>()
      for (const one of picked) rooms.set(one.area, [...(rooms.get(one.area) ?? []), one])
      onAdd([...rooms.values()].map((scenes) => ({ type: 'scenes', style: 'bar' as ScenesStyle, sensors: scenes.slice(0, MAX_ACTIONS).map(ref), title: rooms.size === 1 ? name : '' })))
    } else if (mode === 'scenes' && style === 'grid') {
      onAdd([{ type: 'scenes', style: 'grid', sensors: picked.slice(0, MAX_ACTIONS).map(ref), title: name }])
    } else if (mode === 'scenes') {
      onAdd(picked.map((one) => ({ type: 'scene', ...ref(one), style: style as SceneStyle })))
    } else if (style === 'group') {
      onAdd([{ type: 'switches', sensors: picked.slice(0, MAX_ACTIONS).map(ref), title: name, ...(confirm ? { confirm } : {}) }])
    } else {
      onAdd(picked.map((one) => ({ type: 'switch', ...ref(one), style: style as SwitchStyle, ...(confirm ? { confirm } : {}) })))
    }
  }

  return (
    <Dialog
      open={mode !== null}
      onClose={onClose}
      title={card ? t('homePage.stats.pickEditTitle') : mode === 'scenes' ? t('homePage.scenes.pickTitle') : t('homePage.switches.pickTitle')}
      footer={
        <>
          {!card && (
            <label className="flex items-center gap-2 mr-auto text-sm text-muted">
              {t('homePage.style')}
              <Select value={style} onChange={setStyle} options={styles.map((one) => ({ value: one, label: label(one) }))} />
            </label>
          )}
          <button type="button" className="btn btn-accent" disabled={chosen.length === 0} onClick={done}>
            {chosen.length === 0 ? t('homePage.stats.pickNone') : card ? t('homePage.stats.pickSave') : many || chosen.length === 1 ? t('homePage.sensors.addOne') : t('homePage.sensors.addMany', { count: chosen.length })}
          </button>
        </>
      }
    >
      <div className="grid gap-3">
        {many && (
          <label className="grid gap-1 text-sm">
            <span className="text-muted">{t('homePage.stats.cardTitle')}</span>
            <input className="input" value={title} maxLength={80} placeholder={mode === 'scenes' ? t('homePage.scenes.titleHint') : t('homePage.switches.group')} onChange={(event) => setTitle(event.target.value)} />
          </label>
        )}
        {mode === 'switches' && !card && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="accent-[var(--nd-accent)] w-4 h-4" checked={confirm} onChange={(event) => setConfirm(event.target.checked)} />
            {t('homePage.switches.askFirstLong')}
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
        {problem && <p className="text-sm font-medium" role="status">{t(`homePage.problems.${problem.code}`, { defaultValue: problem.message })}</p>}
        {!offer.isLoading && !problem && shown.length === 0 && <p className="text-sm text-muted py-4 text-center">{t('homePage.sensors.pickEmpty')}</p>}
        <ul className="grid gap-0.5 max-h-[45vh] overflow-y-auto -mx-1" aria-label={t('homePage.pickSearch')}>
          {shown.map((one) => {
            const on = chosen.includes(one.entity_id)
            const state = one.unavailable ? t('homePage.offline')
              : one.kind === 'scene' ? '' : one.kind === 'script' ? (one.running ? t('homePage.scenes.running') : t('homePage.scenes.script'))
              : `${one.on ? t('homePage.on') : t('homePage.off')}${one.on && typeof one.power === 'number' ? ` · ${watts(one.power)}` : ''}`
            return (
              <li key={one.rid || one.entity_id}>
                <label className={`flex items-center gap-3 px-2 py-2 rounded-lg ${!on && full ? 'opacity-50' : 'cursor-pointer hover:bg-surface-hover'}`}>
                  <input type="checkbox" className="accent-[var(--nd-accent)] w-4 h-4 flex-none" checked={on} disabled={!on && full} aria-label={one.name}
                    onChange={(event) => setChosen((now) => (event.target.checked ? [...now, one.entity_id] : now.filter((id) => id !== one.entity_id)))} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium truncate">{one.name}</span>
                    <span className="block text-[11px] text-muted truncate">{one.area ? `${one.area} · ` : ''}<span className="font-mono">{one.entity_id}</span></span>
                  </span>
                  <span className="num text-[11.5px] text-muted whitespace-nowrap">{state}</span>
                </label>
              </li>
            )
          })}
        </ul>
      </div>
    </Dialog>
  )
}
