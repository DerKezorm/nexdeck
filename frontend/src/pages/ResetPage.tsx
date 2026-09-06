/**
 * The other end of a reset link. It checks the link before showing a form,
 * because filling in a password twice only to be told the link expired is the
 * worst moment to find out.
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'

import { ApiError, get, post } from '../api/client'
import { BackgroundLayer } from '../components/BackgroundLayer'
import { Logo } from '../components/Logo'
import { Field, PasswordInput } from '../components/ui'

const SHORTEST = 8

export function ResetPage() {
  const { t } = useTranslation()
  const { token = '' } = useParams()
  const navigate = useNavigate()
  const [state, setState] = useState<'checking' | 'ready' | 'stale' | 'done'>('checking')
  const [who, setWho] = useState('')
  const [password, setPassword] = useState('')
  const [again, setAgain] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let dropped = false
    void get<{ valid: boolean; username: string }>(`/auth/reset/${encodeURIComponent(token)}`)
      .then((answer) => {
        if (dropped) return
        setWho(answer.username)
        setState(answer.valid ? 'ready' : 'stale')
      })
      .catch(() => {
        if (!dropped) setState('stale')
      })
    return () => {
      dropped = true
    }
  }, [token])

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await post('/auth/reset', { token, new_password: password })
      setState('done')
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : t('errors.network'))
    } finally {
      setBusy(false)
    }
  }

  const tooShort = password.length > 0 && password.length < SHORTEST
  const mismatch = again.length > 0 && again !== password

  return (
    <div className="min-h-full flex items-center justify-center p-6">
      <BackgroundLayer />
      <div className="glass rounded-2xl p-6 w-full max-w-sm shadow-2xl">
        <div className="flex justify-center mb-6">
          <Logo size={34} />
        </div>
        {state === 'checking' && <p className="text-sm text-muted">{t('common.loading')}</p>}
        {state === 'stale' && (
          <>
            <p className="text-sm text-muted mb-4">{t('auth.reset.stale')}</p>
            <button className="btn w-full h-9" type="button" onClick={() => navigate('/login', { replace: true })}>
              {t('auth.reset.toSignIn')}
            </button>
          </>
        )}
        {state === 'done' && (
          <>
            {/* ⚠️ Worth saying plainly: everything else was signed out. */}
            <p className="text-sm text-muted mb-4">{t('auth.reset.done')}</p>
            <button className="btn btn-accent w-full h-9" type="button" onClick={() => navigate('/login', { replace: true })}>
              {t('auth.reset.toSignIn')}
            </button>
          </>
        )}
        {state === 'ready' && (
          <form onSubmit={submit}>
            <p className="text-sm text-muted mb-4">{t('auth.reset.lead', { name: who })}</p>
            <Field label={t('auth.reset.new')} htmlFor="reset-password" help={t('auth.reset.rule', { count: SHORTEST })}>
              <PasswordInput id="reset-password" autoComplete="new-password" value={password} onChange={setPassword} />
            </Field>
            <Field label={t('auth.reset.again')} htmlFor="reset-again">
              <PasswordInput id="reset-again" autoComplete="new-password" value={again} onChange={setAgain} />
            </Field>
            {(error || tooShort || mismatch) && (
              <p className="text-sm text-bad mb-3" role="alert">
                {error || (tooShort ? t('auth.reset.rule', { count: SHORTEST }) : t('auth.reset.mismatch'))}
              </p>
            )}
            <button className="btn btn-accent w-full h-9" type="submit" disabled={busy || password.length < SHORTEST || again !== password}>
              {t('auth.reset.save')}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
