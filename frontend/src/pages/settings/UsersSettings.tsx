import { useQuery } from '@tanstack/react-query'
import { MoreHorizontal, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, del, get, patch, post } from '../../api/client'
import type { LinkedProvider, User } from '../../api/types'

type Belongings = { boards: { slug: string; name: string }[]; kiosk_tokens: number; api_tokens: number; channels: number }
import { Avatar } from '../../components/Avatar'
import { Confirm, Dialog, Field, PasswordInput, Select, Toast } from '../../components/ui'
import { useAuth } from '../../stores/auth'
import { oidcErrorKey } from '../../vendor/nexoidc/oidc'
import { SettingsCard } from './SettingsCard'

export function UsersSettings() {
  const { t } = useTranslation()
  const me = useAuth((s) => s.user)
  const users = useQuery({ queryKey: ['users-admin'], queryFn: () => get<User[]>('/users') })
  const [form, setForm] = useState({ username: '', password: '', display_name: '', role: 'user' })
  const [removing, setRemoving] = useState<User | null>(null)
  // ⚠️ What hangs off the account, asked for before the question is put, so
  // the question can name it. A board whose owner is gone kept running and
  // showed up in nobody's list, which is a thing you only notice by the load.
  const [whatBecomesOfTheBoards, setWhatBecomesOfTheBoards] = useState('hand_over')
  const belongings = useQuery({
    queryKey: ['belongings', removing?.id],
    queryFn: () => get<Belongings>(`/users/${removing?.id}/belongings`),
    enabled: removing !== null,
  })
  // Setting someone else's password: no old password needed, the
  // administrator is the way back in when a user has locked himself out.
  const [passwordFor, setPasswordFor] = useState<User | null>(null)
  const [newPassword, setNewPassword] = useState('')
  const [repeated, setRepeated] = useState('')
  const [toast, setToast] = useState<{ text: string; level: 'ok' | 'error' } | null>(null)
  const roles = [{ value: 'admin', label: t('users.role.admin') }, { value: 'user', label: t('users.role.user') }, { value: 'guest', label: t('users.role.guest') }]
  const fail = (failure: unknown) => setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' })
  // The administrator unlinks an account from a provider with the own password (sign-in blueprint 01).
  const [unlinking, setUnlinking] = useState<{ user: User; provider: LinkedProvider } | null>(null)
  const [ownPassword, setOwnPassword] = useState('')
  // The menu per account ("Unlink <provider>", sign-in blueprint 04): one at a time, closed by a click elsewhere or Escape.
  const [menuFor, setMenuFor] = useState<number | null>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (menuFor === null) return
    const away = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuFor(null)
    }
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenuFor(null)
    }
    window.addEventListener('mousedown', away)
    window.addEventListener('keydown', key)
    return () => {
      window.removeEventListener('mousedown', away)
      window.removeEventListener('keydown', key)
    }
  }, [menuFor])
  const owned = belongings.data?.boards ?? []
  const alsoOnIt = [
    belongings.data?.kiosk_tokens ? t('users.removeKiosk', { count: belongings.data.kiosk_tokens }) : '',
    belongings.data?.api_tokens ? t('users.removeTokens', { count: belongings.data.api_tokens }) : '',
    belongings.data?.channels ? t('users.removeChannels', { count: belongings.data.channels }) : '',
  ].filter(Boolean)
  return (
    <>
      <SettingsCard title={t('settings.users.title')} description={t('settings.users.help')}>
        <ul className="space-y-1.5">
          {(users.data ?? []).map((user) => (
            <li key={user.id} className="flex items-center gap-2 rounded-xl border border-line p-2.5">
              <Avatar url={user.avatar_url} name={user.display_name || user.username} size={28} />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium truncate">
                  {user.display_name || user.username} <span className="text-faint text-xs">@{user.username}</span>
                  {user.disabled && <span className="chip ml-2 !py-0 text-[10px]">{t('users.disabled')}</span>}
                </div>
                {user.email && <div className="text-[11px] text-muted truncate">{user.email}</div>}
                {(user.providers ?? []).length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1" data-testid="account-providers">
                    {(user.providers ?? []).map((provider) => (
                      <span key={provider.provider_id} className="chip !py-0 text-[10px]">
                        {provider.label}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              {(user.providers ?? []).length > 0 && (
                <div className="relative" ref={menuFor === user.id ? menuRef : undefined}>
                  <button
                    type="button"
                    className="btn btn-icon h-8 w-8"
                    aria-haspopup="menu"
                    aria-expanded={menuFor === user.id}
                    aria-label={t('users.moreFor', { name: user.display_name || user.username })}
                    onClick={() => setMenuFor(menuFor === user.id ? null : user.id)}
                  >
                    <MoreHorizontal size={14} />
                  </button>
                  {menuFor === user.id && (
                    <div className="absolute right-0 top-9 z-50 glass-strong rounded-xl p-1 min-w-56 shadow-2xl" role="menu">
                      {(user.providers ?? []).map((provider) => (
                        <button
                          key={provider.provider_id}
                          type="button"
                          role="menuitem"
                          className="w-full text-left px-3 py-2 rounded-lg text-sm hover:bg-surface-hover"
                          onClick={() => {
                            setMenuFor(null)
                            setOwnPassword('')
                            setUnlinking({ user, provider })
                          }}
                        >
                          {t('users.unlink', { name: provider.label })}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
              <Select className="!w-32 !h-8" value={user.role} onChange={(role) => void patch(`/users/${user.id}`, { role }).then(() => users.refetch()).catch(fail)} options={roles} />
              {user.id !== me?.id && (
                <>
                  <button
                    className="btn h-8 text-xs"
                    onClick={() => {
                      setNewPassword('')
                      setRepeated('')
                      setPasswordFor(user)
                    }}
                  >
                    {t('users.setPassword')}
                  </button>
                  <button className="btn h-8 text-xs" onClick={() => void patch(`/users/${user.id}`, { disabled: !user.disabled }).then(() => users.refetch()).catch(fail)}>
                    {user.disabled ? t('users.enable') : t('users.disable')}
                  </button>
                  <button className="btn btn-icon h-8 w-8 btn-danger" onClick={() => { setWhatBecomesOfTheBoards('hand_over'); setRemoving(user) }} aria-label={t('common.delete')}>
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
            <PasswordInput id="u-pass" autoComplete="new-password" value={form.password} onChange={(password) => setForm((f) => ({ ...f, password }))} />
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
      <Dialog
        open={passwordFor !== null}
        onClose={() => setPasswordFor(null)}
        title={t('users.setPasswordFor', { name: passwordFor?.display_name || passwordFor?.username || '' })}
        footer={
          <>
            <button className="btn" onClick={() => setPasswordFor(null)}>
              {t('common.cancel')}
            </button>
            <button
              className="btn btn-accent"
              disabled={newPassword.length < 8 || newPassword !== repeated}
              onClick={() => {
                const target = passwordFor
                if (!target) return
                void patch(`/users/${target.id}`, { password: newPassword })
                  .then(() => {
                    setPasswordFor(null)
                    setToast({ text: t('common.saved'), level: 'ok' })
                  })
                  .catch(fail)
              }}
            >
              {t('users.setPassword')}
            </button>
          </>
        }
      >
        <div className="grid gap-3">
          <Field label={t('settings.profile.newPassword')} htmlFor="up-new" help={t('setup.passwordHelp')}>
            <PasswordInput id="up-new" autoComplete="new-password" value={newPassword} onChange={setNewPassword} />
          </Field>
          <Field label={t('settings.profile.confirmPassword')} htmlFor="up-new2">
            <PasswordInput id="up-new2" autoComplete="new-password" value={repeated} onChange={setRepeated} />
            {repeated.length > 0 && repeated !== newPassword && <p className="text-[11px] mt-1 text-warn">{t('auth.mismatch')}</p>}
          </Field>
          <p className="text-[11px] text-faint">{t('users.setPasswordHelp')}</p>
        </div>
      </Dialog>
      <Confirm
        open={removing !== null}
        title={t('users.remove', { name: removing?.username ?? '' })}
        body={t('users.removeBody')}
        danger
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          const target = removing
          const decision = owned.length > 0 ? `?boards=${whatBecomesOfTheBoards}` : ''
          setRemoving(null)
          if (target) void del(`/users/${target.id}${decision}`).then(() => users.refetch()).catch(fail)
        }}
      >
        {owned.length > 0 && (
          <div className="mt-3 grid gap-2">
            <p className="text-sm">{t('users.removeOwns', { count: owned.length, boards: owned.map((b) => b.name).join(', ') })}</p>
            <Select
              value={whatBecomesOfTheBoards}
              onChange={setWhatBecomesOfTheBoards}
              options={[
                { value: 'hand_over', label: t('users.removeHandOver') },
                { value: 'delete', label: t('users.removeBoardsToo') },
              ]}
            />
          </div>
        )}
        {alsoOnIt.length > 0 && <p className="text-[11px] text-faint mt-2">{t('users.removeAlso', { what: alsoOnIt.join(', ') })}</p>}
      </Confirm>
      <Confirm
        open={unlinking !== null}
        title={t('users.unlinkTitle', { name: unlinking?.provider.label ?? '' })}
        body={t('users.unlinkBody', { account: unlinking?.user.username ?? '', name: unlinking?.provider.label ?? '' })}
        confirmLabel={t('oidc.account.unlink')}
        confirmDisabled={!ownPassword}
        danger
        onCancel={() => setUnlinking(null)}
        onConfirm={() => {
          const target = unlinking
          setUnlinking(null)
          if (!target) return
          void del(`/oidc/admin/accounts/${target.user.id}/links/${target.provider.provider_id}`, { password: ownPassword })
            .then(() => {
              setToast({ text: t('users.unlinked', { name: target.provider.label }), level: 'ok' })
              return users.refetch()
            })
            .catch((failure: unknown) => {
              const key = failure instanceof ApiError ? oidcErrorKey(failure.code) : null
              if (key) setToast({ text: t(key), level: 'error' })
              else fail(failure)
            })
        }}
      >
        <div className="mt-3">
          <Field label={t('settings.twoFactor.confirmWithPassword')} htmlFor="unlink-password">
            <PasswordInput id="unlink-password" autoComplete="current-password" value={ownPassword} onChange={setOwnPassword} />
          </Field>
        </div>
      </Confirm>
      {toast && (
        <Toast level={toast.level} onClose={() => setToast(null)}>
          {toast.text}
        </Toast>
      )}
    </>
  )
}
