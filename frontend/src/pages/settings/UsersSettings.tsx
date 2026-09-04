import { useQuery } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, del, get, patch, post } from '../../api/client'
import type { User } from '../../api/types'
import { Confirm, Field, Select, Toast } from '../../components/ui'
import { useAuth } from '../../stores/auth'
import { SettingsCard } from './SettingsPage'

export function UsersSettings() {
  const { t } = useTranslation()
  const me = useAuth((s) => s.user)
  const users = useQuery({ queryKey: ['users-admin'], queryFn: () => get<User[]>('/users') })
  const [form, setForm] = useState({ username: '', password: '', display_name: '', role: 'user' })
  const [removing, setRemoving] = useState<User | null>(null)
  const [toast, setToast] = useState<{ text: string; level: 'ok' | 'error' } | null>(null)
  const roles = [{ value: 'admin', label: t('users.role.admin') }, { value: 'user', label: t('users.role.user') }, { value: 'guest', label: t('users.role.guest') }]
  const fail = (failure: unknown) => setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' })
  return (
    <>
      <SettingsCard title={t('settings.users.title')} description={t('settings.users.help')}>
        <ul className="space-y-1.5">
          {(users.data ?? []).map((user) => (
            <li key={user.id} className="flex items-center gap-2 rounded-xl border border-line p-2.5">
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium truncate">
                  {user.display_name || user.username} <span className="text-faint text-xs">@{user.username}</span>
                  {user.disabled && <span className="chip ml-2 !py-0 text-[10px]">{t('users.disabled')}</span>}
                </div>
              </div>
              <Select className="!w-32 !h-8" value={user.role} onChange={(role) => void patch(`/users/${user.id}`, { role }).then(() => users.refetch()).catch(fail)} options={roles} />
              {user.id !== me?.id && (
                <>
                  <button className="btn h-8 text-xs" onClick={() => void patch(`/users/${user.id}`, { disabled: !user.disabled }).then(() => users.refetch()).catch(fail)}>
                    {user.disabled ? t('users.enable') : t('users.disable')}
                  </button>
                  <button className="btn btn-icon h-8 w-8 btn-danger" onClick={() => setRemoving(user)} aria-label={t('common.delete')}>
                    <Trash2 size={14} />
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      </SettingsCard>
      <SettingsCard title={t('settings.users.add')}>
        <div className="grid sm:grid-cols-2 gap-3">
          <Field label={t('auth.username')} htmlFor="u-name">
            <input id="u-name" className="input" value={form.username} onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))} />
          </Field>
          <Field label={t('auth.password')} htmlFor="u-pass">
            <input id="u-pass" className="input" type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))} />
          </Field>
          <Field label={t('settings.profile.displayName')} htmlFor="u-display">
            <input id="u-display" className="input" value={form.display_name} onChange={(e) => setForm((f) => ({ ...f, display_name: e.target.value }))} />
          </Field>
          <Field label={t('users.roleLabel')} htmlFor="u-role">
            <Select id="u-role" value={form.role} onChange={(role) => setForm((f) => ({ ...f, role }))} options={roles} />
          </Field>
        </div>
        <button
          className="btn btn-accent"
          disabled={!form.username.trim() || form.password.length < 8}
          onClick={() =>
            void post('/users', form)
              .then(() => {
                setForm({ username: '', password: '', display_name: '', role: 'user' })
                void users.refetch()
              })
              .catch(fail)
          }
        >
          {t('common.create')}
        </button>
      </SettingsCard>
      <Confirm
        open={removing !== null}
        title={t('users.remove', { name: removing?.username ?? '' })}
        body={t('users.removeBody')}
        danger
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          const target = removing
          setRemoving(null)
          if (target) void del(`/users/${target.id}`).then(() => users.refetch()).catch(fail)
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
