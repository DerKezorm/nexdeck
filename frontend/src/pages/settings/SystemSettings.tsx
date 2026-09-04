import { useQuery } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, del, get, patch, post } from '../../api/client'
import type { About } from '../../api/types'
import { Field, Select, Switch, Toast } from '../../components/ui'
import { useAuth } from '../../stores/auth'
import { SettingsCard } from './SettingsPage'

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
  default_role: string
}

/** Version and counts for everyone; public URL, demo, update check and OIDC for administrators. */
export function SystemSettings() {
  const { t } = useTranslation()
  const user = useAuth((s) => s.user)
  const admin = user?.role === 'admin'
  const about = useQuery({ queryKey: ['about'], queryFn: () => get<About>('/about') })
  const providers = useQuery({ queryKey: ['oidc-providers'], queryFn: () => get<Provider[]>('/oidc/providers'), enabled: admin })
  const [publicUrl, setPublicUrl] = useState('')
  const [toast, setToast] = useState<{ text: string; level: 'ok' | 'error' } | null>(null)
  const [form, setForm] = useState({ slug: '', label: '', issuer_url: '', client_id: '', client_secret: '', scopes: 'openid profile email', enabled: true, auto_create: true, default_role: 'user' })
  useEffect(() => {
    if (about.data) setPublicUrl(about.data.public_url)
  }, [about.data])
  const fail = (failure: unknown) => setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' })
  const save = (body: Record<string, unknown>) => void patch('/settings', body).then(() => about.refetch()).then(() => setToast({ text: t('common.saved'), level: 'ok' })).catch(fail)
  const data = about.data
  return (
    <>
      <SettingsCard title={t('settings.system.title')}>
        {data && (
          <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
            <div>
              <dt className="text-[11px] text-muted uppercase tracking-wide">{t('settings.system.version')}</dt>
              <dd className="num font-semibold">
                {data.version}
                {data.latest_version && data.latest_version !== data.version && <span className="chip ml-2 !py-0 text-[10px]">{t('settings.system.updateAvailable', { version: data.latest_version })}</span>}
              </dd>
            </div>
            <div>
              <dt className="text-[11px] text-muted uppercase tracking-wide">{t('settings.system.boards')}</dt>
              <dd className="num font-semibold">{data.counts.boards}</dd>
            </div>
            <div>
              <dt className="text-[11px] text-muted uppercase tracking-wide">{t('settings.system.widgets')}</dt>
              <dd className="num font-semibold">{data.counts.widgets}</dd>
            </div>
            <div>
              <dt className="text-[11px] text-muted uppercase tracking-wide">{t('settings.system.connections')}</dt>
              <dd className="num font-semibold">{data.connections}</dd>
            </div>
          </dl>
        )}
        <p className="text-[11px] text-faint mt-4">
          nexdeck · AGPL-3.0 ·{' '}
          <a className="text-accent" href="https://nexview.nexapps.dev" target="_blank" rel="noreferrer">
            nexapps
          </a>
        </p>
      </SettingsCard>
      {admin && data && (
        <>
          <SettingsCard title={t('settings.system.installation')} description={t('settings.system.installationHelp')}>
            <Field label={t('settings.system.publicUrl')} htmlFor="s-url" help={t('settings.system.publicUrlHelp')}>
              <div className="flex gap-2">
                <input id="s-url" className="input" type="url" placeholder="https://deck.example.com" value={publicUrl} onChange={(e) => setPublicUrl(e.target.value)} />
                <button className="btn flex-none" onClick={() => save({ public_url: publicUrl })}>
                  {t('common.save')}
                </button>
              </div>
            </Field>
            <Switch checked={data.demo} onChange={(demo) => save({ demo })} label={t('settings.system.demo')} description={t('settings.system.demoHelp')} />
            <Switch checked={data.update_check} onChange={(update_check) => save({ update_check })} label={t('settings.system.updateCheck')} description={t('settings.system.updateCheckHelp')} />
          </SettingsCard>
          <SettingsCard title={t('settings.system.oidc')} description={t('settings.system.oidcHelp')}>
            <ul className="space-y-1.5 mb-4">
              {(providers.data ?? []).map((provider) => (
                <li key={provider.id} className="flex items-center gap-2 rounded-xl border border-line p-2.5 text-sm">
                  <span className="flex-1 truncate">
                    {provider.label} <span className="text-faint text-xs">{provider.issuer_url}</span>
                  </span>
                  <span className="dot" data-status={provider.enabled ? 'ok' : 'unknown'} />
                  <button className="btn btn-icon h-7 w-7 btn-danger" onClick={() => void del(`/oidc/providers/${provider.id}`).then(() => providers.refetch())} aria-label={t('common.delete')}>
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
                <input id="o-secret" className="input" type="password" autoComplete="off" value={form.client_secret} onChange={(e) => setForm((f) => ({ ...f, client_secret: e.target.value }))} />
              </Field>
              <Field label={t('settings.system.oidcRole')} htmlFor="o-role">
                <Select id="o-role" value={form.default_role} onChange={(default_role) => setForm((f) => ({ ...f, default_role }))} options={[{ value: 'user', label: t('users.role.user') }, { value: 'guest', label: t('users.role.guest') }, { value: 'admin', label: t('users.role.admin') }]} />
              </Field>
            </div>
            <Switch checked={form.auto_create} onChange={(auto_create) => setForm((f) => ({ ...f, auto_create }))} label={t('settings.system.oidcAutoCreate')} description={t('settings.system.oidcAutoCreateHelp')} />
            <p className="text-[11px] text-faint mb-2">{t('settings.system.oidcRedirect', { url: `${publicUrl || window.location.origin}/api/v1/auth/oidc/${form.slug || 'slug'}/callback` })}</p>
            <button
              className="btn btn-accent"
              disabled={!form.slug || !form.label || !form.issuer_url || !form.client_id}
              onClick={() =>
                void post('/oidc/providers', form)
                  .then(() => {
                    setForm({ slug: '', label: '', issuer_url: '', client_id: '', client_secret: '', scopes: 'openid profile email', enabled: true, auto_create: true, default_role: 'user' })
                    void providers.refetch()
                  })
                  .catch(fail)
              }
            >
              {t('settings.system.oidcAdd')}
            </button>
          </SettingsCard>
        </>
      )}
      {toast && (
        <Toast level={toast.level} onClose={() => setToast(null)}>
          {toast.text}
        </Toast>
      )}
    </>
  )
}
