import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, del, get, patch, post, put } from '../api/client'
import type { AdapterSpec, Integration } from '../api/types'
import { tAdapter } from '../i18n/texts'
import type { WidgetData, WidgetView } from '../lib/types'
import { FieldInput } from './FieldInput'
import { IconPicker } from './IconPicker'
import { Confirm, Field, Select, Sheet, Switch } from './ui'

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

/** Everything about one widget: title, icon, link, connection, options, reachability check. */
export function WidgetSettingsSheet({ widget, pages, onClose, onSaved, onDeleted, onPreview, onPreviewData }: Props) {
  const { t } = useTranslation()
  const adapters = useQuery({ queryKey: ['adapters'], queryFn: () => get<AdapterSpec[]>('/adapters'), staleTime: 300_000 })
  const integrations = useQuery({ queryKey: ['integrations'], queryFn: () => get<Integration[]>('/integrations') })
  const [title, setTitle] = useState('')
  const [icon, setIcon] = useState('')
  const [link, setLink] = useState('')
  const [integrationId, setIntegrationId] = useState('')
  const [refresh, setRefresh] = useState('')
  const [pageId, setPageId] = useState('')
  const [options, setOptions] = useState<Record<string, unknown>>({})
  const [health, setHealth] = useState({ kind: 'http', interval_seconds: 30, enabled: true, insecure: false })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const adapterKind = widget?.kind.split('.')[0] ?? ''
  const adapter = adapters.data?.find((a) => a.kind === adapterKind)
  const spec = adapter?.widgets.find((w) => w.kind === widget?.kind)

  useEffect(() => {
    if (!widget) return
    setTitle(widget.title)
    setIcon(widget.icon)
    setLink(widget.link)
    setIntegrationId(widget.integration_id ? String(widget.integration_id) : '')
    setRefresh(widget.refresh_seconds ? String(widget.refresh_seconds) : '')
    setPageId('')
    setOptions({ ...widget.options })
    setError('')
    if (widget.health) setHealth({ kind: widget.health.kind, interval_seconds: (widget.health as { interval_seconds?: number }).interval_seconds ?? 30, enabled: true, insecure: false })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [widget?.id])
  useEffect(() => {
    if (widget) onPreview?.({ id: widget.id, title, icon, link, options })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title, icon, link, options, widget?.id])
  // Options and the connection change what the server would show: ask it for
  // a preview after a short pause, without saving anything.
  useEffect(() => {
    if (!widget) return
    const savedIntegration = widget.integration_id ? String(widget.integration_id) : ''
    const changed = JSON.stringify(options) !== JSON.stringify(widget.options) || integrationId !== savedIntegration
    if (!changed) {
      onPreviewData?.(widget.id, null)
      return
    }
    const id = window.setTimeout(() => {
      void post<WidgetData>(`/widgets/${widget.id}/preview`, {
        options,
        integration_id: integrationId ? Number(integrationId) : undefined,
        clear_integration: !integrationId && adapter?.needs_integration ? true : undefined,
      })
        .then((data) => onPreviewData?.(widget.id, data))
        .catch(() => undefined)
    }, 400)
    return () => window.clearTimeout(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options, integrationId, widget?.id])

  if (!widget) return null
  const matching = (integrations.data ?? []).filter((i) => i.kind === adapterKind)
  const isApp = widget.kind === 'core.app'

  const save = async () => {
    setBusy(true)
    setError('')
    try {
      await patch(`/widgets/${widget.id}`, {
        title,
        icon,
        link,
        integration_id: integrationId ? Number(integrationId) : undefined,
        clear_integration: !integrationId && adapter?.needs_integration ? true : undefined,
        options,
        refresh_seconds: refresh ? Number(refresh) : undefined,
        page_id: pageId ? Number(pageId) : undefined,
      })
      if (isApp && link && options.check !== false) {
        await put(`/widgets/${widget.id}/health`, { kind: health.kind, target: health.kind === 'http' ? link : (options.check_target as string) || link, interval_seconds: health.interval_seconds, enabled: true, insecure: health.insecure })
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
      <Field label={t('widget.title')} htmlFor="w-title">
        <input id="w-title" className="input" value={title} onChange={(e) => setTitle(e.target.value)} />
      </Field>
      <IconPicker value={icon} onChange={setIcon} label={t('widget.icon')} />
      <Field label={t('widget.link')} htmlFor="w-link" help={t('widget.linkHelp')}>
        <input id="w-link" className="input" type="url" value={link} placeholder="https://" onChange={(e) => setLink(e.target.value)} />
      </Field>
      {adapter?.needs_integration && (
        <Field label={t('widget.integration')} htmlFor="w-int">
          <Select id="w-int" value={integrationId} onChange={setIntegrationId} options={[{ value: '', label: t('widget.noIntegration') }, ...matching.map((i) => ({ value: String(i.id), label: i.name }))]} />
        </Field>
      )}
      {spec?.options.map((option) => (
        <FieldInput key={option.name} spec={option} value={options[option.name]} onChange={(value) => setOptions((o) => ({ ...o, [option.name]: value }))} />
      ))}
      {/* Cards with server data can hand their alarm to a Findings card next to them. */}
      {!spec?.client_only && (
        <Switch checked={options.show_findings !== false} onChange={(value) => setOptions((o) => ({ ...o, show_findings: value }))} label={t('widget.showFindings')} description={t('widget.showFindingsHelp')} />
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
