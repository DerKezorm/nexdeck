import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { get } from '../api/client'
import { ServiceIcon } from './ServiceIcon'
import { Field } from './ui'

/** An icon field with a live search across the two logo collections. */
export function IconPicker({ value, onChange, label }: { value: string; onChange: (value: string) => void; label: string }) {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const results = useQuery({ queryKey: ['icons', query], queryFn: () => get<{ name: string; source: string }[]>(`/icons/search?q=${encodeURIComponent(query)}`), enabled: query.trim().length >= 2 })
  return (
    <Field label={label} help={t('widget.iconHelp')}>
      <div className="flex items-center gap-2">
        <span className="w-9 h-9 rounded-lg glass flex items-center justify-center flex-none">
          <ServiceIcon icon={value} size={22} />
        </span>
        <input className="input" value={value} placeholder="radarr, lucide:rss, https://…" onChange={(e) => onChange(e.target.value)} />
      </div>
      <input className="input mt-2" placeholder={t('widget.iconSearch')} value={query} onChange={(e) => setQuery(e.target.value)} />
      {results.data && results.data.length > 0 && (
        <div className="grid grid-cols-6 gap-1 mt-2">
          {results.data.slice(0, 18).map((hit) => (
            <button key={hit.name} type="button" className={`h-11 rounded-lg border flex flex-col items-center justify-center gap-0.5 ${value === hit.name ? 'border-accent bg-accent-soft' : 'border-line hover:bg-surface-hover'}`} onClick={() => onChange(hit.name)} title={hit.name}>
              <ServiceIcon icon={hit.name} size={18} />
              <span className="text-[9px] text-muted truncate max-w-full px-1">{hit.name}</span>
            </button>
          ))}
        </div>
      )}
    </Field>
  )
}
