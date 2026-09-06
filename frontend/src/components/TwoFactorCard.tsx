/**
 * The second factor, from the owner's side of it.
 *
 * ⚠️ The recovery codes are shown once and never again. The card says so
 * before it shows them and keeps them on screen until the person says they
 * have written them down: a dialog that vanishes on the next click is how
 * people end up locked out of their own dashboard.
 */
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, del, get, post } from '../api/client'
import { SettingsCard } from '../pages/settings/SettingsCard'
import { Field, PasswordInput } from './ui'

interface State {
  enabled: boolean
  recovery_codes_left: number
  required_by_operator: boolean
}

export function TwoFactorCard({ hasPassword, onDone }: { hasPassword: boolean; onDone: (text: string, level: 'ok' | 'error') => void }) {
  const { t } = useTranslation()
  const state = useQuery({ queryKey: ['two-factor'], queryFn: () => get<State>('/auth/two-factor') })
  const [setup, setSetup] = useState<{ secret: string; qr_svg: string } | null>(null)
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [codes, setCodes] = useState<string[] | null>(null)
  const [busy, setBusy] = useState(false)

  const failed = (failure: unknown) => onDone(failure instanceof ApiError ? failure.message : t('errors.network'), 'error')
  const done = () => {
    setSetup(null)
    setCode('')
    setPassword('')
    void state.refetch()
  }

  const start = () => {
    setBusy(true)
    void post<{ secret: string; qr_svg: string }>('/auth/two-factor/start')
      .then((answer) => setSetup(answer))
      .catch(failed)
      .finally(() => setBusy(false))
  }

  const confirm = () => {
    setBusy(true)
    void post<{ recovery_codes: string[] }>('/auth/two-factor/confirm', { code: code.trim() })
      .then((answer) => {
        setCodes(answer.recovery_codes)
        done()
      })
      .catch(failed)
      .finally(() => setBusy(false))
  }

  const fresh = () => {
    setBusy(true)
    void post<{ recovery_codes: string[] }>('/auth/two-factor/recovery-codes', { password })
      .then((answer) => {
        setCodes(answer.recovery_codes)
        done()
      })
      .catch(failed)
      .finally(() => setBusy(false))
  }

  const off = () => {
    setBusy(true)
    void del('/auth/two-factor', { password })
      .then(() => {
        onDone(t('settings.twoFactor.switchedOff'), 'ok')
        done()
      })
      .catch(failed)
      .finally(() => setBusy(false))
  }

  const current = state.data
  const few = (current?.recovery_codes_left ?? 0) <= 2

  return (
    <SettingsCard title={t('settings.twoFactor.title')} description={t('settings.twoFactor.help')}>
      {codes && (
        <div className="rounded-lg border border-strong p-3 mb-4">
          <p className="text-sm mb-2">{t('settings.twoFactor.codesLead')}</p>
          <ul className="num grid grid-cols-2 gap-x-4 gap-y-1 text-sm mb-3">
            {codes.map((one) => (
              <li key={one}>{one}</li>
            ))}
          </ul>
          <div className="flex gap-2">
            <button className="btn" type="button" onClick={() => void navigator.clipboard?.writeText(codes.join('\n'))}>
              {t('common.copy')}
            </button>
            <button className="btn btn-accent" type="button" onClick={() => setCodes(null)}>
              {t('settings.twoFactor.codesKept')}
            </button>
          </div>
        </div>
      )}

      {!current ? (
        <p className="text-sm text-muted">{t('common.loading')}</p>
      ) : setup ? (
        <div className="flex flex-wrap items-start gap-5">
          <div className="rounded-lg bg-white p-2 leading-none" dangerouslySetInnerHTML={{ __html: setup.qr_svg }} />
          <div className="min-w-[16rem] flex-1">
            <p className="text-sm text-muted mb-2">{t('settings.twoFactor.scan')}</p>
            <p className="num text-xs text-faint break-all mb-3">{setup.secret}</p>
            <Field label={t('settings.twoFactor.enterCode')} htmlFor="tf-code">
              <input id="tf-code" className="input num" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} />
            </Field>
            <div className="flex gap-2">
              <button className="btn btn-accent" type="button" disabled={busy || code.trim().length < 6} onClick={confirm}>
                {t('settings.twoFactor.switchOn')}
              </button>
              <button className="btn" type="button" onClick={done}>
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>
      ) : current.enabled ? (
        <>
          <p className="text-sm mb-1">
            {t('settings.twoFactor.on')}
            {' · '}
            <span className={few ? 'text-warn' : 'text-muted'}>{t('settings.twoFactor.left', { count: current.recovery_codes_left })}</span>
          </p>
          {current.required_by_operator && <p className="text-[12px] text-faint mb-3">{t('settings.twoFactor.demanded')}</p>}
          {hasPassword && (
            <Field label={t('settings.twoFactor.confirmWithPassword')} htmlFor="tf-pass">
              <PasswordInput id="tf-pass" autoComplete="current-password" value={password} onChange={setPassword} />
            </Field>
          )}
          <div className="flex flex-wrap gap-2">
            <button className="btn" type="button" disabled={busy || (hasPassword && !password)} onClick={fresh}>
              {t('settings.twoFactor.newCodes')}
            </button>
            <button className="btn btn-danger" type="button" disabled={busy || current.required_by_operator || (hasPassword && !password)} onClick={off}>
              {t('settings.twoFactor.switchOff')}
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="text-sm text-muted mb-3">{current.required_by_operator ? t('settings.twoFactor.demandedOff') : t('settings.twoFactor.off')}</p>
          <button className="btn btn-accent" type="button" disabled={busy} onClick={start}>
            {t('settings.twoFactor.setUp')}
          </button>
        </>
      )}
    </SettingsCard>
  )
}
