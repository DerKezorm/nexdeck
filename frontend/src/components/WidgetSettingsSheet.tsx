import { useQuery } from '@tanstack/react-query'
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, del, get, patch, post, put } from '../api/client'
import type { AdapterSpec, AppEntry, Integration } from '../api/types'
import { tAdapter } from '../i18n/texts'
import { shownField } from '../lib/fields'
import { inFigures, TILE_LINES } from '../lib/figures'
import { useEditedPage } from '../lib/groups'
import type { WidgetData, WidgetView } from '../lib/types'
import { useAuth } from '../stores/auth'
import { CardLookFields } from './CardLookFields'
import { FieldInput } from './FieldInput'
import { IconPicker } from './IconPicker'
import { Confirm, Field, Select, Sheet, Switch } from './ui'

const DependsOn = lazy(() => import('./inventory/DependsOn').then((module) => ({ default: module.DependsOn })))

export interface WidgetDraft {
  id: number
  title: string
  icon: string
  link: string
  options: Record<string, unknown>
}

interface Props {
  widget: WidgetView | null
  pages: { id: number; name: string }[]
  onClose: () => void
  onSaved: () => void
  onDeleted: () => void
  /** Shows title, icon, link and options on the card while they are being edited. */
  onPreview?: (draft: WidgetDraft | null) => void
  /** Data the server fetched with the draft options; null returns the card to its live data. */
  onPreviewData?: (widgetId: number, data: WidgetData | null) => void
}

/** The same empty list every time, so an effect that reads the catalog does not run on every render. */
const NO_APPS: AppEntry[] = []

/** A check as a card without one starts it. */
const FRESH_CHECK = { kind: 'http', interval_seconds: 30, timeout_seconds: 5, expect_status: 0, insecure: false }

/** Everything about one widget: title, icon, link, connection, options, reachability check. */
export function WidgetSettingsSheet({ widget, pages, onClose, onSaved, onDeleted, onPreview, onPreviewData }: Props) {
  const { t } = useTranslation()
  const adapters = useQuery({ queryKey: ['adapters'], queryFn: () => get<AdapterSpec[]>('/adapters'), staleTime: 300_000 })
  const integrations = useQuery({ queryKey: ['integrations'], queryFn: () => get<Integration[]>('/integrations') })
  const admin = useAuth((s) => s.user?.role === 'admin')
  // The catalog only matters to an app tile; a guest edits nothing and is not asked.
  const appTile = widget?.kind === 'core.app'
  const apps = useQuery({ queryKey: ['apps'], queryFn: () => get<AppEntry[]>('/apps'), enabled: appTile, staleTime: 60_000 })
  // A list or nothing: an answer of another shape must not take the whole sheet down.
  const catalog = Array.isArray(apps.data) ? apps.data : NO_APPS
  // A tile of key figures offers the lines that colour it, whatever its view.
  const tile = useEditedPage((state) => inFigures(widget?.id, state.widgets))
  const [title, setTitle] = useState('')
  const [icon, setIcon] = useState('')
  const [link, setLink] = useState('')
  const [integrationId, setIntegrationId] = useState('')
  const [refresh, setRefresh] = useState('')
  const [pageId, setPageId] = useState('')
  const [options, setOptions] = useState<Record<string, unknown>>({})
  const [health, setHealth] = useState(FRESH_CHECK)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  /** The last answer from the server, kept so a row picker knows the rows. */
  const [preview, setPreview] = useState<WidgetData | null>(null)
  /** Which preview question is the newest; older answers are dropped. */
  const asked = useRef(0)

  const adapterKind = widget?.kind.split('.')[0] ?? ''
  const adapter = adapters.data?.find((a) => a.kind === adapterKind)
  const spec = adapter?.widgets.find((w) => w.kind === widget?.kind)

  useEffect(() => {
    if (!widget) return
    // ⚠️ The answer belonged to the card that was open before. Left standing,
    // the row picker of the next card lists the wrong rows, or none.
    setPreview(null)
    // ⚠️ The tile's own name and icon, not the app's it shows: saving the
    // shown name back would pin it to the tile, which would stop following a
    // rename of the app.
    setTitle(widget.own_title ?? widget.title)
    setIcon(widget.own_icon ?? widget.icon)
    setLink(widget.link)
    setIntegrationId(widget.integration_id ? String(widget.integration_id) : '')
    setRefresh(widget.refresh_seconds ? String(widget.refresh_seconds) : '')
    setPageId('')
    setOptions({ ...widget.options })
    setError('')
    // ⚠️ Everything, not two of them. The sheet used to read the kind and the
    // interval and hard-code the rest, while the server assigns every field
    // without condition: renaming an app card put the TLS box back to off, the
    // timeout back to five seconds and the expected status back to any, and
    // two minutes later every administrator got an outage notice about a
    // service that had been fine all along. Everything but `enabled`, which
    // the switch below decides (see save).
    if (widget.health) {
      const check = widget.health
      setHealth({
        kind: check.kind,
        interval_seconds: check.interval_seconds ?? 30,
        timeout_seconds: check.timeout_seconds ?? 5,
        expect_status: check.expect_status ?? 0,
        insecure: check.insecure ?? false,
      })
    } else {
      // ⚠️ The sheet stays mounted between cards. Without this a card with no
      // check yet took over the check of the card opened before it: its kind,
      // its interval, its TLS box, and in issue #17 its switched-off flag.
      setHealth(FRESH_CHECK)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [widget?.id])
  useEffect(() => {
    if (!widget) return
    // A tile that follows an app shows the app's name and icon while its own
    // are empty, in the preview as on the board; an empty draft drew a blank card.
    const app = widget.kind === 'core.app' ? catalog.find((one) => one.id === Number(options.app_id)) : undefined
    onPreview?.({ id: widget.id, title: title || (app?.name ?? ''), icon: icon || (app?.icon ?? ''), link, options })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title, icon, link, options, widget?.id, catalog])
  // Options and the connection change what the server would show: ask it for
  // a preview after a short pause, without saving anything.
  useEffect(() => {
    if (!widget) return
    const savedIntegration = widget.integration_id ? String(widget.integration_id) : ''
    const changed = JSON.stringify(options) !== JSON.stringify(widget.options) || integrationId !== savedIntegration
    // ⚠️ One fetch on opening even when nothing changed, but only where a
    // field needs to list the card's own rows: without it the picker would be
    // empty until the first edit, which is the one moment nobody edits.
    const needsRows = !changed && preview === null && (spec?.options ?? []).some((option) => option.type === 'items')
    if (!changed && !needsRows) {
      onPreviewData?.(widget.id, null)
      return
    }
    // ⚠️ Numbered, because clearing the timeout does not call back a request
    // that is already out. Two changes in quick succession put two questions
    // on the wire, and the older answer could land last and paint the card
    // with the options before the one just made: the change appeared not to
    // arrive at all, which is how it was reported.
    const mine = (asked.current += 1)
    const id = window.setTimeout(() => {
      void post<WidgetData>(`/widgets/${widget.id}/preview`, {
        options,
        integration_id: integrationId ? Number(integrationId) : undefined,
        clear_integration: !integrationId && (adapter?.needs_integration || adapter?.optional_integration) ? true : undefined,
      })
        .then((data) => {
          if (mine !== asked.current) return
          setPreview(data)
          // A fetch made only to fill the picker must not repaint the card.
          if (changed) onPreviewData?.(widget.id, data)
        })
        // ⚠️ A failed preview leaves the card on what it had. It is not
        // silence out of laziness: the alternative is dropping the card back
        // to the collector's answer mid-edit, which is the flicker this whole
        // area is about. The failure is not invented away either, because the
        // save that follows would fail just as loudly.
        .catch(() => undefined)
    }, changed ? 400 : 0)
    return () => window.clearTimeout(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options, integrationId, widget?.id, spec?.kind])

  if (!widget) return null
  const isApp = widget.kind === 'core.app'
  // A service widget needs an integration of its own kind; an app tile may follow any service.
  const matching = (integrations.data ?? []).filter((i) => isApp || i.kind === adapterKind)
  const followed = isApp ? matching.find((i) => String(i.id) === integrationId) : undefined
  const followedUrl = typeof followed?.config?.url === 'string' ? followed.config.url : ''
  const chooseIntegration = (value: string) => {
    setIntegrationId(value)
    const chosen = matching.find((i) => String(i.id) === value)
    if (!isApp || !chosen) return
    // Name and icon are suggestions, filled only while the tile still carries the defaults.
    if (!title.trim() || title === spec?.label || title === tAdapter(spec?.label)) setTitle(chosen.name)
    if (!icon) setIcon(chosen.icon)
  }

  const followedApp = isApp ? catalog.find((app) => app.id === Number(options.app_id)) : undefined
  /** Follow an app of the catalog, or stop following one. */
  const chooseApp = (value: string) => {
    const app = catalog.find((one) => String(one.id) === value)
    if (!app) {
      // Stopping keeps what the tile showed, so it does not go blank.
      const was = followedApp
      setOptions(({ app_id: _id, address: _address, ...rest }) => rest)
      if (was) {
        if (!title.trim()) setTitle(was.name)
        if (!icon) setIcon(was.icon)
        if (!link) setLink(widget.service_link || was.addresses[0]?.url || '')
      }
      return
    }
    // The app gives name, icon and address; the tile's own would win over it.
    setOptions((o) => ({ ...o, app_id: app.id, address: app.home || app.away ? 'auto' : '' }))
    setTitle('')
    setIcon('')
    setLink('')
    setIntegrationId('')
  }
  /** Put this tile into the catalog and let it follow its new app. */
  const saveAsApp = async () => {
    setError('')
    try {
      const made = await post<AppEntry>('/apps', {
        name: title.trim() || t('widget.app.untitled'),
        icon,
        description: String(options.description ?? '').trim(),
        addresses: [{ label: t('widget.app.firstLabel'), url: link.trim() }],
      })
      await apps.refetch()
      setOptions((o) => ({ ...o, app_id: made.id, address: '' }))
      setTitle('')
      setIcon('')
      setLink('')
      setIntegrationId('')
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : t('errors.network'))
    }
  }

  const save = async () => {
    setBusy(true)
    setError('')
    try {
      await patch(`/widgets/${widget.id}`, {
        title,
        icon,
        link,
        integration_id: integrationId ? Number(integrationId) : undefined,
        clear_integration: !integrationId && (adapter?.needs_integration || adapter?.optional_integration || isApp) ? true : undefined,
        options,
        refresh_seconds: refresh ? Number(refresh) : undefined,
        // An emptied field means "back to the card's own interval", and that
        // needs saying: leaving it out means "unchanged".
        clear_refresh: refresh ? undefined : true,
        page_id: pageId ? Number(pageId) : undefined,
      })
      if (isApp && (link || integrationId || options.app_id) && options.check !== false) {
        // An empty target follows the app's or the integration's address on the server, at every check.
        await put(`/widgets/${widget.id}/health`, {
          kind: health.kind,
          target: health.kind === 'http' ? link : (options.check_target as string) || link,
          interval_seconds: health.interval_seconds,
          timeout_seconds: health.timeout_seconds,
          expect_status: health.expect_status,
          // ⚠️ On, because the switch that says so is on. This used to send
          // back whatever the check had, and nothing in the sheet shows that
          // flag: a demo tile's check starts switched off, and a tile edited
          // into a real service stayed grey through every save. Issue #17.
          enabled: true,
          insecure: health.insecure,
        })
      }
      onSaved()
      onClose()
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : t('errors.network'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Sheet
      open
      onClose={onClose}
      title={t('widget.settings')}
      footer={
        <>
          <button className="btn btn-danger mr-auto" onClick={() => setConfirmDelete(true)}>
            {t('common.delete')}
          </button>
          <button className="btn" onClick={onClose}>
            {t('common.cancel')}
          </button>
          <button className="btn btn-accent" onClick={() => void save()} disabled={busy}>
            {t('common.save')}
          </button>
        </>
      }
    >
      <p className="text-xs text-muted mb-1">
        {adapter?.label} · {tAdapter(spec?.label)}
        {adapter?.beta && (
          <span className="chip ml-1.5 !py-0 text-[10px] cursor-help" title={t('widget.betaHelp')}>
            beta
          </span>
        )}
      </p>
      <p className="text-[11px] text-faint mb-3">{t('widget.previewHint')}</p>
      {/* Errors stand at the top, where a long sheet still shows them. */}
      {error && (
        <p className="text-sm text-bad mb-3 rounded-lg border border-bad/40 px-3 py-2" role="alert">
          {error}
        </p>
      )}
      {isApp && (
        <div className="rounded-xl border border-line p-3 mb-3">
          <Field label={t('widget.app.label')} htmlFor="w-app" help={t('widget.app.help')}>
            <Select
              id="w-app"
              value={followedApp ? String(followedApp.id) : ''}
              onChange={chooseApp}
              options={[{ value: '', label: t('widget.app.none') }, ...catalog.map((app) => ({ value: String(app.id), label: app.name }))]}
            />
          </Field>
          {followedApp && (
            <Field label={t('widget.app.address')} htmlFor="w-app-address" help={followedApp.home || followedApp.away ? t('widget.app.autoHelp') : undefined}>
              <Select
                id="w-app-address"
                value={String(options.address ?? '')}
                onChange={(address) => setOptions((o) => ({ ...o, address }))}
                options={[
                  ...(followedApp.home || followedApp.away ? [{ value: 'auto', label: t('widget.app.auto') }] : [{ value: '', label: t('widget.app.first', { label: followedApp.addresses[0]?.label ?? '' }) }]),
                  ...followedApp.addresses.map((one) => ({ value: one.label, label: `${one.label} · ${one.url}` })),
                ]}
              />
            </Field>
          )}
          {!followedApp && admin && link.trim() && (
            <button className="btn h-8 text-xs" onClick={() => void saveAsApp()} title={t('widget.app.saveAsHelp')}>
              {t('widget.app.saveAs')}
            </button>
          )}
        </div>
      )}
      <Field label={t('widget.title')} htmlFor="w-title" help={followedApp ? t('widget.app.titleHelp') : undefined}>
        <input id="w-title" className="input" value={title} placeholder={followedApp?.name} onChange={(e) => setTitle(e.target.value)} />
      </Field>
      <IconPicker value={icon} onChange={setIcon} label={t('widget.icon')} />
      <Field label={t('widget.link')} htmlFor="w-link" help={followedApp ? t('widget.app.linkFollows') : followed ? t('widget.linkFollows') : t('widget.linkHelp')}>
        <input id="w-link" className="input" type="url" value={link} placeholder={(followedApp && widget.app?.id === followedApp.id ? widget.service_link : '') || followedUrl || 'https://'} onChange={(e) => setLink(e.target.value)} />
      </Field>
      {(adapter?.needs_integration || adapter?.optional_integration || (isApp && !followedApp)) && (
        <Field label={isApp || adapter?.optional_integration ? t('widget.integrationOptional') : t('widget.integration')} htmlFor="w-int" help={isApp ? t('widget.integrationFollowHelp') : undefined}>
          <Select id="w-int" value={integrationId} onChange={chooseIntegration} options={[{ value: '', label: t('widget.noIntegration') }, ...matching.map((i) => ({ value: String(i.id), label: i.name }))]} />
        </Field>
      )}
      {/* ⚠️ An option that does nothing is not on screen. The volume card in
          its dial view offered "usage bar" and "percentage", which describe a
          row of a list, and a dial has no rows: three switches that moved and
          changed nothing. */}
      {spec?.options
        .filter((option) => {
          // ⚠️ The app tile's own box below has this switch, with the kind of
          // check under it. From the list it was a second switch of the same
          // name for the same option, one screen apart. Seen in issue #17.
          if (isApp && option.name === 'check') return false
          // A tile of key figures draws the number whatever the view, coloured by these lines.
          if (tile && TILE_LINES.has(option.name)) return true
          return shownField(option, spec.options, options)
        })
        .map((option) => (
          <FieldInput
            key={option.name}
            spec={option}
            value={options[option.name]}
            items={preview?.items as Record<string, unknown>[] | undefined}
            allTitles={preview?.meta?.all_items as string[] | undefined}
            /* ⚠️ A choices field usually asks the card's own connection. The
               button card asks a connection named in a sibling option, so the
               sheet hands both down and the field picks. */
            integrationId={
              option.from_field
                ? Number(options[option.from_field] ?? 0) || undefined
                : integrationId ? Number(integrationId) : undefined
            }
            onChange={(value) => setOptions((o) => ({ ...o, [option.name]: value }))}
          />
        ))}
      {/* Cards with server data can hand their alarm to a Findings card next to them. */}
      {!spec?.client_only && (
        <Switch checked={options.show_findings === true} onChange={(value) => setOptions((o) => ({ ...o, show_findings: value }))} label={t('widget.showFindings')} description={t('widget.showFindingsHelp')} />
      )}
      {/* A heading has a colour of its kind; every other card its look here. */}
      {widget.kind !== 'core.heading' && (
        <CardLookFields
          options={options}
          icon={icon || widget.icon}
          onChange={(patch) => setOptions((o) => ({ ...o, ...patch }))}
        />
      )}
      {isApp && admin && widget.id > 0 && (
        // Roadmap M5: what this tile's app runs on. Loaded with its words only when an administrator opens a tile.
        <Suspense fallback={null}>
          <DependsOn subject={`tile:${widget.id}`} />
        </Suspense>
      )}
      {isApp && (
        <div className="rounded-xl border border-line p-3 mb-3">
          <Switch checked={options.check !== false} onChange={(value) => setOptions((o) => ({ ...o, check: value }))} label={t('widget.health.enable')} description={t('widget.health.help')} />
          {options.check !== false && (
            <div className="grid grid-cols-2 gap-2 mt-2">
              <Field label={t('widget.health.kind')} htmlFor="w-health-kind" help={t('widget.health.kindHelp')}>
                <Select id="w-health-kind" value={health.kind} onChange={(kind) => setHealth((h) => ({ ...h, kind }))} options={[{ value: 'http', label: 'HTTP' }, { value: 'tcp', label: 'TCP' }, { value: 'ping', label: 'Ping' }]} />
              </Field>
              <Field label={t('widget.health.interval')} htmlFor="w-health-interval">
                <input id="w-health-interval" className="input" type="number" min={5} value={health.interval_seconds} onChange={(e) => setHealth((h) => ({ ...h, interval_seconds: Number(e.target.value) || 30 }))} />
              </Field>
              {health.kind !== 'http' && (
                <div className="col-span-2">
                  <Field label={t('widget.health.target')} htmlFor="w-health-target" help={health.kind === 'tcp' ? 'host:port' : 'host'}>
                    <input id="w-health-target" className="input" value={String(options.check_target ?? '')} onChange={(e) => setOptions((o) => ({ ...o, check_target: e.target.value }))} />
                  </Field>
                </div>
              )}
              <div className="col-span-2">
                <Switch checked={health.insecure} onChange={(insecure) => setHealth((h) => ({ ...h, insecure }))} label={t('widget.health.insecure')} />
              </div>
            </div>
          )}
        </div>
      )}
      <div className="grid grid-cols-2 gap-2">
        {/* A clock or a note draws itself; the server has nothing to refresh for it. */}
        {!spec?.client_only && (
          <Field label={t('widget.refresh')} htmlFor="w-refresh" help={t('widget.refreshHelp', { seconds: spec?.refresh_seconds ?? 30 })}>
            <input id="w-refresh" className="input" type="number" min={5} value={refresh} placeholder={String(spec?.refresh_seconds ?? 30)} onChange={(e) => setRefresh(e.target.value)} />
          </Field>
        )}
        {/* Moving between pages only makes sense once the board has more than one. */}
        {pages.length > 1 && (
          <Field label={t('widget.page')} htmlFor="w-page" help={t('widget.pageHelp')}>
            <Select id="w-page" value={pageId} onChange={setPageId} options={[{ value: '', label: t('widget.keepPage') }, ...pages.map((p) => ({ value: String(p.id), label: p.name }))]} />
          </Field>
        )}
      </div>
      <Confirm
        open={confirmDelete}
        title={t('widget.remove.title')}
        body={t('widget.remove.body')}
        danger
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => {
          setConfirmDelete(false)
          del(`/widgets/${widget.id}`)
            .then(onDeleted)
            .catch((failure) => setError(failure instanceof ApiError ? failure.message : t('errors.network')))
        }}
      />
    </Sheet>
  )
}
