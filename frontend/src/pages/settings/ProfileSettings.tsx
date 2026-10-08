import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, del, get, post, upload } from '../../api/client'
import type { BoardSummary, User } from '../../api/types'
import { Avatar } from '../../components/Avatar'
import { TwoFactorCard } from '../../components/TwoFactorCard'
import { Field, PasswordInput, Select, Toast } from '../../components/ui'
import { accountPair, LANGUAGES } from '../../i18n'
import { useAuth } from '../../stores/auth'
import { SettingsCard } from './SettingsCard'

export function ProfileSettings() {
  const { t } = useTranslation()
  const { user, update, logout, setUser } = useAuth()
  const fileRef = useRef<HTMLInputElement>(null)
  const boards = useQuery({ queryKey: ['boards'], queryFn: () => get<BoardSummary[]>('/boards') })
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: () => get<{ id: number; user_agent: string; last_seen_at: string }[]>('/auth/sessions') })
  const [displayName, setDisplayName] = useState(user?.display_name ?? '')
  const [email, setEmail] = useState(user?.email ?? '')
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [toast, setToast] = useState<{ text: string; level: 'ok' | 'error' } | null>(null)
  const links = useQuery({ queryKey: ['oidc-links'], queryFn: () => get<{ slug: string; label: string; linked: boolean }[]>('/auth/oidc/links') })
  // Back from the provider after linking: say how it went, once, and take it
  // out of the address so a reload does not say it again.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const linked = params.get('oidc_linked')
    const failure = params.get('oidc_error')
    if (!linked && !failure) return
    setToast(
      linked
        ? { text: t('settings.profile.providerLinked'), level: 'ok' }
        : { text: t(`auth.oidc.${failure}`, { defaultValue: t('auth.oidc.failed') }), level: 'error' },
    )
    params.delete('oidc_linked')
    params.delete('oidc_error')
    const rest = params.toString()
    window.history.replaceState(null, '', window.location.pathname + (rest ? `?${rest}` : ''))
  }, [t])
  if (!user) return null
  const mismatch = confirm.length > 0 && confirm !== next
  const pair = accountPair(user.language_pair)
  const languageOptions = Object.entries(LANGUAGES).map(([value, label]) => ({ value, label }))
  /** One button changed; taking the other button's language swaps the two. */
  const choosePair = (index: 0 | 1, code: string) => {
    const other = pair[1 - index]
    const next: [string, string] = index === 0 ? [code, code === other ? pair[0] : other] : [code === other ? pair[1] : other, code]
    void update({ language_pair: next }).catch(failed)
  }
  /** Whether the two fields above the button differ from what is stored. */
  const dirty = displayName !== (user.display_name ?? '') || email !== (user.email ?? '')
  const failed = (failure: unknown) => setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' })
  const pickPicture = (file: File) => {
    void upload('/auth/me/avatar', file)
      .then((updated) => {
        setUser(updated as User)
        setToast({ text: t('common.saved'), level: 'ok' })
      })
      .catch(failed)
  }
  return (
    <>
      <SettingsCard title={t('settings.profile.picture')} description={t('settings.profile.pictureHelp')}>
        <div className="flex flex-wrap items-center gap-4">
          <Avatar url={user.avatar_url} name={user.display_name || user.username} size={72} />
          <input
            ref={fileRef}
            type="file"
            accept="image/png,image/jpeg,image/gif,image/webp"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) pickPicture(file)
              // Cleared, so choosing the same file again is a change again.
              e.target.value = ''
            }}
          />
          <div className="flex flex-wrap gap-2">
            <button className="btn" onClick={() => fileRef.current?.click()}>
              {t('settings.profile.chooseImage')}
            </button>
            {user.avatar_url && (
              <button
                className="btn"
                onClick={() =>
                  void del<User>('/auth/me/avatar')
                    .then((updated) => {
                      setUser(updated)
                      setToast({ text: t('common.saved'), level: 'ok' })
                    })
                    .catch(failed)
                }
              >
                {t('settings.profile.removeImage')}
              </button>
            )}
          </div>
        </div>
      </SettingsCard>

      <SettingsCard title={t('settings.profile.title')}>
        <div className="grid sm:grid-cols-2 gap-3">
          <Field label={t('settings.profile.displayName')} htmlFor="p-name">
            <input id="p-name" className="input" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          </Field>
          {/* The address is what a password reset needs; nothing is sent to it otherwise. */}
          <Field label={t('settings.profile.email')} htmlFor="p-mail" help={t('settings.profile.emailHelp')}>
            <input id="p-mail" className="input" type="email" autoComplete="email" placeholder="you@example.com" value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
        </div>
        {/* ⚠️ Everything below this saves the moment it changes; these two
            fields need a press. A quiet button under the left column reads as
            belonging to the name above it, so somebody who fills in the
            address looks for a second one and reports that there is none.
            It spans both fields, it lights up when there is something to
            save, and it says so when there is not. */}
        <div className="mb-3 flex items-center gap-3">
          <button
            className={dirty ? 'btn btn-accent' : 'btn'}
            disabled={!dirty}
            onClick={() =>
              void update({ display_name: displayName, email })
                .then(() => setToast({ text: t('common.saved'), level: 'ok' }))
                .catch(failed)
            }
          >
            {t('settings.profile.saveProfile')}
          </button>
          {dirty && <span className="text-[12px] text-warn">{t('settings.profile.unsaved')}</span>}
        </div>
        <div className="grid sm:grid-cols-3 gap-3">
          <Field label={t('settings.profile.language')} htmlFor="p-lang">
            <Select id="p-lang" value={user.locale} onChange={(locale) => void update({ locale })} options={languageOptions} />
          </Field>
          <Field label={t('settings.profile.theme')} htmlFor="p-theme">
            <Select id="p-theme" value={user.theme} onChange={(theme) => void update({ theme: theme as 'dark' | 'light' | 'system' })} options={[{ value: 'dark', label: t('settings.profile.theme_dark') }, { value: 'light', label: t('settings.profile.theme_light') }, { value: 'system', label: t('settings.profile.theme_system') }]} />
          </Field>
          <Field label={t('settings.profile.startBoard')} htmlFor="p-start">
            <Select id="p-start" value={user.start_board_id ? String(user.start_board_id) : ''} onChange={(value) => void update({ start_board_id: value ? Number(value) : 0 })} options={[{ value: '', label: t('settings.profile.firstBoard') }, ...(boards.data ?? []).map((b) => ({ value: String(b.id), label: b.name }))]} />
          </Field>
        </div>
        <div className="grid sm:grid-cols-3 gap-3">
          <Field label={t('settings.profile.barLanguages')} htmlFor="p-pair-1" help={t('settings.profile.barLanguagesHelp')}>
            <div id="p-pair" className="flex gap-2">
              <select id="p-pair-1" className="input" aria-label={t('settings.profile.barFirst')} aria-describedby="p-pair-1-help" value={pair[0]} onChange={(e) => choosePair(0, e.target.value)}>
                {languageOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <select id="p-pair-2" className="input" aria-label={t('settings.profile.barSecond')} aria-describedby="p-pair-1-help" value={pair[1]} onChange={(e) => choosePair(1, e.target.value)}>
                {languageOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
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
                // ⚠️ A password change ends every session of the account, this
                // one included; the server does that on purpose and a test
                // says so. What was missing is saying it: the app used to
                // announce "saved" and then quietly break, because every
                // request after this one came back 401.
                setToast({ text: t('settings.profile.passwordChangedSignIn'), level: 'ok' })
                window.setTimeout(() => window.location.assign('/login'), 1500)
              })
              .catch((failure) => setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' }))
          }
        >
          {t('settings.profile.changePassword')}
        </button>
      </SettingsCard>

      {new URLSearchParams(window.location.search).get('factor') === 'required' && (
        <p className="rounded-xl border border-warn/40 bg-warn/10 p-3 text-sm mb-3" role="alert">
          {t('settings.profile.factorRequiredHere')}
        </p>
      )}
      <TwoFactorCard hasPassword={user.has_password} onDone={(text, level) => setToast({ text, level })} />

      {(links.data ?? []).length > 0 && (
        <SettingsCard title={t('settings.profile.providers')} description={t('settings.profile.providersHelp')}>
          <ul className="space-y-1.5">
            {(links.data ?? []).map((provider) => (
              <li key={provider.slug} className="flex items-center gap-2 text-sm">
                <span className="flex-1 truncate">{provider.label}</span>
                {/* Not linked, the button says so already; on a phone a second word squeezed the name to three letters. */}
                {provider.linked && <span className="text-[12px] text-ok">{t('settings.profile.providerIsLinked')}</span>}
                {provider.linked ? (
                  <button className="btn h-7 text-xs" onClick={() => void del(`/auth/oidc/${provider.slug}/link`).then(() => links.refetch()).catch(failed)}>
                    {t('settings.profile.providerUnlink')}
                  </button>
                ) : (
                  <button
                    className="btn btn-accent h-7 text-xs"
                    onClick={() =>
                      void post<{ url: string }>(`/auth/oidc/${provider.slug}/link`)
                        .then(({ url }) => window.location.assign(url))
                        .catch(failed)
                    }
                  >
                    {t('settings.profile.providerLink', { name: provider.label })}
                  </button>
                )}
              </li>
            ))}
          </ul>
        </SettingsCard>
      )}

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
