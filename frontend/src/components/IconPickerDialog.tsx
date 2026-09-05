import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { get } from '../api/client'
import { ServiceIcon, SYMBOLS } from './ServiceIcon'
import { Dialog } from './ui'

interface Named {
  name: string
  source: string
}

/** Tiles per page: enough to browse, few enough to stay quick while filtering. */
const PAGE = 240

/**
 * The overview: every symbol and every logo of both collections, filtered as
 * you type, one click to take one. The name index comes from the server once
 * a day; the filtering happens here, so it never waits for the network.
 */
export function IconPickerDialog({ open, value, onPick, onClose }: { open: boolean; value: string; onPick: (name: string) => void; onClose: () => void }) {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [shown, setShown] = useState(PAGE)
  useEffect(() => {
    if (open) {
      setQuery('')
      setShown(PAGE)
    }
  }, [open])
  const names = useQuery({ queryKey: ['icon-names'], queryFn: () => get<Named[]>('/icons/names'), enabled: open, staleTime: 86_400_000 })
  const needle = query.trim().toLowerCase()
  const symbols = useMemo(() => Object.keys(SYMBOLS).filter((name) => name.includes(needle)), [needle])
  const logos = useMemo(() => {
    const all = names.data ?? []
    if (!needle) return all
    return all
      .filter((entry) => entry.name.includes(needle))
      .sort((a, b) => Number(!a.name.startsWith(needle)) - Number(!b.name.startsWith(needle)) || a.name.length - b.name.length)
  }, [names.data, needle])
  useEffect(() => setShown(PAGE), [needle])
  const pick = (name: string) => {
    onPick(name)
    onClose()
  }
  return (
    <Dialog open={open} onClose={onClose} title={t('widget.iconDialogTitle')} size="lg">
      <input className="input mb-4" autoFocus placeholder={t('widget.iconDialogSearch')} value={query} onChange={(event) => setQuery(event.target.value)} autoComplete="off" spellCheck={false} />
      {symbols.length > 0 && (
        <section className="mb-4">
          <h3 className="text-[11px] uppercase tracking-wide text-faint mb-1.5">{t('widget.iconSymbols')}</h3>
          <div className="grid grid-cols-6 sm:grid-cols-10 gap-1">
            {symbols.map((name) => (
              <Tile key={name} icon={`lucide:${name}`} label={name} active={value === `lucide:${name}`} onClick={() => pick(`lucide:${name}`)} />
            ))}
          </div>
        </section>
      )}
      <section>
        <h3 className="text-[11px] uppercase tracking-wide text-faint mb-1.5">
          {t('widget.iconLogos')}
          {names.isSuccess && <span className="ml-1.5 num normal-case tracking-normal">{t('widget.iconCount', { count: logos.length })}</span>}
        </h3>
        {names.isLoading && <p className="text-sm text-muted">{t('common.loading')}</p>}
        {names.isError && (
          <p className="text-sm text-bad" role="alert">
            {t('widget.iconSearchFailed')}
          </p>
        )}
        {names.isSuccess && logos.length === 0 && (
          <p className="text-sm text-muted" role="status">
            {t('widget.iconNothing', { query: needle })}
          </p>
        )}
        <div className="grid grid-cols-4 sm:grid-cols-8 gap-1" data-testid="icon-overview">
          {logos.slice(0, shown).map((entry) => (
            <Tile key={entry.name} icon={entry.name} label={entry.name} active={value === entry.name} onClick={() => pick(entry.name)} />
          ))}
        </div>
        {logos.length > shown && (
          <button type="button" className="btn mt-3" onClick={() => setShown((current) => current + PAGE)}>
            {t('widget.iconMore', { count: logos.length - shown })}
          </button>
        )}
      </section>
    </Dialog>
  )
}

function Tile({ icon, label, active, onClick }: { icon: string; label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      className={`h-14 rounded-lg border flex flex-col items-center justify-center gap-1 ${active ? 'border-accent bg-accent-soft' : 'border-line hover:bg-surface-hover'}`}
      aria-pressed={active}
      title={label}
      onClick={onClick}
    >
      <ServiceIcon icon={icon} size={22} />
      <span className="text-[9px] text-muted truncate max-w-full px-1">{label}</span>
    </button>
  )
}
