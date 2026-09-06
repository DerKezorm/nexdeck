/**
 * The door. Three things can happen here: the password is right and the
 * session opens, the password is right but the account wants a code, or
 * somebody has forgotten the password and needs a way back in.
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { ApiError, post } from '../api/client'
import { BackgroundLayer } from '../components/BackgroundLayer'
import { Logo } from '../components/Logo'
import { Field, PasswordInput } from '../components/ui'
import { useAuth } from '../stores/auth'

export function LoginPage() {
  const { t } = useTranslation()
  const { user, status, loading, login, secondStep } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  // The half-finished sign-in: a ticket, and whether recovery codes exist.
  const [step, setStep] = useState<{ ticket: string; recovery: boolean } | null>(null)
  const [code, setCode] = useState('')
  const [useRecovery, setUseRecovery] = useState(false)
  const [forgetting, setForgetting] = useState(false)
  const [sent, setSent] = useState(false)
  const oidcError = new URLSearchParams(location.search).get('oidc_error')

  useEffect(() => {
    if (user) navigate((location.state as { from?: string } | null)?.from ?? '/', { replace: true })
  }, [user, navigate, location.state])

  if (!loading && status?.needs_setup) return <Navigate to="/setup" replace />

  const explain = (failure: unknown) =>
    failure instanceof ApiError
      ? failure.code === 'bad_credentials'
        ? t('auth.wrong')
        : failure.code === 'too_many_attempts'
          ? t('auth.throttled')
          : failure.message
      : t('errors.network')

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const outcome = await login(username.trim(), password)
      if (!outcome.done) {
        setStep({ ticket: outcome.ticket, recovery: outcome.recovery })
        setPassword('')
      }
    } catch (failure) {
      setError(explain(failure))
    } finally {
      setBusy(false)
    }
  }

  const finish = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!step) return
    setBusy(true)
    setError('')
    try {
      await secondStep(step.ticket, useRecovery ? '' : code.trim(), useRecovery ? code.trim() : '')
    } catch (failure) {
      setError(failure instanceof ApiError && failure.code === 'bad_code' ? t('auth.twoFactor.wrongCode') : explain(failure))
      setCode('')
    } finally {
      setBusy(false)
    }
  }

  const askForLink = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await post('/auth/forgot', { username: username.trim() })
      setSent(true)
    } catch (failure) {
      setError(explain(failure))
    } finally {
      setBusy(false)
    }
  }

  const shell = (children: React.ReactNode) => (
    <div className="min-h-full flex items-center justify-center p-6">
      <BackgroundLayer />
      <div className="glass rounded-2xl p-6 w-full max-w-sm shadow-2xl">
        <div className="flex justify-center mb-6">
          <Logo size={34} />
        </div>
        {children}
      </div>
    </div>
  )

  // --- forgotten -----------------------------------------------------------
  if (forgetting) {
    return shell(
      sent ? (
        <>
          {/* ⚠️ The same sentence whether the account exists or not. */}
          <p className="text-sm text-muted mb-4">{t('auth.forgot.sent')}</p>
          <button className="btn w-full h-9" type="button" onClick={() => { setForgetting(false); setSent(false) }}>
            {t('auth.forgot.back')}
          </button>
        </>
      ) : (
        <form onSubmit={askForLink}>
          <p className="text-sm text-muted mb-4">{t('auth.forgot.lead')}</p>
          <Field label={t('auth.forgot.who')} htmlFor="forgot-username">
            <input id="forgot-username" className="input" autoComplete="username" autoFocus value={username} onChange={(e) => setUsername(e.target.value)} />
          </Field>
          {error && <p className="text-sm text-bad mb-3" role="alert">{error}</p>}
          <button className="btn btn-accent w-full h-9" type="submit" disabled={busy || !username.trim()}>
            {t('auth.forgot.send')}
          </button>
          <button className="btn w-full h-9 mt-2" type="button" onClick={() => setForgetting(false)}>
            {t('auth.forgot.back')}
          </button>
        </form>
      ),
    )
  }

  // --- the second step -----------------------------------------------------
  if (step) {
    return shell(
      <form onSubmit={finish}>
        <p className="text-sm text-muted mb-4">{useRecovery ? t('auth.twoFactor.askRecovery') : t('auth.twoFactor.askCode')}</p>
        <Field label={useRecovery ? t('auth.twoFactor.recoveryCode') : t('auth.twoFactor.code')} htmlFor="second-step">
          <input
            id="second-step"
            className="input num"
            autoFocus
            autoComplete="one-time-code"
            inputMode={useRecovery ? 'text' : 'numeric'}
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
        </Field>
        {error && <p className="text-sm text-bad mb-3" role="alert">{error}</p>}
        <button className="btn btn-accent w-full h-9" type="submit" disabled={busy || !code.trim()}>
          {t('auth.signin')}
        </button>
        {step.recovery && (
          <button className="mt-3 block mx-auto text-xs text-accent underline underline-offset-2" type="button" onClick={() => { setUseRecovery(!useRecovery); setCode(''); setError('') }}>
            {useRecovery ? t('auth.twoFactor.useApp') : t('auth.twoFactor.useRecovery')}
          </button>
        )}
        <button className="mt-2 block mx-auto text-xs text-accent underline underline-offset-2" type="button" onClick={() => { setStep(null); setCode(''); setError('') }}>
          {t('auth.forgot.back')}
        </button>
      </form>,
    )
  }

  // --- the ordinary way in -------------------------------------------------
  return shell(
    <form onSubmit={submit}>
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
      {/* Only where a link could actually be sent. */}
      {status?.can_reset_password && (
        <button className="mt-3 block mx-auto text-xs text-accent underline underline-offset-2" type="button" onClick={() => { setForgetting(true); setError('') }}>
          {t('auth.forgot.link')}
        </button>
      )}
      {status?.providers?.length ? (
        <div className="mt-4 pt-4 border-t border-line space-y-2">
          {status.providers.map((provider) => (
            <a key={provider.slug} className="btn w-full h-9" href={`/api/v1/auth/oidc/${provider.slug}/login`}>
              {t('auth.with', { name: provider.label })}
            </a>
          ))}
        </div>
      ) : null}
    </form>,
  )
}
