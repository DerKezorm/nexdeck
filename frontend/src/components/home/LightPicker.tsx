import { useQuery } from '@tanstack/react-query'
import { Lightbulb, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { get } from '../../api/client'
import { LAMP_STYLES, lampColour, type LampInfo, type LampStyle, type LightOffer } from '../../lib/home'
import { Dialog, Select, Spinner } from '../ui'

interface Props {
  open: boolean
  pageId: number
  /** Registry ids already on the page: shown, not offered twice. */
  placed: Set<string>
  onClose: () => void
  onAdd: (lights: LampInfo[], style: LampStyle) => void
}

/** The style a browser last added lamps in, so the next ones match; a convenience, kept in the browser. */
const LAST_STYLE = 'nexdeck.homeLampStyle'

function lastStyle(): LampStyle {
  try {
    const kept = localStorage.getItem(LAST_STYLE)
    return (LAMP_STYLES as readonly string[]).includes(kept ?? '') ? (kept as LampStyle) : 'pill'
  } catch {
    return 'pill'
  }
}

/**
 * Picking lamps for a home page: every lamp of the page's Home Assistant that
 * is worth a wall, by name, with its room and entity id to tell two "Ceiling
 * light"s apart. What is filtered out, and why, is the server's business
 * (``hass_registry.pick_lights``).
 */
export function LightPicker({ open, pageId, placed, onClose, onAdd }: Props) {
  const { t } = useTranslation()
  const offer = useQuery({ queryKey: ['home-lights', pageId], queryFn: () => get<LightOffer>(`/pages/${pageId}/home/lights`), enabled: open, staleTime: 30_000 })
  const [query, setQuery] = useState('')
  const [chosen, setChosen] = useState<string[]>([])
  const [style, setStyle] = useState<LampStyle>(lastStyle)
  const lights = useMemo(() => offer.data?.lights ?? [], [offer.data])
  const shown = useMemo(() => {
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
    return lights.filter((light) => words.every((word) => `${light.name} ${light.area} ${light.entity_id}`.toLowerCase().includes(word)))
  }, [lights, query])
  const problem = offer.data?.problem ?? null

  const close = () => {
    setChosen([])
    setQuery('')
    onClose()
  }
  const add = () => {
    const picked = lights.filter((light) => chosen.includes(light.rid))
    setChosen([])
    setQuery('')
    try {
      localStorage.setItem(LAST_STYLE, style)
    } catch {
      // Storage may be unavailable; the next pick starts from the pill again, which is fine.
    }
    onAdd(picked, style)
  }

  return (
    <Dialog
      open={open}
      onClose={close}
      title={t('homePage.pickTitle')}
      footer={
        <>
          <label className="flex items-center gap-2 mr-auto text-sm text-muted">
            {t('homePage.style')}
            <Select value={style} onChange={(value) => setStyle(value as LampStyle)} options={LAMP_STYLES.map((one) => ({ value: one, label: t(`homePage.styles.${one}`) }))} />
          </label>
          <button type="button" className="btn btn-accent" disabled={chosen.length === 0} onClick={add}>
            {chosen.length === 0 ? t('homePage.pickNone') : t('homePage.pickAdd', { count: chosen.length })}
          </button>
        </>
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
        {!offer.isLoading && !problem && shown.length === 0 && <p className="text-sm text-muted py-4 text-center">{t('homePage.pickEmpty')}</p>}
        {shown.length > 0 && (
          <ul className="grid gap-0.5 max-h-[50vh] overflow-y-auto -mx-1" aria-label={t('homePage.pickTitle')}>
            {shown.map((light) => {
              const there = placed.has(light.rid)
              const colour = lampColour(light)
              return (
                <li key={light.rid || light.entity_id}>
                  <label className={`flex items-center gap-3 px-2 py-2 rounded-lg ${there ? 'opacity-60' : 'cursor-pointer hover:bg-surface-hover'}`}>
                    <input
                      type="checkbox"
                      className="accent-[var(--nd-accent)] w-4 h-4 flex-none"
                      disabled={there}
                      checked={there || chosen.includes(light.rid)}
                      onChange={(event) => setChosen((now) => (event.target.checked ? [...now, light.rid] : now.filter((rid) => rid !== light.rid)))}
                      aria-label={light.name}
                    />
                    <span className="grid place-items-center w-7 h-7 rounded-full flex-none" style={colour ? { background: colour, color: '#1b1206' } : { background: 'color-mix(in srgb, var(--nd-text) 8%, transparent)' }}>
                      <Lightbulb size={14} className={colour ? '' : 'text-muted'} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium truncate">{light.name}</span>
                      <span className="block text-[11px] text-muted truncate">
                        {light.area ? `${light.area} · ` : ''}
                        <span className="font-mono">{light.entity_id}</span>
                      </span>
                    </span>
                    <span className="text-[11px] text-faint whitespace-nowrap">{there ? t('homePage.placed') : light.unavailable ? t('homePage.unavailable') : ''}</span>
                  </label>
                </li>
              )
            })}
          </ul>
        )}
        <p className="text-xs text-faint">{t('homePage.pickHelp')}</p>
      </div>
    </Dialog>
  )
}
