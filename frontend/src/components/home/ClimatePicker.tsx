import { useQuery } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { get } from '../../api/client'
import { temperature, type ClimateInfo, type ClimateOffer } from '../../lib/home'
import { Dialog, Spinner } from '../ui'
import { climateLook } from './ClimateControl'

interface Props {
  open: boolean
  pageId: number
  /** Registry ids already on the page: shown, not offered twice. */
  placed: Set<string>
  onClose: () => void
  onAdd: (climates: ClimateInfo[]) => void
}

/**
 * Picking thermostats for a home page, as lamps are picked: by name, with the
 * room and entity id to tell them apart. What is offered is the server's
 * business (``hass_registry.pick_climates``).
 */
export function ClimatePicker({ open, pageId, placed, onClose, onAdd }: Props) {
  const { t } = useTranslation()
  const offer = useQuery({ queryKey: ['home-climates', pageId], queryFn: () => get<ClimateOffer>(`/pages/${pageId}/home/climates`), enabled: open, staleTime: 30_000 })
  const [query, setQuery] = useState('')
  const [chosen, setChosen] = useState<string[]>([])
  const climates = useMemo(() => offer.data?.climates ?? [], [offer.data])
  const shown = useMemo(() => {
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
    return climates.filter((one) => words.every((word) => `${one.name} ${one.area} ${one.entity_id}`.toLowerCase().includes(word)))
  }, [climates, query])
  const problem = offer.data?.problem ?? null

  const close = () => {
    setChosen([])
    setQuery('')
    onClose()
  }
  const add = () => {
    const picked = climates.filter((one) => chosen.includes(one.rid))
    setChosen([])
    setQuery('')
    onAdd(picked)
  }

  return (
    <Dialog
      open={open}
      onClose={close}
      title={t('homePage.pickClimateTitle')}
      footer={
        <button type="button" className="btn btn-accent" disabled={chosen.length === 0} onClick={add}>
          {chosen.length === 0 ? t('homePage.pickClimateNone') : t('homePage.pickAdd', { count: chosen.length })}
        </button>
      }
    >
      <div className="grid gap-3">
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
        {!offer.isLoading && !problem && shown.length === 0 && <p className="text-sm text-muted py-4 text-center">{t('homePage.pickClimateEmpty')}</p>}
        {shown.length > 0 && (
          <ul className="grid gap-0.5 max-h-[50vh] overflow-y-auto -mx-1" aria-label={t('homePage.pickClimateTitle')}>
            {shown.map((one) => {
              const there = placed.has(one.rid)
              const { colour, icon } = climateLook({ ...one, reading: one.current, sensor: null })
              return (
                <li key={one.rid || one.entity_id}>
                  <label className={`flex items-center gap-3 px-2 py-2 rounded-lg ${there ? 'opacity-60' : 'cursor-pointer hover:bg-surface-hover'}`}>
                    <input type="checkbox" className="accent-[var(--nd-accent)] w-4 h-4 flex-none" disabled={there} checked={there || chosen.includes(one.rid)} aria-label={one.name}
                      onChange={(event) => setChosen((now) => (event.target.checked ? [...now, one.rid] : now.filter((rid) => rid !== one.rid)))} />
                    <span className="grid place-items-center w-7 h-7 rounded-full flex-none" style={colour ? { background: colour, color: '#1b1206' } : { background: 'color-mix(in srgb, var(--nd-text) 8%, transparent)' }}>
                      {icon}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium truncate">{one.name}</span>
                      <span className="block text-[11px] text-muted truncate">
                        {one.area ? `${one.area} · ` : ''}
                        <span className="font-mono">{one.entity_id}</span>
                      </span>
                    </span>
                    <span className="num text-[11px] text-faint whitespace-nowrap">{there ? t('homePage.placed') : one.unavailable ? t('homePage.unavailable') : temperature(one.current)}</span>
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
