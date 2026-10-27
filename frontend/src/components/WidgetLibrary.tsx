import { useQuery } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { ApiError, get, post, put } from '../api/client'
import type { AdapterSpec, AppEntry, Integration, WidgetTypeSpec } from '../api/types'
import { tAdapter, tLabel } from '../i18n/texts'
import { pickText } from '../lib/cardText'
import { isOwnKind, sourceLine, type LibraryCard } from '../lib/customCards'
import { CATEGORY_ORDER } from '../lib/adapterCategories'
import { isNumberCard } from '../lib/figures'
import { useAuth } from '../stores/auth'
import { ServiceIcon } from './ServiceIcon'
import { Select, Sheet } from './ui'

interface Props {
  open: boolean
  onClose: () => void
  pageId: number
  onCreated: (widgetId: number) => void
  /** For a tile of key figures: only the cards that show a number, and no apps. */
  numbersOnly?: boolean
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
    ...(adapter.keywords ?? []),
  ]
    .join(' ')
    .toLowerCase()
}

/** The widget library: every adapter's widgets, searchable, one click to add. */
export function WidgetLibrary({ open, onClose, pageId, onCreated, numbersOnly = false }: Props) {
  const { t, i18n } = useTranslation()
  const adapters = useQuery({ queryKey: ['adapters'], queryFn: () => get<AdapterSpec[]>('/adapters'), enabled: open, staleTime: 300_000 })
  const integrations = useQuery({ queryKey: ['integrations'], queryFn: () => get<Integration[]>('/integrations'), enabled: open })
  // The app catalog (issue #37): an app is placed straight from here, already following it.
  const apps = useQuery({ queryKey: ['apps'], queryFn: () => get<AppEntry[]>('/apps'), enabled: open, staleTime: 60_000 })
  // The custom cards this account may place (KARTEN-11): every one for an administrator, the released ones for anybody else.
  const cardLibrary = useQuery({ queryKey: ['cards-library'], queryFn: () => get<{ cards: LibraryCard[] }>('/cards/library'), enabled: open, staleTime: 30_000 })
  const admin = useAuth((state) => state.user?.role === 'admin')
  const [query, setQuery] = useState('')
  const [pickingCard, setPickingCard] = useState<LibraryCard | null>(null)
  const [cardConnection, setCardConnection] = useState('')
  const [picking, setPicking] = useState<{ adapter: AdapterSpec; widget: WidgetTypeSpec } | null>(null)
  const [integrationId, setIntegrationId] = useState<string>('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const result: Record<string, { adapter: AdapterSpec; widget: WidgetTypeSpec }[]> = {}
    for (const adapter of adapters.data ?? []) {
      // ⚠️ A custom card is placed from its own section, by the name of the card. Its four forms have no name of their own.
      if (adapter.kind === 'custom') continue
      for (const widget of adapter.widgets) {
        if (needle && !haystack(adapter, widget).includes(needle)) continue
        if (numbersOnly && !isNumberCard(widget)) continue
        ;(result[adapter.category] ??= []).push({ adapter, widget })
      }
    }
    return Object.entries(result).sort(([a], [b]) => CATEGORY_ORDER.indexOf(a) - CATEGORY_ORDER.indexOf(b))
  }, [adapters.data, query, numbersOnly])

  /** The custom cards that match the search, split into the ones with a connection that fits and the ones without. */
  const customCards = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const list = (cardLibrary.data?.cards ?? []).filter((card) => {
      // A card of blocks is a number only when it names its main value (KARTEN-7 AC-8).
      if (numbersOnly && card.form !== 'value' && card.form !== 'stats' && !(card.form === 'builder' && card.main)) return false
      return !needle || `${pickText(card.name, i18n.language)} ${pickText(card.description, i18n.language)} ${card.slug} ${sourceLine(card)}`.toLowerCase().includes(needle)
    })
    return { ready: list.filter((card) => card.fits.length > 0), waiting: list.filter((card) => card.fits.length === 0) }
  }, [cardLibrary.data, query, numbersOnly, i18n.language])

  const catalog = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const list = Array.isArray(apps.data) && !numbersOnly ? apps.data : []
    return list.filter((app) => !needle || `${app.name} ${app.description ?? ''}`.toLowerCase().includes(needle))
  }, [apps.data, query, numbersOnly])

  /** The connections of kinds the administrator described (KARTEN-3), offered as app tiles with their logo and address. */
  const ownConnections = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return (integrations.data ?? []).filter(
      (one) => isOwnKind(one) && !one.missing && one.enabled && !numbersOnly && (!needle || `${one.name} ${one.label}`.toLowerCase().includes(needle)),
    )
  }, [integrations.data, query, numbersOnly])

  /** A tile that follows a connection of an own kind: its name, its logo, its address, and the dot that asks its check path. */
  const placeConnection = async (connection: Integration) => {
    const tile = adapters.data?.find((one) => one.kind === 'core')?.widgets.find((one) => one.kind === 'core.app')
    setBusy(true)
    setError('')
    try {
      const defaults = Object.fromEntries((tile?.options ?? []).filter((o) => o.default !== null && o.default !== undefined).map((o) => [o.name, o.default]))
      const result = await post<{ widget: { id: number } }>(`/pages/${pageId}/widgets`, {
        kind: 'core.app',
        title: connection.name,
        icon: connection.icon,
        integration_id: connection.id,
        options: defaults,
      })
      // An empty target follows the address of the connection, at every check.
      await put(`/widgets/${result.widget.id}/health`, {
        kind: 'http', target: '', interval_seconds: 30, timeout_seconds: 5, expect_status: 0, enabled: true, insecure: connection.config.insecure === true,
      })
      onCreated(result.widget.id)
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : t('errors.network'))
    } finally {
      setBusy(false)
    }
  }

  /** An app tile that follows ``app``: its name and icon stay empty, so the app's show and follow a rename. */
  const placeApp = async (app: AppEntry) => {
    const tile = adapters.data?.find((one) => one.kind === 'core')?.widgets.find((one) => one.kind === 'core.app')
    setBusy(true)
    setError('')
    try {
      const defaults = Object.fromEntries((tile?.options ?? []).filter((o) => o.default !== null && o.default !== undefined).map((o) => [o.name, o.default]))
      const result = await post<{ widget: { id: number } }>(`/pages/${pageId}/widgets`, {
        kind: 'core.app',
        title: '',
        options: { ...defaults, app_id: app.id, address: app.home || app.away ? 'auto' : '' },
      })
      onCreated(result.widget.id)
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : t('errors.network'))
    } finally {
      setBusy(false)
    }
  }

  const create = async (adapter: AdapterSpec, widget: WidgetTypeSpec, chosen: number | null) => {
    setBusy(true)
    setError('')
    try {
      if (adapter.bars_widgets && chosen !== null) {
        // ⚠️ Asked before the card exists. A nexmail key that may only count
        // would give a sender list that can only ever show its hint.
        const shortKind = widget.kind.slice(adapter.kind.length + 1)
        const { reason } = await get<{ reason: string }>(`/integrations/${chosen}/barred/${encodeURIComponent(shortKind)}`)
        if (reason) {
          setError(tLabel(reason))
          return
        }
      }
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

  /** A custom card sits on a connection of a kind it names; its form and short name travel as the kind and the `card` option. */
  const placeCard = async (card: LibraryCard, chosen: number) => {
    setBusy(true)
    setError('')
    try {
      const result = await post<{ widget: { id: number } }>(`/pages/${pageId}/widgets`, {
        kind: `custom.${card.form}`,
        // In the language of whoever places it; the server would fall back to the English name.
        title: pickText(card.name, i18n.language),
        integration_id: chosen,
        options: { card: card.slug },
      })
      setPickingCard(null)
      onCreated(result.widget.id)
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : t('errors.network'))
    } finally {
      setBusy(false)
    }
  }

  const chooseCard = (card: LibraryCard) => {
    if (card.fits.length === 1) {
      void placeCard(card, card.fits[0].id)
      return
    }
    setCardConnection(String(card.fits[0].id))
    setPickingCard(card)
  }

  const choose = (adapter: AdapterSpec, widget: WidgetTypeSpec) => {
    if (!adapter.needs_integration) {
      // A card that can do without a connection still takes the first there
      // is: a GitHub card with a token has a hundred times the requests.
      const optional = adapter.optional_integration ? (integrations.data ?? []).find((i) => i.kind === adapter.kind) : undefined
      void create(adapter, widget, optional ? optional.id : null)
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
    <Sheet open={open} onClose={onClose} title={numbersOnly ? t('figures.library') : t('library.title')} wide>
      <div className="relative mb-3">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
        <input className="input input-icon" aria-label={t('library.search')} placeholder={t('library.search')} value={query} onChange={(e) => setQuery(e.target.value)} autoFocus />
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
      {pickingCard && (
        <div className="glass rounded-xl p-3 mb-3">
          <div className="text-sm font-medium mb-2">{t('library.pickCard', { name: pickText(pickingCard.name, i18n.language) })}</div>
          <Select value={cardConnection} onChange={setCardConnection} options={pickingCard.fits.map((one) => ({ value: String(one.id), label: one.name }))} />
          <div className="flex justify-end gap-2 mt-3">
            <button className="btn" onClick={() => setPickingCard(null)}>
              {t('common.cancel')}
            </button>
            <button className="btn btn-accent" disabled={!cardConnection || busy} onClick={() => void placeCard(pickingCard, Number(cardConnection))}>
              {t('common.add')}
            </button>
          </div>
        </div>
      )}
      {customCards.ready.length > 0 && (
        <section className="mb-4">
          <h3 className="text-[11px] uppercase tracking-wide text-faint mb-1.5">{t('library.customCards')}</h3>
          <ul className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
            {customCards.ready.map((card) => (
              <li key={card.slug}>
                <button className="w-full text-left flex items-start gap-3 p-2.5 rounded-xl border border-line hover:border-line-strong hover:bg-surface-hover transition-colors" onClick={() => chooseCard(card)} disabled={busy}>
                  <ServiceIcon icon={card.requires[0]?.icon ?? ''} size={22} className="mt-0.5" />
                  <span className="min-w-0">
                    <span className="block text-[13px] font-medium">{pickText(card.name, i18n.language)}</span>
                    <span className="block text-[11px] text-muted leading-snug">{pickText(card.description, i18n.language) || sourceLine(card)}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      {customCards.waiting.length > 0 && (
        <section className="mb-4">
          <h3 className="text-[11px] uppercase tracking-wide text-faint mb-1.5">{t('library.needIntegration')}</h3>
          <ul className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
            {customCards.waiting.map((card) => (
              <li key={card.slug} className="flex items-start gap-3 p-2.5 rounded-xl border border-line">
                <ServiceIcon icon={card.requires[0]?.icon ?? ''} size={22} className="mt-0.5" />
                <span className="min-w-0">
                  <span className="block text-[13px] font-medium">{pickText(card.name, i18n.language)}</span>
                  <span className="block text-[11px] text-muted leading-snug">{sourceLine(card)}</span>
                  {admin ? (
                    <Link to={`/system/integrations?add=${card.requires[0]?.kind ?? ''}`} className="text-[12px] text-accent">
                      {t('library.addTheIntegration')}
                    </Link>
                  ) : (
                    <span className="block text-[11px] text-faint">{t('library.askAdmin', { name: card.requires[0]?.label ?? '' })}</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {catalog.length > 0 && (
        <section className="mb-4">
          <h3 className="text-[11px] uppercase tracking-wide text-faint mb-1.5">{t('library.apps')}</h3>
          <ul className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
            {catalog.map((app) => (
              <li key={app.id}>
                <button className="w-full text-left flex items-start gap-3 p-2.5 rounded-xl border border-line hover:border-line-strong hover:bg-surface-hover transition-colors" onClick={() => void placeApp(app)} disabled={busy}>
                  <ServiceIcon icon={app.icon} size={22} className="mt-0.5" />
                  <span className="min-w-0">
                    <span className="block text-[13px] font-medium">{app.name}</span>
                    <span className="block text-[11px] text-muted leading-snug">{app.description || (app.addresses ?? []).map((one) => one.label).join(' · ')}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      {ownConnections.length > 0 && (
        <section className="mb-4" data-testid="library-own-connections">
          <h3 className="text-[11px] uppercase tracking-wide text-faint mb-1.5">{t('library.ownConnections')}</h3>
          <ul className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
            {ownConnections.map((connection) => (
              <li key={connection.id}>
                <button className="w-full text-left flex items-start gap-3 p-2.5 rounded-xl border border-line hover:border-line-strong hover:bg-surface-hover transition-colors" onClick={() => void placeConnection(connection)} disabled={busy}>
                  <ServiceIcon icon={connection.icon} size={22} className="mt-0.5" />
                  <span className="min-w-0">
                    <span className="block text-[13px] font-medium">{connection.name}</span>
                    <span className="block text-[11px] text-muted leading-snug truncate">{connection.label}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
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
