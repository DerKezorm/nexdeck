import { useQuery } from '@tanstack/react-query'
import { Download, Pencil, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, del, get, patch, post, serverUrl } from '../../api/client'
import type { About } from '../../api/types'
import { Confirm, Field, Select, Switch, Toast } from '../../components/ui'
import { SettingsCard } from './SettingsCard'

interface Provider {
  id: number
  slug: string
  label: string
  issuer_url: string
  client_id: string
  has_secret: boolean
  scopes: string
  enabled: boolean
  auto_create: boolean
  trusts_second_factor: boolean
  default_role: string
  /** Accounts linked to it; they lose the link when the issuer changes. */
  links: number
}

// A new provider hands out no accounts unless the operator says so.
const EMPTY = { slug: '', label: '', issuer_url: '', client_id: '', client_secret: '', scopes: 'openid profile email', enabled: true, auto_create: false, trusts_second_factor: false, default_role: 'user' }

/** One issuer written two ways: spaces around it and the slash at the end do not count. Same rule as the server. */
function sameIssuer(a: string, b: string): boolean {
  const normal = (issuer: string) => issuer.trim().replace(/\/+$/, '')
  return normal(a) === normal(b)
}

interface Steps {
  ok: boolean
  steps: { key: string; ok: boolean; detail: string }[]
}

/** Sign-in through authentik, Keycloak, Authelia, Pocket ID and the rest. */
export function OidcSettings() {
  const { t } = useTranslation()
  const providers = useQuery({ queryKey: ['oidc-providers'], queryFn: () => get<Provider[]>('/oidc/providers') })
  const about = useQuery({ queryKey: ['about'], queryFn: () => get<About>('/about') })
  const [form, setForm] = useState(EMPTY)
  // The provider the form is changing; null while it adds a new one. Until
  // 0.18.1 there was no way to change one at all, only to delete it and add
  // it again (issue #10), which loses every account linked to it.
  const [editing, setEditing] = useState<Provider | null>(null)
  const [toast, setToast] = useState<{ text: string; level: 'ok' | 'error' } | null>(null)
  const [authentik, setAuthentik] = useState({ url: '', token: '' })
  const [steps, setSteps] = useState<Steps | null>(null)
  const [busy, setBusy] = useState(false)
  // How many accounts lose their link if the issuer changes; null while nobody is asked.
  const [dropping, setDropping] = useState<number | null>(null)
  const fail = (failure: unknown) => setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' })
  const base = about.data?.public_url || window.location.origin
  const edit = (provider: Provider) => {
    // The secret never comes back from the server; left empty, it is kept.
    const { slug, label, issuer_url, client_id, scopes, enabled, auto_create, trusts_second_factor, default_role } = provider
    setForm({ slug, label, issuer_url, client_id, client_secret: '', scopes, enabled, auto_create, trusts_second_factor, default_role })
    setEditing(provider)
    requestAnimationFrame(() => document.getElementById('o-slug')?.focus())
  }
  const reset = () => {
    setForm(EMPTY)
    setEditing(null)
  }
  const store = () =>
    void (editing ? patch(`/oidc/providers/${editing.id}`, form) : post('/oidc/providers', form))
      .then(() => {
        if (editing) setToast({ text: t('common.saved'), level: 'ok' })
        reset()
        void providers.refetch()
      })
      .catch(fail)
  const save = () => {
    if (!editing || sameIssuer(editing.issuer_url, form.issuer_url)) return store()
    // Another issuer is another provider, and the server drops every link to
    // this one. The number comes fresh from the server, not from the list.
    void get<Provider>(`/oidc/providers/${editing.id}`)
      .then((current) => (current.links > 0 ? setDropping(current.links) : store()))
      .catch(fail)
  }
  const runAuthentik = () => {
    setBusy(true)
    setSteps(null)
    void post<Steps>('/oidc/authentik/setup', authentik)
      .then((result) => {
        setSteps(result)
        // The token was for this run only; it does not stay in the page either.
        setAuthentik((a) => ({ ...a, token: '' }))
        void providers.refetch()
      })
      .catch(fail)
      .finally(() => setBusy(false))
  }
  const noAddress = about.isSuccess && !about.data?.public_url
  return (
    <>
      <SettingsCard title={t('settings.system.authentik')} description={t('settings.system.authentikHelp')}>
        {noAddress && <p className="text-[12px] text-warn mb-2">{t('settings.system.authentikNoAddress')}</p>}
        <form
          className="grid sm:grid-cols-2 gap-3"
          onSubmit={(event) => {
            event.preventDefault()
            runAuthentik()
          }}
        >
          <Field label={t('settings.system.authentikUrl')} htmlFor="a-url">
            <input id="a-url" className="input" type="url" placeholder="https://auth.example.com" value={authentik.url} onChange={(e) => setAuthentik((a) => ({ ...a, url: e.target.value }))} />
          </Field>
          <Field label={t('settings.system.authentikToken')} htmlFor="a-token" help={t('settings.system.authentikTokenHelp')}>
            <input id="a-token" className="input" type="password" autoComplete="new-password" value={authentik.token} onChange={(e) => setAuthentik((a) => ({ ...a, token: e.target.value }))} />
          </Field>
          <div className="flex flex-wrap gap-2 sm:col-span-2">
            <button type="submit" className="btn btn-accent" disabled={busy || noAddress || !authentik.url.trim() || !authentik.token.trim()}>
              {busy ? t('settings.system.authentikBusy') : t('settings.system.authentikRun')}
            </button>
            {!noAddress && (
              <a className="btn" href={serverUrl('/api/v1/oidc/authentik/blueprint')} download>
                <Download size={14} />
                {t('settings.system.authentikBlueprint')}
              </a>
            )}
          </div>
        </form>
        {steps && (
          <>
            <ol className="mt-3 space-y-1 text-xs" data-testid="authentik-steps">
              {steps.steps.map((step) => (
                <li key={step.key} className={step.ok ? 'text-ok' : 'text-bad'}>
                  {step.ok ? '✓' : '✗'} {t(`settings.system.authentikStep.${step.key}`, { defaultValue: step.key })}: {step.detail}
                </li>
              ))}
            </ol>
            {steps.ok && <p className="mt-2 text-[12px]">{t('settings.system.authentikDone')}</p>}
          </>
        )}
      </SettingsCard>
      <SettingsCard title={t('settings.system.oidc')} description={t('settings.system.oidcHelp')}>
        <ul className="space-y-1.5 mb-4">
          {(providers.data ?? []).map((provider) => (
            <li key={provider.id} className={`flex items-center gap-2 rounded-xl border p-2.5 text-sm ${editing?.id === provider.id ? 'border-accent' : 'border-line'}`}>
              <span className="flex-1 truncate">
                {provider.label} <span className="text-faint text-xs">{provider.issuer_url}</span>
              </span>
              <span className="dot" data-status={provider.enabled ? 'ok' : 'unknown'} />
              <button className="btn btn-icon h-7 w-7" onClick={() => edit(provider)} aria-label={t('settings.system.oidcEdit', { name: provider.label })} aria-pressed={editing?.id === provider.id}>
                <Pencil size={14} />
              </button>
              <button className="btn btn-icon h-7 w-7 btn-danger" onClick={() => void del(`/oidc/providers/${provider.id}`).then(() => providers.refetch()).catch(fail)} aria-label={t('common.delete')}>
                <Trash2 size={14} />
              </button>
            </li>
          ))}
        </ul>
        <div className="grid sm:grid-cols-2 gap-3">
          <Field label={t('settings.system.oidcSlug')} htmlFor="o-slug" help="authentik, keycloak, …">
            <input id="o-slug" className="input" value={form.slug} onChange={(e) => setForm((f) => ({ ...f, slug: e.target.value.toLowerCase() }))} />
          </Field>
          <Field label={t('settings.system.oidcLabel')} htmlFor="o-label">
            <input id="o-label" className="input" value={form.label} onChange={(e) => setForm((f) => ({ ...f, label: e.target.value }))} />
          </Field>
          <Field label={t('settings.system.oidcIssuer')} htmlFor="o-issuer">
            <input id="o-issuer" className="input" type="url" placeholder="https://auth.example.com/application/o/nexdeck/" value={form.issuer_url} onChange={(e) => setForm((f) => ({ ...f, issuer_url: e.target.value }))} />
          </Field>
          <Field label={t('settings.system.oidcClientId')} htmlFor="o-client">
            <input id="o-client" className="input" value={form.client_id} onChange={(e) => setForm((f) => ({ ...f, client_id: e.target.value }))} />
          </Field>
          <Field label={t('settings.system.oidcSecret')} htmlFor="o-secret">
            <input
              id="o-secret"
              className="input"
              type="password"
              autoComplete="off"
              placeholder={editing?.has_secret ? t('settings.system.oidcSecretKept') : undefined}
              value={form.client_secret}
              onChange={(e) => setForm((f) => ({ ...f, client_secret: e.target.value }))}
            />
          </Field>
          <Field label={t('settings.system.oidcRole')} htmlFor="o-role">
            <Select
              id="o-role"
              value={form.default_role}
              onChange={(default_role) => setForm((f) => ({ ...f, default_role }))}
              options={[
                { value: 'user', label: t('users.role.user') },
                { value: 'guest', label: t('users.role.guest') },
                { value: 'admin', label: t('users.role.admin') },
              ]}
            />
          </Field>
        </div>
        {editing && <Switch checked={form.enabled} onChange={(enabled) => setForm((f) => ({ ...f, enabled }))} label={t('settings.system.oidcEnabled')} description={t('settings.system.oidcEnabledHelp')} />}
        <Switch checked={form.auto_create} onChange={(auto_create) => setForm((f) => ({ ...f, auto_create }))} label={t('settings.system.oidcAutoCreate')} description={t('settings.system.oidcAutoCreateHelp')} />
        <Switch checked={form.trusts_second_factor} onChange={(trusts_second_factor) => setForm((f) => ({ ...f, trusts_second_factor }))} label={t('settings.system.oidcTrustsSecondFactor')} description={t('settings.system.oidcTrustsSecondFactorHelp')} />
        <p className="text-[11px] text-faint mb-2">{t('settings.system.oidcRedirect', { url: `${base}/api/v1/auth/oidc/${form.slug || 'slug'}/callback` })}</p>
        {editing && editing.slug !== form.slug && <p className="text-[11px] text-warn mb-2">{t('settings.system.oidcSlugChanged')}</p>}
        <div className="flex gap-2">
          <button className="btn btn-accent" disabled={!form.slug || !form.label || !form.issuer_url || !form.client_id} onClick={save}>
            {editing ? t('common.save') : t('settings.system.oidcAdd')}
          </button>
          {editing && (
            <button className="btn" onClick={reset}>
              {t('common.cancel')}
            </button>
          )}
        </div>
      </SettingsCard>
      <Confirm
        open={dropping !== null}
        title={t('settings.system.oidcIssuerChangeTitle')}
        body={t('settings.system.oidcIssuerChange', { count: dropping ?? 0 })}
        confirmLabel={t('settings.system.oidcIssuerChangeGo')}
        danger
        onCancel={() => setDropping(null)}
        onConfirm={() => {
          setDropping(null)
          store()
        }}
      />
      {toast && (
        <Toast level={toast.level} onClose={() => setToast(null)}>
          {toast.text}
        </Toast>
      )}
    </>
  )
}
