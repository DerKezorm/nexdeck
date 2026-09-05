import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, get, post, put } from '../../api/client'
import { Field, PasswordInput, Select, Toast } from '../../components/ui'
import { useAuth } from '../../stores/auth'
import { SettingsCard } from './SettingsCard'

interface Smtp {
  host: string
  port: number
  security: 'starttls' | 'ssl' | 'none'
  username: string
  password: string
  from_address: string
  from_name: string
  configured: boolean
}

const EMPTY: Smtp = { host: '', port: 587, security: 'starttls', username: '', password: '', from_address: '', from_name: 'nexdeck', configured: false }

/**
 * The mail server of the installation.
 *
 * Not the same as an e-mail notification channel: a channel belongs to whoever
 * set it up, this one belongs to nexdeck itself and carries what has to go out
 * before anybody is signed in, a password reset above all.
 */
export function MailSettings() {
  const { t } = useTranslation()
  const me = useAuth((state) => state.user)
  const saved = useQuery({ queryKey: ['smtp'], queryFn: () => get<Smtp>('/settings/mail') })
  const [form, setForm] = useState<Smtp>(EMPTY)
  const [to, setTo] = useState('')
  const [toast, setToast] = useState<{ text: string; level: 'ok' | 'error' } | null>(null)
  useEffect(() => {
    if (saved.data) setForm(saved.data)
  }, [saved.data])
  const set = <K extends keyof Smtp>(key: K, value: Smtp[K]) => setForm((current) => ({ ...current, [key]: value }))
  const fail = (failure: unknown) => setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' })
  return (
    <>
      <SettingsCard title={t('settings.mail.title')} description={t('settings.mail.help')}>
        <div className="grid sm:grid-cols-2 gap-3">
          <Field label={t('settings.mail.host')} htmlFor="m-host" help={t('settings.mail.hostHelp')}>
            <input id="m-host" className="input" placeholder="smtp.example.com" value={form.host} onChange={(e) => set('host', e.target.value)} />
          </Field>
          <Field label={t('settings.mail.port')} htmlFor="m-port">
            <input id="m-port" className="input num" type="number" min={1} max={65535} value={form.port} onChange={(e) => set('port', Number(e.target.value) || 0)} />
          </Field>
          <Field label={t('settings.mail.security')} htmlFor="m-sec">
            <Select
              id="m-sec"
              value={form.security}
              onChange={(security) => set('security', security as Smtp['security'])}
              options={[
                { value: 'starttls', label: 'STARTTLS' },
                { value: 'ssl', label: 'SSL' },
                { value: 'none', label: t('settings.mail.securityNone') },
              ]}
            />
          </Field>
          <Field label={t('settings.mail.username')} htmlFor="m-user" help={t('settings.mail.usernameHelp')}>
            <input id="m-user" className="input" autoComplete="off" value={form.username} onChange={(e) => set('username', e.target.value)} />
          </Field>
          <Field label={t('settings.mail.password')} htmlFor="m-pass">
            <PasswordInput id="m-pass" autoComplete="new-password" value={form.password} onChange={(password) => set('password', password)} />
          </Field>
          <Field label={t('settings.mail.fromAddress')} htmlFor="m-from" help={t('settings.mail.fromAddressHelp')}>
            <input id="m-from" className="input" type="email" placeholder="deck@example.com" value={form.from_address} onChange={(e) => set('from_address', e.target.value)} />
          </Field>
          <Field label={t('settings.mail.fromName')} htmlFor="m-fromname">
            <input id="m-fromname" className="input" value={form.from_name} onChange={(e) => set('from_name', e.target.value)} />
          </Field>
        </div>
        <button
          className="btn btn-accent"
          onClick={() =>
            void put<Smtp>('/settings/mail', form)
              .then((next) => {
                setForm(next)
                void saved.refetch()
                setToast({ text: t('common.saved'), level: 'ok' })
              })
              .catch(fail)
          }
        >
          {t('common.save')}
        </button>
      </SettingsCard>

      <SettingsCard title={t('settings.mail.test')} description={t('settings.mail.testHelp')}>
        <Field label={t('settings.mail.testTo')} htmlFor="m-to">
          <div className="flex gap-2">
            <input id="m-to" className="input" type="email" placeholder={me?.email || 'you@example.com'} value={to} onChange={(e) => setTo(e.target.value)} />
            <button
              className="btn flex-none"
              disabled={!saved.data?.configured}
              onClick={() =>
                void post<{ to_address: string }>('/settings/mail/test', { to_address: to })
                  .then((result) => setToast({ text: t('settings.mail.testSent', { address: result.to_address }), level: 'ok' }))
                  .catch(fail)
              }
            >
              {t('settings.mail.send')}
            </button>
          </div>
        </Field>
        {!saved.data?.configured && <p className="text-[11px] text-faint">{t('settings.mail.notConfigured')}</p>}
      </SettingsCard>

      {toast && (
        <Toast level={toast.level} onClose={() => setToast(null)}>
          {toast.text}
        </Toast>
      )}
    </>
  )
}
