import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { LayoutGrid } from 'lucide-react'
import { useEffect, useId, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { get } from '../api/client'
import { IconPickerDialog } from './IconPickerDialog'
import { ServiceIcon } from './ServiceIcon'
import { Field } from './ui'

interface Hit {
  name: string
  source: string
}

/** Names are searched; symbols, addresses and data URLs are taken as they are. */
function searchable(value: string): boolean {
  const text = value.trim()
  return text.length >= 2 && !text.startsWith('lucide:') && !text.startsWith('http') && !text.startsWith('/') && !text.startsWith('data:')
}

/**
 * One field for the icon, two ways in. Typing a service name shows matching
 * logos underneath; the button opens the overview of every symbol and logo.
 * ``lucide:name`` and image addresses pass through untouched.
 *
 * The search and the preview wait a moment after the last keystroke: every
 * logo tile loads through the server, and a request per keystroke would
 * queue behind those images and look dead.
 */
export function IconPicker({ value, onChange, label }: { value: string; onChange: (value: string) => void; label: string }) {
  const { t } = useTranslation()
  const id = useId()
  // A chosen tile hides the suggestions until the user types again.
  const [picked, setPicked] = useState(false)
  const [overview, setOverview] = useState(false)
  const [needle, setNeedle] = useState('')
  const [preview, setPreview] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setNeedle(searchable(value) ? value.trim() : '')
      setPreview(value)
    }, 300)
    return () => window.clearTimeout(timer)
  }, [value])
  const results = useQuery({
    queryKey: ['icons', needle],
    queryFn: () => get<Hit[]>(`/icons/search?q=${encodeURIComponent(needle)}`),
    enabled: needle.length >= 2,
    placeholderData: keepPreviousData,
    staleTime: 300_000,
  })
  const active = needle.length >= 2 && !picked
  const searching = searchable(value) && !picked && (value.trim() !== needle || results.isFetching)
  const hits = active ? (results.data ?? []) : []
  const take = (name: string) => {
    onChange(name)
    setPicked(true)
  }
  return (
    <Field label={label} help={t('widget.iconHelp')} htmlFor={id}>
      <div className="flex items-center gap-2">
        <span className="w-9 h-9 rounded-lg glass flex items-center justify-center flex-none">
          <ServiceIcon icon={preview} size={22} />
        </span>
        <input
          id={id}
          className="input"
          value={value}
          placeholder={t('widget.iconPlaceholder')}
          autoComplete="off"
          spellCheck={false}
          onChange={(event) => {
            setPicked(false)
            onChange(event.target.value)
          }}
        />
        <button type="button" className="btn flex-none" onClick={() => setOverview(true)}>
          <LayoutGrid size={14} /> {t('widget.iconPick')}
        </button>
      </div>
      {searching && (
        <p className="text-[11px] text-muted mt-1" role="status">
          {t('widget.iconSearching')}
        </p>
      )}
      {!searching && active && results.isError && (
        <p className="text-[11px] text-bad mt-1" role="alert">
          {t('widget.iconSearchFailed')}
        </p>
      )}
      {!searching && active && results.isSuccess && hits.length === 0 && (
        <p className="text-[11px] text-muted mt-1" role="status">
          {t('widget.iconNothing', { query: needle })}
        </p>
      )}
      {hits.length > 0 && (
        <div className={`grid grid-cols-6 gap-1 mt-2 ${searching ? 'opacity-60' : ''}`} data-testid="icon-results">
          {hits.slice(0, 18).map((hit) => (
            <button
              key={hit.name}
              type="button"
              className={`h-11 rounded-lg border flex flex-col items-center justify-center gap-0.5 ${value === hit.name ? 'border-accent bg-accent-soft' : 'border-line hover:bg-surface-hover'}`}
              aria-pressed={value === hit.name}
              onClick={() => take(hit.name)}
              title={hit.name}
            >
              <ServiceIcon icon={hit.name} size={18} />
              <span className="text-[9px] text-muted truncate max-w-full px-1">{hit.name}</span>
            </button>
          ))}
        </div>
      )}
      <IconPickerDialog open={overview} value={value} onPick={take} onClose={() => setOverview(false)} />
    </Field>
  )
}
