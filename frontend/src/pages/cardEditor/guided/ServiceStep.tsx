import { useQuery } from '@tanstack/react-query'
import { ClipboardPaste, Plus, Search } from 'lucide-react'
import { useId, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { get } from '../../../api/client'
import type { Integration } from '../../../api/types'
import { ServiceIcon } from '../../../components/ServiceIcon'
import { Select } from '../../../components/ui'
import { deleteAt, setAt } from '../../../lib/cardDocument'
import type { CardSource } from '../../../lib/customCards'
import { useConnections } from '../connections'
import { useCardEditor } from '../store'
import { GuidedFrame, StepNav } from './GuidedWay'
import { writeShape } from './guided'
import { useReplaceGuard } from './ReplaceGuard'
import { byCategory, matchingServices, serviceGroups, type ServiceKind } from './services'

/**
 * What the card is tried with (D3): the one connection of the kind it reads, taken quietly; a choice between several,
 * for the answers and the preview only and never written into the card; and for none, the way to make one. The card
 * itself works with every connection of its kind.
 */
export function TryWith({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation()
  const id = useId()
  const { kinds, fitting, chosen, loaded } = useConnections()
  if (!loaded || !kinds.length) return null
  if (!fitting.length) {
    return (
      <div className="rounded-xl border border-warn/40 px-3 py-2 flex flex-wrap items-center gap-2 min-w-0" role="status" data-testid="card-no-connection">
        <p className="text-sm min-w-0 flex-1 basis-60 break-words hyphens-auto">{t('editor.guided.service.noneOfKind')}</p>
        <Link className="btn" to={`/system/integrations?add=${encodeURIComponent(kinds[0])}`}>
          {t('editor.guided.service.add')}
        </Link>
      </div>
    )
  }
  if (fitting.length === 1 || !chosen) {
    return (
      <small className="text-[12px] text-muted break-words hyphens-auto" data-testid="card-try-with">
        {t('editor.guided.service.tryWith')}: {fitting[0].name}
      </small>
    )
  }
  return (
    <span className={`grid gap-1 min-w-0 ${compact ? '' : 'sm:max-w-xs'}`} data-testid="card-try-with">
      <label className="text-[12px] text-muted" htmlFor={`${id}-try`}>
        {t('editor.guided.service.tryWith')}
      </label>
      <Select
        id={`${id}-try`}
        value={String(chosen.id)}
        options={fitting.map((one) => ({ value: String(one.id), label: one.name }))}
        onChange={(value) => useCardEditor.getState().setIntegration(Number(value))}
      />
    </span>
  )
}

/**
 * Step 1, Service (D1 to D3): one tile for each kind of service a card can read, never one for each connection of the
 * person. A tile sets the kind of the card (`requires`, replaced, never added to); the connection the answers and the
 * preview come from is picked next to it and the card itself never names it (decision 4).
 */
export function ServiceStep() {
  const { t } = useTranslation()
  const ids = useId()
  const [query, setQuery] = useState('')
  const sources = useQuery({ queryKey: ['cards-sources'], queryFn: () => get<CardSource[]>('/cards/sources'), staleTime: 60_000 })
  const integrations = useQuery({ queryKey: ['integrations'], queryFn: () => get<Integration[]>('/integrations') })
  const { kinds } = useConnections()
  const slug = useCardEditor((state) => state.slug)
  const guard = useReplaceGuard()
  const categoryLabel = (category: string) => t(`library.category.${category}`, { defaultValue: category })
  const groups = useMemo(() => serviceGroups(sources.data ?? [], integrations.data ?? []), [sources.data, integrations.data])
  const connected = matchingServices(groups.connected, query, categoryLabel)
  const others = byCategory(matchingServices(groups.others, query, categoryLabel))

  const pick = (one: ServiceKind) => {
    const same = kinds.length === 1 && kinds[0] === one.kind
    const go = () => {
      const editor = useCardEditor.getState()
      if (!same) {
        editor.change((doc) => {
          setAt(doc, ['requires'], [one.kind])
          // What was read from another service means nothing here: back to one request that asks nothing yet.
          setAt(doc, ['requests'], [{ id: 'main', path: '/' }])
          deleteAt(doc, ['demo'])
          writeShape(doc, { form: 'value', number: { kind: 'field', path: '@' } })
        })
        useCardEditor.setState({ shapedPath: null, pendingShape: null, shapeMemory: {} })
      }
      // Tried with the connection already chosen if it is of this kind, else the first; none is as good as any.
      const current = useCardEditor.getState().integrationId
      const next = one.connections.find((connection) => connection.id === current)?.id ?? one.connections[0]?.id ?? null
      if (next !== current) editor.setIntegration(next)
      editor.setGuidedStep('data')
    }
    // Another kind of service starts the card over: what the guided way cannot show is asked about first.
    if (same) go()
    else guard.ask(go)
  }

  const tile = (one: ServiceKind) => {
    const pressed = kinds.length === 1 && kinds[0] === one.kind
    return (
      <div key={one.kind} className="grid gap-1.5 min-w-0 content-start">
        <button
          type="button"
          aria-pressed={pressed}
          className={`text-left grid gap-1.5 rounded-2xl border p-3 min-w-0 ${pressed ? 'border-accent ring-[3px] ring-accent/20' : 'border-line hover:border-line-strong hover:bg-surface-hover'}`}
          onClick={() => pick(one)}
        >
          <span className="flex items-center gap-2.5 min-w-0">
            <ServiceIcon icon={one.icon || one.kind} size={28} />
            <span className="font-semibold text-sm min-w-0 break-words hyphens-auto">{one.label}</span>
          </span>
          {one.connections.length > 1 && <small className="text-[12px] text-muted">{t('editor.guided.service.connections', { count: one.connections.length })}</small>}
        </button>
        {pressed && <TryWith compact />}
      </div>
    )
  }
  const grid = 'grid gap-2.5 grid-cols-[repeat(auto-fill,minmax(170px,1fr))] min-w-0'
  const heading = 'text-[11px] uppercase tracking-wide text-faint break-words'

  return (
    <GuidedFrame id="service" title={t('editor.guided.service.title')} lead={t('editor.guided.service.lead')}>
      <label className="relative block min-w-0" htmlFor={`${ids}-search`}>
        <span className="sr-only">{t('editor.guided.service.search')}</span>
        <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint pointer-events-none" aria-hidden="true" />
        <input
          id={`${ids}-search`}
          type="search"
          className="input w-full pl-9"
          placeholder={t('editor.guided.service.search')}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      {connected.length > 0 && (
        <section className="grid gap-2 min-w-0" aria-labelledby={`${ids}-mine`} data-testid="card-services-mine">
          <h3 id={`${ids}-mine`} className={heading}>
            {t('editor.guided.service.mine')}
          </h3>
          <div className={grid}>{connected.map(tile)}</div>
        </section>
      )}
      {others.length > 0 && (
        <section className="grid gap-3 min-w-0" aria-labelledby={`${ids}-all`} data-testid="card-services-all">
          <h3 id={`${ids}-all`} className={heading}>
            {t('editor.guided.service.all')}
          </h3>
          {others.map(([category, list]) => (
            <div key={category} className="grid gap-2 min-w-0">
              <h4 className="text-[12px] font-medium text-muted break-words">{categoryLabel(category)}</h4>
              <div className={grid}>{list.map(tile)}</div>
            </div>
          ))}
        </section>
      )}
      {sources.isSuccess && !connected.length && !others.length && query.trim() && (
        <p className="text-sm text-muted" role="status">
          {t('editor.guided.service.noMatch')}
        </p>
      )}
      <p className="text-[12px] text-faint flex flex-wrap items-center gap-x-2 gap-y-1 break-words hyphens-auto">
        <span>{t('editor.guided.service.missing')}</span>
        <Link className="text-accent font-medium inline-flex items-center gap-1" to="/system/integrations">
          <Plus size={13} /> {t('editor.guided.service.add')}
        </Link>
      </p>
      {slug === null && (
        <button
          type="button"
          className="btn btn-flat justify-self-start"
          onClick={() => useCardEditor.getState().open({ slug: null, text: '', base: null, saved: null, view: 'yaml' })}
        >
          <ClipboardPaste size={15} /> {t('editor.guided.service.paste')}
        </button>
      )}
      {guard.dialog}
      <StepNav />
    </GuidedFrame>
  )
}
