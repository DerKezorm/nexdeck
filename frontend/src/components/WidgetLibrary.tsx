import { useQuery } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { ApiError, get, post } from '../api/client'
import type { AdapterSpec, Integration, WidgetTypeSpec } from '../api/types'
import { tAdapter } from '../i18n/texts'
import { ServiceIcon } from './ServiceIcon'
import { Select, Sheet } from './ui'

interface Props {
  open: boolean
  onClose: () => void
  pageId: number
  onCreated: (widgetId: number) => void
}

/**
 * The name a new card is born with, in the language of whoever adds it.
 *
 * ⚠️ **The widget name is translated, the service name is not.** Somebody who
 * picks "Fehlende Untertitel" in the library used to get a card called
 * "Missing subtitles": the title is stored text, and the server only knows the
 * English word. Bazarr, Plex and UniFi stay as they write themselves.
 *
 * The rule against a doubled word still looks at the **English** pair, because
 * that is where the doubling comes from: "UniFi Network" + "Network" is one
 * name in every language, and comparing it with "Netzwerk" would bring the
 * repetition back in German.
 */
export function defaultTitle(adapter: { kind: string; label: string }, widget: { label: string }): string {
  const kind = tAdapter(widget.label).trim()
  if (adapter.kind === 'core') return kind
  const service = adapter.label.trim()
  const english = widget.label.trim()
  if (service.toLowerCase().endsWith(english.toLowerCase())) return service
  if (english.toLowerCase().startsWith(service.toLowerCase())) return kind
  return `${service} ${kind}`
}

const CATEGORY_ORDER = ['basics', 'feeds', 'generic', 'hosts', 'nas', 'downloads', 'media', 'network', 'monitoring', 'other']

/**
 * Everything a card can be found by.
 *
 * ⚠️ The technical name counts too. "Wake-on-LAN" does not contain "wol",
 * "Proxmox Backup Server" does not contain "pbs", and "Nginx Proxy Manager"
 * does not contain "npm". Those are exactly what somebody types.
 */
export function haystack(adapter: AdapterSpec, widget: WidgetTypeSpec): string {
  return [
    adapter.kind,
    widget.kind,
    adapter.label,
    widget.label,
    tAdapter(widget.label),
    widget.description,
    tAdapter(widget.description),
    adapter.category,
  ]
    .join(' ')
    .toLowerCase()
}

/** The widget library: every adapter's widgets, searchable, one click to add. */
export function WidgetLibrary({ open, onClose, pageId, onCreated }: Props) {
  const { t } = useTranslation()
  const adapters = useQuery({ queryKey: ['adapters'], queryFn: () => get<AdapterSpec[]>('/adapters'), enabled: open, staleTime: 300_000 })
  const integrations = useQuery({ queryKey: ['integrations'], queryFn: () => get<Integration[]>('/integrations'), enabled: open })
  const [query, setQuery] = useState('')
  const [picking, setPicking] = useState<{ adapter: AdapterSpec; widget: WidgetTypeSpec } | null>(null)
  const [integrationId, setIntegrationId] = useState<string>('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const result: Record<string, { adapter: AdapterSpec; widget: WidgetTypeSpec }[]> = {}
    for (const adapter of adapters.data ?? []) {
      for (const widget of adapter.widgets) {
        if (needle && !haystack(adapter, widget).includes(needle)) continue
        ;(result[adapter.category] ??= []).push({ adapter, widget })
      }
    }
    return Object.entries(result).sort(([a], [b]) => CATEGORY_ORDER.indexOf(a) - CATEGORY_ORDER.indexOf(b))
  }, [adapters.data, query])

  const create = async (adapter: AdapterSpec, widget: WidgetTypeSpec, chosen: number | null) => {
    setBusy(true)
    setError('')
    try {
      const result = await post<{ widget: { id: number } }>(`/pages/${pageId}/widgets`, {
        kind: widget.kind,
        title: defaultTitle(adapter, widget),
        integration_id: chosen,
        options: Object.fromEntries(widget.options.filter((o) => o.default !== null && o.default !== undefined).map((o) => [o.name, o.default])),
      })
      setPicking(null)
      onCreated(result.widget.id)
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : t('errors.network'))
    } finally {
      setBusy(false)
    }
  }

  const choose = (adapter: AdapterSpec, widget: WidgetTypeSpec) => {
    if (!adapter.needs_integration) {
      void create(adapter, widget, null)
      return
    }
    const matching = (integrations.data ?? []).filter((i) => i.kind === adapter.kind)
    if (matching.length === 1) {
      void create(adapter, widget, matching[0].id)
      return
    }
    setIntegrationId(matching[0] ? String(matching[0].id) : '')
    setPicking({ adapter, widget })
  }

  return (
    <Sheet open={open} onClose={onClose} title={t('library.title')} wide>
      <div className="relative mb-3">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
        <input className="input pl-8" placeholder={t('library.search')} value={query} onChange={(e) => setQuery(e.target.value)} autoFocus />
      </div>
      {error && (
        <p className="text-sm text-bad mb-2" role="alert">
          {error}
        </p>
      )}
      {picking && (
        <div className="glass rounded-xl p-3 mb-3">
          <div className="text-sm font-medium mb-2">{t('library.pickIntegration', { name: picking.adapter.label })}</div>
          {(integrations.data ?? []).filter((i) => i.kind === picking.adapter.kind).length > 0 ? (
            <Select value={integrationId} onChange={setIntegrationId} options={(integrations.data ?? []).filter((i) => i.kind === picking.adapter.kind).map((i) => ({ value: String(i.id), label: i.name }))} />
          ) : (
            <p className="text-xs text-muted">
              {t('library.noIntegration')}{' '}
              <Link to={`/system/integrations?add=${picking.adapter.kind}`} className="text-accent">
                {t('library.addIntegration')}
              </Link>
            </p>
          )}
          <div className="flex justify-end gap-2 mt-3">
            <button className="btn" onClick={() => setPicking(null)}>
              {t('common.cancel')}
            </button>
            <button className="btn btn-accent" disabled={!integrationId || busy} onClick={() => void create(picking.adapter, picking.widget, Number(integrationId))}>
              {t('common.add')}
            </button>
          </div>
        </div>
      )}
      {groups.map(([category, entries]) => (
        <section key={category} className="mb-4">
          <h3 className="text-[11px] uppercase tracking-wide text-faint mb-1.5">{t(`library.category.${category}`, { defaultValue: category })}</h3>
          <ul className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
            {entries.map(({ adapter, widget }) => (
              <li key={widget.kind}>
                <button className="w-full text-left flex items-start gap-3 p-2.5 rounded-xl border border-line hover:border-line-strong hover:bg-surface-hover transition-colors" onClick={() => choose(adapter, widget)} disabled={busy}>
                  <ServiceIcon icon={adapter.icon} size={22} className="mt-0.5" />
                  <span className="min-w-0">
                    <span className="block text-[13px] font-medium">
                      {adapter.kind === 'core' ? tAdapter(widget.label) : `${adapter.label} · ${tAdapter(widget.label)}`}
                      {adapter.beta && (
                        <span className="chip ml-1.5 !py-0 text-[10px] cursor-help" title={t('widget.betaHelp')}>
                          beta
                        </span>
                      )}
                    </span>
                    <span className="block text-[11px] text-muted leading-snug">{tAdapter(widget.description)}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
      {adapters.isLoading && <p className="text-sm text-muted">{t('common.loading')}</p>}
    </Sheet>
  )
}
