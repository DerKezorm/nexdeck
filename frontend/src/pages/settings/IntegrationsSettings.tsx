import { useQuery } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'

import { ApiError, del, get, patch, post } from '../../api/client'
import type { About, AdapterSpec, Integration } from '../../api/types'
import { FieldInput } from '../../components/FieldInput'
import { ServiceIcon } from '../../components/ServiceIcon'
import { Confirm, Field, Select, Sheet, Switch } from '../../components/ui'
import { useAuth } from '../../stores/auth'
import { SettingsCard } from './SettingsCard'

/** Configured connections, and a sheet to add or edit one with a live test. */
export function IntegrationsSettings() {
  const { t } = useTranslation()
  const user = useAuth((s) => s.user)
  const admin = user?.role === 'admin'
  const [params, setParams] = useSearchParams()
  const adapters = useQuery({ queryKey: ['adapters'], queryFn: () => get<AdapterSpec[]>('/adapters'), staleTime: 300_000 })
  const integrations = useQuery({ queryKey: ['integrations'], queryFn: () => get<Integration[]>('/integrations') })
  const about = useQuery({ queryKey: ['about'], queryFn: () => get<About>('/about') })
  const [editing, setEditing] = useState<Integration | null>(null)
  const [adding, setAdding] = useState<string | null>(params.get('add'))
  const [removing, setRemoving] = useState<Integration | null>(null)

  useEffect(() => {
    if (params.get('add')) {
      setAdding(params.get('add'))
      setParams({}, { replace: true })
    }
  }, [params, setParams])

  const byCategory = useMemo(() => {
    const groups: Record<string, AdapterSpec[]> = {}
    for (const adapter of adapters.data ?? []) {
      if (!adapter.needs_integration) continue
      ;(groups[adapter.category] ??= []).push(adapter)
    }
    return groups
  }, [adapters.data])

  return (
    <>
      {/* The switch that puts every connection at once into demo mode. It sits
          here and not on a page of its own: it says what the connections show,
          and each one carries the same switch for itself. */}
      {admin && about.data && (
        <SettingsCard title={t('settings.system.demo')}>
          <Switch
            checked={about.data.demo}
            onChange={(demo) => void patch('/settings', { demo }).then(() => about.refetch()).then(() => integrations.refetch())}
            label={t('settings.system.demo')}
            description={t('settings.system.demoHelp')}
          />
        </SettingsCard>
      )}
      <SettingsCard title={t('settings.integrations.title')} description={t('settings.integrations.help')}>
        {integrations.data?.length === 0 && <p className="text-sm text-muted mb-3">{t('settings.integrations.empty')}</p>}
        <ul className="space-y-1.5">
          {(integrations.data ?? []).map((integration) => (
            <li key={integration.id} className="flex items-center gap-3 rounded-xl border border-line p-2.5">
              <ServiceIcon icon={integration.icon} size={22} />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium truncate">
                  {integration.name}
                  {integration.demo && <span className="chip ml-2 !py-0 text-[10px]">demo</span>}
                  {integration.admin_only && (
                    <span className="chip ml-1 !py-0 text-[10px]" title={t('settings.integrations.adminOnlyHelp')}>
                      {t('settings.integrations.adminOnlyChip')}
                    </span>
                  )}
                  {integration.beta && <span className="chip ml-1 !py-0 text-[10px]">beta</span>}
                </div>
                <div className="text-[11px] text-muted truncate">
                  {integration.label} · {t('settings.integrations.widgets', { count: integration.widget_count })}
                  {integration.last_error && <span className="text-bad"> · {integration.last_error}</span>}
                </div>
              </div>
              <span className="dot" data-status={!integration.enabled ? 'unknown' : integration.last_error ? 'bad' : integration.last_ok_at || integration.demo ? 'ok' : 'unknown'} />
              {admin && (
                <>
                  <button className="btn h-7 text-xs" onClick={() => setEditing(integration)}>
                    {t('common.edit')}
                  </button>
                  <button className="btn btn-icon h-7 w-7 btn-danger" onClick={() => setRemoving(integration)} aria-label={t('common.delete')}>
                    <Trash2 size={14} />
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      </SettingsCard>
      {admin && (
        <SettingsCard title={t('settings.integrations.add')} description={t('settings.integrations.addHelp')}>
          {Object.entries(byCategory).map(([category, list]) => (
            <div key={category} className="mb-3">
              <h3 className="text-[11px] uppercase tracking-wide text-faint mb-1.5">{t(`library.category.${category}`, { defaultValue: category })}</h3>
              <div className="flex flex-wrap gap-1.5">
                {list.map((adapter) => (
                  <button key={adapter.kind} className="btn h-8 text-xs gap-1.5" onClick={() => setAdding(adapter.kind)}>
                    <ServiceIcon icon={adapter.icon} size={14} />
                    {adapter.label}
                    {adapter.beta && <span className="text-[9px] text-faint">beta</span>}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </SettingsCard>
      )}
      {(editing || adding) && adapters.data && (
        <IntegrationSheet
          adapters={adapters.data}
          integration={editing}
          kind={adding ?? editing?.kind ?? ''}
          onClose={() => {
            setEditing(null)
            setAdding(null)
          }}
          onSaved={() => {
            setEditing(null)
            setAdding(null)
            void integrations.refetch()
          }}
        />
      )}
      <Confirm
        open={removing !== null}
        title={t('settings.integrations.remove', { name: removing?.name ?? '' })}
        body={t('settings.integrations.removeBody', { count: removing?.widget_count ?? 0 })}
        danger
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          const target = removing
          setRemoving(null)
          if (target) void del(`/integrations/${target.id}`).then(() => integrations.refetch())
        }}
      />
    </>
  )
}

function IntegrationSheet({ adapters, integration, kind, onClose, onSaved }: { adapters: AdapterSpec[]; integration: Integration | null; kind: string; onClose: () => void; onSaved: () => void }) {
  const { t } = useTranslation()
  const adapter = adapters.find((a) => a.kind === kind)
  const [name, setName] = useState(integration?.name ?? adapter?.label ?? '')
  const [config, setConfig] = useState<Record<string, unknown>>(() => integration?.config ?? Object.fromEntries((adapter?.fields ?? []).filter((f) => f.default !== null && f.default !== undefined).map((f) => [f.name, f.default])))
  const [enabled, setEnabled] = useState(integration?.enabled ?? true)
  const [demo, setDemo] = useState(integration?.demo ?? false)
  const [adminOnly, setAdminOnly] = useState(integration?.admin_only ?? false)
  const [result, setResult] = useState<{ ok: boolean; message: string; hint?: string } | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  if (!adapter) return null

  const test = async () => {
    setBusy(true)
    setResult(null)
    try {
      setResult(await post<{ ok: boolean; message: string; hint?: string }>('/integrations/test', { kind: adapter.kind, config, integration_id: integration?.id ?? null }))
    } catch (failure) {
      setResult({ ok: false, message: failure instanceof ApiError ? failure.message : t('errors.network') })
    } finally {
      setBusy(false)
    }
  }
  const save = async () => {
    setBusy(true)
    setError('')
    try {
      if (integration) await patch(`/integrations/${integration.id}`, { name, config, enabled, demo, admin_only: adminOnly })
      else await post('/integrations', { kind: adapter.kind, name, config, enabled, demo, admin_only: adminOnly })
      onSaved()
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
      title={integration ? t('settings.integrations.edit', { name: integration.name }) : t('settings.integrations.new', { name: adapter.label })}
      footer={
        <>
          <button className="btn mr-auto" onClick={() => void test()} disabled={busy || demo}>
            {t('settings.integrations.test')}
          </button>
          <button className="btn" onClick={onClose}>
            {t('common.cancel')}
          </button>
          <button className="btn btn-accent" onClick={() => void save()} disabled={busy || !name.trim()}>
            {t('common.save')}
          </button>
        </>
      }
    >
      <div className="flex items-start gap-3 mb-4">
        <ServiceIcon icon={adapter.icon} size={28} />
        <div className="text-sm">
          <p className="text-muted">{adapter.description}</p>
          {adapter.beta && <p className="text-[11px] text-warn mt-1">{t('settings.integrations.betaHelp')}</p>}
          {adapter.docs_url && (
            <a className="text-[11px] text-accent" href={adapter.docs_url} target="_blank" rel="noreferrer">
              {t('settings.integrations.docs')}
            </a>
          )}
        </div>
      </div>
      <Field label={t('settings.integrations.name')} htmlFor="i-name" required>
        <input id="i-name" className="input" value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Switch checked={demo} onChange={setDemo} label={t('settings.integrations.demo')} description={t('settings.integrations.demoHelp')} />
      {/* Locked: users neither build on it nor see it in their list. What
          the administrator has built with it keeps running for them. */}
      <Switch checked={adminOnly} onChange={setAdminOnly} label={t('settings.integrations.adminOnly')} description={t('settings.integrations.adminOnlyHelp')} />
      {!demo && adapter.fields.map((field) => <FieldInput key={field.name} spec={field} value={config[field.name]} onChange={(value) => setConfig((c) => ({ ...c, [field.name]: value }))} onFill={(values) => setConfig((c) => ({ ...c, ...values }))} />)}
      <Switch checked={enabled} onChange={setEnabled} label={t('settings.integrations.enabled')} />
      {result && (
        <div className={`rounded-xl border p-3 text-sm mt-3 ${result.ok ? 'border-ok/50' : 'border-bad/50'}`} role="status">
          <span className="dot mr-2" data-status={result.ok ? 'ok' : 'bad'} />
          {result.message}
          {result.hint && <div className="text-xs text-muted mt-1">{result.hint}</div>}
        </div>
      )}
      {error && (
        <p className="text-sm text-bad mt-2" role="alert">
          {error}
        </p>
      )}
    </Sheet>
  )
}

export { Select, Plus }
