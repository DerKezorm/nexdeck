/**
 * The search field, on the board instead of behind Ctrl+K.
 *
 * The way out of the house existed only in the command palette, which you
 * have to know about. On a board that is somebody's start page the field
 * belongs in front of them. Same targets, same `!shortcut`, same address
 * building as the palette: another door to the same room, not a second
 * implementation.
 */
import { useQuery } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { get } from '../api/client'
import { pickTarget, searchUrl, type SearchSettings, type SearchTarget } from '../lib/search'
import type { RenderProps } from './renderers'
import { ServiceIcon } from './ServiceIcon'

export function SearchCard({ data, editing }: RenderProps) {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const field = useRef<HTMLInputElement>(null)

  const meta = data?.meta ?? {}
  const wantsFocus = Boolean(meta.autofocus) && !editing
  const newTab = meta.new_tab !== false
  const showTargets = meta.show_targets !== false
  const showShortcuts = meta.show_shortcuts !== false

  /** The same query and the same cache the palette uses, so both stay in step. */
  const search = useQuery({
    queryKey: ['search-targets'],
    queryFn: () => get<SearchSettings>('/settings/search'),
    staleTime: 5 * 60 * 1000,
  })

  useEffect(() => {
    if (wantsFocus) field.current?.focus()
  }, [wantsFocus])

  const settings = search.data
  const targets = settings?.targets ?? []

  if (search.isLoading) return <Hint>{t('common.loading')}</Hint>
  if (!settings?.enabled || targets.length === 0) {
    return (
      <Hint>
        {/* Not "no data": the card is fine, it has nothing to hand a word to yet. */}
        {t('card.search.notSetUp')}{' '}
        <Link className="underline" to="/settings/system">
          {t('card.search.setUpNow')}
        </Link>
      </Hint>
    )
  }

  const showRow = showTargets && targets.length > 1

  /** The target Enter uses: the one named in the settings, else the first. */
  const fallback = targets.find((one) => one.prefix.toLowerCase() === String(meta.target ?? '').toLowerCase()) ?? targets[0]

  function go(forced?: SearchTarget) {
    // `!y cats` picks a target inside the field, exactly as in the palette.
    const { chosen, rest } = pickTarget(targets, query)
    const words = (chosen ? rest : query).trim()
    if (!words) return
    const target = forced ?? chosen ?? fallback
    const url = searchUrl(target, words)
    if (newTab) window.open(url, '_blank', 'noopener,noreferrer')
    else window.location.assign(url)
    setQuery('')
  }

  const { chosen } = pickTarget(targets, query)
  const active = chosen ?? fallback

  return (
    // ⚠️ The field keeps its height whatever else is on the card. With a dozen
    // targets the row below used to squeeze it into a line: the one part that
    // has to be usable was the one that gave way. With no row at all the field
    // sits in the middle instead of leaving the space under it empty.
    <div className={`flex-1 min-h-0 flex flex-col gap-2 px-3 pb-3 ${showRow ? '' : 'justify-center'}`}>
      <form
        className="flex-none flex items-center gap-2 input"
        onSubmit={(event) => {
          event.preventDefault()
          go()
        }}
      >
        {active.icon ? <ServiceIcon icon={active.icon} size={16} /> : <Search size={16} className="text-faint" />}
        <input
          ref={field}
          type="search"
          className="flex-1 bg-transparent border-0 outline-none min-w-0"
          value={query}
          placeholder={String(meta.placeholder || '') || t('card.search.placeholder', { name: active.name })}
          aria-label={t('card.search.label')}
          // In edit mode the card is being dragged, not used.
          disabled={editing}
          onChange={(event) => setQuery(event.target.value)}
        />
      </form>
      {showRow && (
        // Its own scroller, so a long list never pushes the field out.
        <div className="flex-1 min-h-0 overflow-y-auto flex flex-wrap content-start gap-1.5">
          {targets.map((target) => (
            <button
              key={target.prefix || target.name}
              type="button"
              className="btn btn-xs"
              disabled={editing || !query.trim()}
              aria-label={t('card.search.searchWith', { name: target.name })}
              onClick={() => go(target)}
            >
              {target.icon ? <ServiceIcon icon={target.icon} size={13} /> : null}
              {target.name}
              {/* The shortcut only helps if it is written where the target is. */}
              {showShortcuts && target.prefix ? <span className="text-faint">!{target.prefix}</span> : null}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function Hint({ children }: { children: React.ReactNode }) {
  return <div className="flex-1 flex items-center justify-center text-xs text-faint px-3 pb-3 text-center">{children}</div>
}
