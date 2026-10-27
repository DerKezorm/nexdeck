import { useQuery, useQueryClient } from '@tanstack/react-query'
import { FlaskConical, Plus } from 'lucide-react'
import { lazy, Suspense, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { ApiError, del, get, patch, post } from '../../api/client'
import type { About, AdapterSpec, Integration } from '../../api/types'
import { FieldInput } from '../../components/FieldInput'
import { ServiceIcon } from '../../components/ServiceIcon'
import { LeaveDemo } from '../../components/LeaveDemo'
import { Confirm, Field, Sheet, Switch, Toast, Toggle } from '../../components/ui'
import { tAdapter } from '../../i18n/texts'
import { shownField } from '../../lib/fields'
import { useHomeBoardPath } from '../../lib/homeBoard'
import { useAuth } from '../../stores/auth'

const DependsOn = lazy(() => import('../../components/inventory/DependsOn').then((module) => ({ default: module.DependsOn })))
// The catalog is a window of its own and only comes when it is opened.
const CatalogDialog = lazy(() => import('./integrations/CatalogDialog'))
import { OwnList } from './integrations/OwnList'
import type { VersionReading } from './integrations/own'
import { SettingsCard } from './SettingsCard'

/**
 * Demo mode for everything: a slim line while it is off, the full box while it is on.
 *
 * Off, it is one switch nobody needs most days, and the box pushed the
 * connections below the fold. On, or with invented connections left behind,
 * it says so and offers the way out.
 */
function DemoMode({ about, onChange }: { about: About; onChange: (demo: boolean) => void }) {
  const { t } = useTranslation()
  if (!about.demo && !about.demo_data && !about.demo_forced) {
    return (
      <div className="glass rounded-[14px] flex items-center gap-2.5 pl-3.5 pr-3 py-2.5 mb-3 text-[13px]">
        <FlaskConical size={15} className="text-faint flex-none" />
        <span className="font-medium whitespace-nowrap">{t('settings.integrations.demoRow.title')}</span>
        <span className="text-faint text-[12.5px] truncate min-w-0 flex-1 max-md:hidden">{t('settings.integrations.demoRow.off')}</span>
        <span className="ml-auto" />
        <Toggle checked={false} onChange={onChange} label={t('settings.system.demo')} />
      </div>
    )
  }
  return (
    <div className="glass rounded-2xl p-5 mb-4 border-warn/40 bg-[color-mix(in_srgb,var(--nd-warn)_6%,var(--nd-surface))]">
      <h2 className="font-semibold text-[15px] mb-1">{t('settings.integrations.demoRow.title')}</h2>
      <Switch checked={about.demo} disabled={about.demo_forced} onChange={onChange} label={t('settings.system.demo')} description={about.demo_forced ? t('settings.system.demoForced') : t('settings.system.demoHelp')} />
      {/* The switch alone leaves the demo's own connections inventing
          data; this takes them away, after saying what goes. */}
      {!about.demo_forced && (about.demo || about.demo_data) && (
        <div className="mt-3.5 pt-3.5 border-t border-line flex flex-wrap items-center gap-3 text-[12.5px] text-muted">
          <span className="flex-[1_1_200px]">{t('settings.integrations.demoRow.left')}</span>
          <LeaveDemo className="btn btn-xs" />
        </div>
      )}
    </div>
  )
}

/** Configured connections, and a sheet to add or edit one with a live test. */
export function IntegrationsSettings() {
  const { t } = useTranslation()
  const user = useAuth((s) => s.user)
  const admin = user?.role === 'admin'
  const [params, setParams] = useSearchParams()
  const adapters = useQuery({ queryKey: ['adapters'], queryFn: () => get<AdapterSpec[]>('/adapters'), staleTime: 300_000 })
  const integrations = useQuery({ queryKey: ['integrations'], queryFn: () => get<Integration[]>('/integrations') })
  const about = useQuery({ queryKey: ['about'], queryFn: () => get<About>('/about') })
  // Read every six hours on the server; the first look after a start asks every service once and may take a moment.
  const versions = useQuery({ queryKey: ['integration-versions'], queryFn: () => get<Record<string, VersionReading>>('/integrations/versions'), enabled: admin, staleTime: 600_000 })
  const [editing, setEditing] = useState<Integration | null>(null)
  const [adding, setAdding] = useState<string | null>(params.get('add'))
  const [removing, setRemoving] = useState<Integration | null>(null)
  // The catalog window, with the words it opens with; null while it is closed.
  const [catalog, setCatalog] = useState<string | null>(null)
  // What a new connection starts with besides its defaults: the address of a service found in the network.
  const [prefill, setPrefill] = useState<Record<string, unknown> | null>(null)
  const [bellFailed, setBellFailed] = useState('')
  const navigate = useNavigate()
  const home = useHomeBoardPath()
  const queries = useQueryClient()

  /** The bell of one connection, flipped where it stands. Nothing to open, nothing to save. */
  const toggleBell = async (integration: Integration) => {
    setBellFailed('')
    try {
      await patch(`/integrations/${integration.id}`, { muted: !integration.muted })
      await integrations.refetch()
    } catch (failure) {
      setBellFailed(failure instanceof ApiError ? failure.message : t('settings.integrations.bellFailed'))
    }
  }

  useEffect(() => {
    if (params.get('add')) {
      setAdding(params.get('add'))
      setParams({}, { replace: true })
    }
  }, [params, setParams])

  return (
    <>
      {/* The switch that puts every connection at once into demo mode. It sits
          here and not on a page of its own: it says what the connections show,
          and each one carries the same switch for itself. */}
      {admin && about.data && <DemoMode about={about.data} onChange={(demo) => void patch('/settings', { demo }).then(() => about.refetch()).then(() => integrations.refetch())} />}
      <SettingsCard
        title={t('settings.integrations.title')}
        description={t('settings.integrations.help')}
        action={
          admin && (
            <button type="button" className="btn btn-accent" onClick={() => setCatalog('')}>
              <Plus size={15} />
              {t('settings.integrations.add')}
            </button>
          )
        }
      >
        {integrations.data && adapters.data && (
          <OwnList
            integrations={integrations.data}
            adapters={adapters.data}
            versions={versions.data}
            versionsLoading={versions.isLoading}
            admin={admin}
            onBell={(integration) => void toggleBell(integration)}
            onEdit={setEditing}
            onRemove={setRemoving}
            // The way a card is always made: the library of a board, already searching for this service.
            onBuildCard={(integration) => navigate(home, { state: { library: integration.label } })}
            onSearchCatalog={admin ? setCatalog : undefined}
          />
        )}
        {bellFailed && (
          <Toast level="error" onClose={() => setBellFailed('')}>
            {bellFailed}
          </Toast>
        )}
      </SettingsCard>
      {catalog !== null && adapters.data && integrations.data && (
        <Suspense fallback={null}>
          <CatalogDialog
            adapters={adapters.data}
            integrations={integrations.data}
            initialQuery={catalog}
            onClose={() => setCatalog(null)}
            onPick={(kind) => {
              setCatalog(null)
              setPrefill(null)
              setAdding(kind)
            }}
            onConnect={(kind, address) => {
              setCatalog(null)
              setPrefill(address ? { url: address } : null)
              setAdding(kind)
            }}
          />
        </Suspense>
      )}
      {(editing || adding) && adapters.data && (
        <IntegrationSheet
          adapters={adapters.data}
          integration={editing}
          kind={adding ?? editing?.kind ?? ''}
          prefill={editing ? null : prefill}
          onClose={() => {
            setEditing(null)
            setAdding(null)
            setPrefill(null)
          }}
          onSaved={() => {
            setEditing(null)
            setAdding(null)
            setPrefill(null)
            void integrations.refetch()
            // A service connected from what was found is no longer one to suggest.
            void queries.invalidateQueries({ queryKey: ['integrations-found'] })
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

function IntegrationSheet({ adapters, integration, kind, prefill, onClose, onSaved }: { adapters: AdapterSpec[]; integration: Integration | null; kind: string; prefill?: Record<string, unknown> | null; onClose: () => void; onSaved: () => void }) {
  const admin = useAuth((s) => s.user?.role === 'admin')
  const { t } = useTranslation()
  const adapter = adapters.find((a) => a.kind === kind)
  const [name, setName] = useState(integration?.name ?? adapter?.label ?? '')
  const [config, setConfig] = useState<Record<string, unknown>>(
    () => integration?.config ?? { ...Object.fromEntries((adapter?.fields ?? []).filter((f) => f.default !== null && f.default !== undefined).map((f) => [f.name, f.default])), ...(prefill ?? {}) },
  )
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
          <p className="text-muted">{tAdapter(adapter.description)}</p>
          {adapter.beta && <p className="text-[11px] text-warn mt-1">{t('settings.integrations.betaHelp')}</p>}
          {adapter.docs_url && (
            <a className="text-[11px] text-accent" href={adapter.docs_url} target="_blank" rel="noreferrer">
              {t('settings.integrations.docs')}
            </a>
          )}
        </div>
      </div>
      {/* Open for a new connection, where it is needed; folded away once
          the connection exists and somebody only comes back to change it. */}
      {adapter.guide && adapter.guide.length > 0 && (
        <details className="rounded-xl border border-line p-3 mb-4 text-sm" open={!integration}>
          <summary className="cursor-pointer font-medium">{t('settings.integrations.guide')}</summary>
          <ol className="list-decimal pl-5 mt-2 flex flex-col gap-1 text-muted">
            {adapter.guide.map((step) => (
              <li key={step}>{tAdapter(step)}</li>
            ))}
          </ol>
        </details>
      )}
      <Field label={t('settings.integrations.name')} htmlFor="i-name" required>
        <input id="i-name" className="input" value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Switch checked={demo} onChange={setDemo} label={t('settings.integrations.demo')} description={t('settings.integrations.demoHelp')} />
      {/* Locked: users neither build on it nor see it in their list. What
          the administrator has built with it keeps running for them. */}
      <Switch checked={adminOnly} onChange={setAdminOnly} label={t('settings.integrations.adminOnly')} description={t('settings.integrations.adminOnlyHelp')} />
      {/* ⚠️ A field that belongs to the other choice is not on screen: a
          community next to an SNMPv3 user reads as "fill in both". */}
      {!demo && adapter.fields.filter((field) => shownField(field, adapter.fields, config)).map((field) => <FieldInput key={field.name} spec={field} value={config[field.name]} onChange={(value) => setConfig((c) => ({ ...c, [field.name]: value }))} onFill={(values) => setConfig((c) => ({ ...c, ...values }))} values={config} />)}
      <Switch checked={enabled} onChange={setEnabled} label={t('settings.integrations.enabled')} />
      {result && (
        // ⚠️ Passed with a hint is yellow, not green: the hint says the cards
        // will not show what the test just found (demo mode, issue #2).
        <div className={`rounded-xl border p-3 text-sm mt-3 ${!result.ok ? 'border-bad/50' : result.hint ? 'border-warn/50' : 'border-ok/50'}`} role="status">
          <span className="dot mr-2" data-status={!result.ok ? 'bad' : result.hint ? 'warn' : 'ok'} />
          {result.message}
          {result.hint && <div className="text-xs text-muted mt-1">{result.hint}</div>}
        </div>
      )}
      {error && (
        <p className="text-sm text-bad mt-2" role="alert">
          {error}
        </p>
      )}
      {/* Roadmap M5: what this connection runs on; only once it exists. */}
      {integration && admin && (
        <div className="mt-4">
          <Suspense fallback={null}>
            <DependsOn subject={`integration:${integration.id}`} />
          </Suspense>
        </div>
      )}
    </Sheet>
  )
}

