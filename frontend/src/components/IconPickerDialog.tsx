import { useQuery } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, del, get, upload } from '../api/client'
import { ServiceIcon, SYMBOLS } from './ServiceIcon'
import { Confirm, Dialog } from './ui'

interface Named {
  name: string
  source: string
}

/** An uploaded file, as the assets list returns it. */
interface Uploaded {
  id: number
  filename: string
  url: string
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
  //: What this installation uploaded. Kept apart from the collections: these
  //: are the ones somebody chose to add, and they belong at the top.
  const mine = useQuery({ queryKey: ['icon-uploads'], queryFn: () => get<Uploaded[]>('/assets?kind=icon'), enabled: open })
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState('')
  const [removing, setRemoving] = useState<Uploaded | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
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
  const take = (file: File) => {
    setFailed('')
    setBusy(true)
    upload('/assets', file, { kind: 'icon' })
      .then((asset) => {
        void mine.refetch()
        pick((asset as Uploaded).url)
      })
      .catch((why) => setFailed(why instanceof ApiError ? why.message : t('errors.network')))
      .finally(() => setBusy(false))
  }

  return (
    <Dialog open={open} onClose={onClose} title={t('widget.iconDialogTitle')} size="lg">
      <input className="input mb-4" autoFocus aria-label={t('widget.iconDialogSearch')} placeholder={t('widget.iconDialogSearch')} value={query} onChange={(event) => setQuery(event.target.value)} autoComplete="off" spellCheck={false} />

      <section className="mb-4">
        <h3 className="text-[11px] uppercase tracking-wide text-faint mb-1.5">{t('widget.iconOwn')}</h3>
        <div className="grid grid-cols-4 sm:grid-cols-8 gap-1">
          {(mine.data ?? []).map((one) => (
            <div key={one.id} className="relative">
              <Tile icon={one.url} label={one.filename} active={value === one.url} onClick={() => pick(one.url)} />
              <button
                type="button"
                className="btn btn-icon btn-danger absolute -top-1 -right-1 h-5 w-5"
                aria-label={t('widget.iconRemove', { name: one.filename })}
                title={t('widget.iconRemove', { name: one.filename })}
                onClick={() => setRemoving(one)}
              >
                <Trash2 size={11} />
              </button>
            </div>
          ))}
          {/* ⚠️ A label, not a bare file input styled to look like a button.
              The input itself has to stay reachable by keyboard, and hiding it
              with display:none takes it out of the tab order. */}
          <label className="h-14 rounded-lg border border-dashed border-line flex flex-col items-center justify-center gap-1 cursor-pointer hover:bg-surface-hover focus-within:border-accent">
            <span className="text-lg leading-none text-muted" aria-hidden="true">+</span>
            <span className="text-[9px] text-muted px-1 text-center">{busy ? t('common.loading') : t('widget.iconUpload')}</span>
            <input
              ref={fileInput}
              type="file"
              accept="image/*"
              // Its own name: inside the label the accessible name would come
              // out as "+ Upload", the plus included.
              aria-label={t('widget.iconUpload')}
              className="sr-only"
              disabled={busy}
              onChange={(event) => {
                const file = event.target.files?.[0]
                event.target.value = ''
                if (file) take(file)
              }}
            />
          </label>
        </div>
        <p className="text-[11px] text-faint mt-1">{t('widget.iconUploadHelp')}</p>
        {failed && (
          <p className="text-[12px] text-bad mt-1" role="alert">
            {failed}
          </p>
        )}
      </section>
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
      <Confirm
        open={removing !== null}
        title={t('widget.iconRemove', { name: removing?.filename ?? '' })}
        body={t('widget.iconRemoveHelp')}
        confirmLabel={t('common.delete')}
        danger
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          const one = removing
          setRemoving(null)
          if (!one) return
          void del(`/assets/${one.id}`)
            .then(() => mine.refetch())
            .catch((why) => setFailed(why instanceof ApiError ? why.message : t('errors.network')))
        }}
      />
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
