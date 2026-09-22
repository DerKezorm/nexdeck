/**
 * Signed in on the home network without a password, for a wall tablet.
 *
 * The page says first what nexdeck makes of the administrator's own address:
 * behind a reverse proxy that nobody named in NEXDECK_TRUSTED_PROXIES the real
 * addresses are unknown, and then nobody is signed in automatically, whatever
 * networks stand here. Only ordinary accounts are offered.
 */
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, get, put } from '../../api/client'
import { Field, Select, Switch, Toast } from '../../components/ui'
import { SettingsCard } from './SettingsCard'

interface HomeSettings {
  enabled: boolean
  networks: string[]
  user_id: number | null
  seen: { address: string | null; how: string; reason: string }
  trusted_proxies: string[]
  recent: { username: string; address: string; at: string; active: boolean; user_agent: string }[]
}

interface Account {
  id: number
  username: string
  display_name: string
  role: string
  disabled: boolean
}

export function HomeNetworkSettings() {
  const { t, i18n } = useTranslation()
  const state = useQuery({ queryKey: ['home-network'], queryFn: () => get<HomeSettings>('/settings/home-network') })
  const accounts = useQuery({ queryKey: ['users'], queryFn: () => get<Account[]>('/users') })
  const [enabled, setEnabled] = useState(false)
  const [networks, setNetworks] = useState('')
  const [userId, setUserId] = useState('')
  const [message, setMessage] = useState<{ level: 'ok' | 'error'; text: string } | null>(null)

  useEffect(() => {
    if (!state.data) return
    setEnabled(state.data.enabled)
    setNetworks(state.data.networks.join('\n'))
    setUserId(state.data.user_id ? String(state.data.user_id) : '')
  }, [state.data])

  const save = () => {
    setMessage(null)
    put<HomeSettings>('/settings/home-network', {
      enabled,
      networks: networks.split(/[\n,]/).map((line) => line.trim()).filter(Boolean),
      user_id: userId ? Number(userId) : null,
    })
      .then(() => {
        setMessage({ level: 'ok', text: t('settings.home.saved') })
        void state.refetch()
      })
      .catch((failure) => setMessage({ level: 'error', text: failure instanceof ApiError ? failure.message : t('errors.network') }))
  }

  const ordinary = (accounts.data ?? []).filter((account) => account.role !== 'admin' && !account.disabled)
  const seen = state.data?.seen

  return (
    <>
      <SettingsCard title={t('settings.home.title')} description={t('settings.home.help')}>
        {seen && (
          <p className={`text-sm mb-3 rounded-lg border px-3 py-2 ${seen.address ? 'border-line' : 'border-warn/40 bg-warn/10'}`} data-testid="home-seen">
            {seen.address ? t('settings.home.seenAt', { address: seen.address }) : t('settings.home.seenNone')}
            <span className="block text-[12px] text-muted mt-0.5">{t(`settings.home.how.${seen.how}`, { defaultValue: seen.reason })}</span>
          </p>
        )}
        <Switch checked={enabled} onChange={setEnabled} label={t('settings.home.enabled')} description={t('settings.home.enabledHelp')} />
        <Field label={t('settings.home.networks')} help={t('settings.home.networksHelp')} htmlFor="home-networks">
          <textarea id="home-networks" className="input font-mono text-[12px] min-h-20" value={networks} onChange={(event) => setNetworks(event.target.value)} placeholder="192.168.1.0/24" />
        </Field>
        <Field label={t('settings.home.account')} help={t('settings.home.accountHelp')} htmlFor="home-account">
          <Select
            id="home-account"
            value={userId}
            onChange={setUserId}
            options={[{ value: '', label: t('settings.home.noAccount') }, ...ordinary.map((account) => ({ value: String(account.id), label: account.display_name || account.username }))]}
          />
        </Field>
        <p className="text-[12px] text-muted mb-3">
          {state.data?.trusted_proxies.length ? t('settings.home.proxies', { list: state.data.trusted_proxies.join(', ') }) : t('settings.home.noProxies')}
        </p>
        <button type="button" className="btn btn-accent" onClick={save}>
          {t('common.save')}
        </button>
        {message && (
          <div className="mt-3">
            <Toast level={message.level} onClose={() => setMessage(null)}>
              {message.text}
            </Toast>
          </div>
        )}
      </SettingsCard>
      {state.data?.recent.length ? (
        <SettingsCard title={t('settings.home.recent')}>
          <ul className="space-y-1 text-sm">
            {state.data.recent.map((entry) => (
              <li key={`${entry.at}-${entry.address}`} className="flex gap-3">
                <span className="num text-muted w-40 shrink-0">{new Date(entry.at).toLocaleString(i18n.language)}</span>
                <span className="num">{entry.address}</span>
                <span className="text-muted truncate">{entry.username}</span>
                {!entry.active && <span className="text-faint text-[12px]">{t('settings.home.ended')}</span>}
              </li>
            ))}
          </ul>
        </SettingsCard>
      ) : null}
    </>
  )
}
