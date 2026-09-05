import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, del, get, post } from '../../api/client'
import type { BoardSummary } from '../../api/types'
import { Field, PasswordInput, Select, Toast } from '../../components/ui'
import { LANGUAGES } from '../../i18n'
import { useAuth } from '../../stores/auth'
import { SettingsCard } from './SettingsPage'

export function ProfileSettings() {
  const { t } = useTranslation()
  const { user, update, logout } = useAuth()
  const boards = useQuery({ queryKey: ['boards'], queryFn: () => get<BoardSummary[]>('/boards') })
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: () => get<{ id: number; user_agent: string; last_seen_at: string }[]>('/auth/sessions') })
  const [displayName, setDisplayName] = useState(user?.display_name ?? '')
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [toast, setToast] = useState<{ text: string; level: 'ok' | 'error' } | null>(null)
  if (!user) return null
  const mismatch = confirm.length > 0 && confirm !== next
  return (
    <>
      <SettingsCard title={t('settings.profile.title')}>
        <Field label={t('settings.profile.displayName')} htmlFor="p-name">
          <div className="flex gap-2">
            <input id="p-name" className="input" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
            <button className="btn flex-none" onClick={() => void update({ display_name: displayName }).then(() => setToast({ text: t('common.saved'), level: 'ok' }))}>
              {t('common.save')}
            </button>
          </div>
        </Field>
        <div className="grid sm:grid-cols-3 gap-3">
          <Field label={t('settings.profile.language')} htmlFor="p-lang">
            <Select id="p-lang" value={user.locale} onChange={(locale) => void update({ locale })} options={Object.entries(LANGUAGES).map(([value, label]) => ({ value, label }))} />
          </Field>
          <Field label={t('settings.profile.theme')} htmlFor="p-theme">
            <Select id="p-theme" value={user.theme} onChange={(theme) => void update({ theme: theme as 'dark' | 'light' | 'system' })} options={[{ value: 'dark', label: t('settings.profile.theme_dark') }, { value: 'light', label: t('settings.profile.theme_light') }, { value: 'system', label: t('settings.profile.theme_system') }]} />
          </Field>
          <Field label={t('settings.profile.startBoard')} htmlFor="p-start">
            <Select id="p-start" value={user.start_board_id ? String(user.start_board_id) : ''} onChange={(value) => void update({ start_board_id: value ? Number(value) : 0 })} options={[{ value: '', label: t('settings.profile.firstBoard') }, ...(boards.data ?? []).map((b) => ({ value: String(b.id), label: b.name }))]} />
          </Field>
        </div>
      </SettingsCard>

      <SettingsCard title={t('settings.profile.password')} description={t('settings.profile.passwordHelp')}>
        <div className="grid sm:grid-cols-3 gap-3">
          {user.has_password && (
            <Field label={t('settings.profile.currentPassword')} htmlFor="p-cur">
              <PasswordInput id="p-cur" autoComplete="current-password" value={current} onChange={setCurrent} />
            </Field>
          )}
          <Field label={t('settings.profile.newPassword')} htmlFor="p-new" help={t('setup.passwordHelp')}>
            <PasswordInput id="p-new" autoComplete="new-password" value={next} onChange={setNext} />
          </Field>
          <Field label={t('settings.profile.confirmPassword')} htmlFor="p-new2">
            <PasswordInput id="p-new2" autoComplete="new-password" value={confirm} onChange={setConfirm} />
            {mismatch && <p className="text-[11px] mt-1 text-warn">{t('auth.mismatch')}</p>}
          </Field>
        </div>
        <button
          className="btn"
          disabled={next.length < 8 || confirm !== next}
          onClick={() =>
            void post('/auth/password', { current_password: current, new_password: next })
              .then(() => {
                setCurrent('')
                setNext('')
                setConfirm('')
                setToast({ text: t('common.saved'), level: 'ok' })
              })
              .catch((failure) => setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' }))
          }
        >
          {t('settings.profile.changePassword')}
        </button>
      </SettingsCard>

      <SettingsCard title={t('settings.profile.sessions')} description={t('settings.profile.sessionsHelp')}>
        <ul className="space-y-1 mb-3">
          {(sessions.data ?? []).map((session) => (
            <li key={session.id} className="flex items-center gap-2 text-sm">
              <span className="flex-1 truncate text-muted">{session.user_agent || '?'}</span>
              <span className="text-[11px] text-faint num">{new Date(session.last_seen_at).toLocaleString()}</span>
              <button className="btn h-7 text-xs" onClick={() => void del(`/auth/sessions/${session.id}`).then(() => sessions.refetch())}>
                {t('settings.profile.signOutSession')}
              </button>
            </li>
          ))}
        </ul>
        <button className="btn btn-danger" onClick={() => void logout().then(() => window.location.assign('/login'))}>
          {t('settings.profile.signOut')}
        </button>
      </SettingsCard>
      {toast && (
        <Toast level={toast.level} onClose={() => setToast(null)}>
          {toast.text}
        </Toast>
      )}
    </>
  )
}
