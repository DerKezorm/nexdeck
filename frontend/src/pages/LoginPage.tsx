import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { ApiError } from '../api/client'
import { BackgroundLayer } from '../components/BackgroundLayer'
import { Logo } from '../components/Logo'
import { Field, PasswordInput } from '../components/ui'
import { useAuth } from '../stores/auth'

export function LoginPage() {
  const { t } = useTranslation()
  const { user, status, loading, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const oidcError = new URLSearchParams(location.search).get('oidc_error')

  useEffect(() => {
    if (user) navigate((location.state as { from?: string } | null)?.from ?? '/', { replace: true })
  }, [user, navigate, location.state])

  if (!loading && status?.needs_setup) return <Navigate to="/setup" replace />

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await login(username.trim(), password)
    } catch (failure) {
      setError(failure instanceof ApiError ? (failure.code === 'bad_credentials' ? t('auth.wrong') : failure.code === 'too_many_attempts' ? t('auth.throttled') : failure.message) : t('errors.network'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-full flex items-center justify-center p-6">
      <BackgroundLayer />
      <form onSubmit={submit} className="glass rounded-2xl p-6 w-full max-w-sm shadow-2xl">
        <div className="flex justify-center mb-6">
          <Logo size={34} />
        </div>
        <Field label={t('auth.username')} htmlFor="username">
          <input id="username" className="input" autoComplete="username" autoFocus value={username} onChange={(e) => setUsername(e.target.value)} />
        </Field>
        <Field label={t('auth.password')} htmlFor="password">
          <PasswordInput id="password" autoComplete="current-password" value={password} onChange={setPassword} />
        </Field>
        {(error || oidcError) && (
          <p className="text-sm text-bad mb-3" role="alert">
            {error || t(`auth.oidc.${oidcError}`, { defaultValue: t('auth.oidc.failed') })}
          </p>
        )}
        <button className="btn btn-accent w-full h-9" type="submit" disabled={busy || !username || !password}>
          {t('auth.signin')}
        </button>
        {status?.providers?.length ? (
          <div className="mt-4 pt-4 border-t border-line space-y-2">
            {status.providers.map((provider) => (
              <a key={provider.slug} className="btn w-full h-9" href={`/api/v1/auth/oidc/${provider.slug}/login`}>
                {t('auth.with', { name: provider.label })}
              </a>
            ))}
          </div>
        ) : null}
      </form>
    </div>
  )
}
