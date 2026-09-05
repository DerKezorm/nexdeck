import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, useNavigate } from 'react-router-dom'

import { ApiError, post } from '../api/client'
import type { User } from '../api/types'
import { BackgroundLayer } from '../components/BackgroundLayer'
import { Logo } from '../components/Logo'
import { Field, Select, Switch } from '../components/ui'
import { LANGUAGES, setLanguage } from '../i18n'
import { applyTheme, useAuth } from '../stores/auth'

/** The first start: administrator, language, look, and a demo or a real Docker host. */
export function SetupPage() {
  const { t, i18n } = useTranslation()
  const { status, loading, refresh } = useAuth()
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [locale, setLocale] = useState(i18n.language)
  const [theme, setTheme] = useState<'dark' | 'light'>('dark')
  const [demo, setDemo] = useState(true)
  const [dockerHost, setDockerHost] = useState('unix:///var/run/docker.sock')
  const [useDocker, setUseDocker] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  if (!loading && status && !status.needs_setup) return <Navigate to="/" replace />

  const finish = async () => {
    setBusy(true)
    setError('')
    try {
      const user = await post<User>('/setup', { username: username.trim(), password, display_name: displayName.trim(), locale, demo, docker_host: useDocker && !demo ? dockerHost.trim() : '' })
      applyTheme(theme)
      await refresh()
      navigate(user.start_board_id ? '/' : '/settings/boards', { replace: true })
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : t('errors.network'))
    } finally {
      setBusy(false)
    }
  }

  const steps = [t('setup.step.account'), t('setup.step.look'), t('setup.step.start')]

  return (
    <div className="min-h-full flex items-center justify-center p-6">
      <BackgroundLayer />
      <div className="glass rounded-2xl p-6 w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between mb-5">
          <Logo size={30} />
          <span className="text-xs text-muted num">
            {step + 1} / {steps.length}
          </span>
        </div>
        <h1 className="text-lg font-semibold mb-1">{steps[step]}</h1>
        <p className="text-sm text-muted mb-5">{t(`setup.intro.${step}`)}</p>

        {step === 0 && (
          <>
            <Field label={t('auth.username')} htmlFor="su-user">
              <input id="su-user" className="input" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
            </Field>
            <Field label={t('auth.password')} htmlFor="su-pass">
              <input id="su-pass" className="input" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
              <p className={`text-[11px] mt-1 ${password.length > 0 && password.length < 8 ? 'text-warn' : 'text-faint'}`}>
                {password.length > 0 && password.length < 8 ? t('setup.passwordShort', { missing: 8 - password.length }) : t('setup.passwordHelp')}
              </p>
            </Field>
            <Field label={t('settings.profile.displayName')} htmlFor="su-name">
              <input id="su-name" className="input" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
            </Field>
          </>
        )}

        {step === 1 && (
          <>
            <Field label={t('settings.profile.language')} htmlFor="su-lang">
              <Select
                id="su-lang"
                value={locale}
                onChange={(value) => {
                  setLocale(value)
                  void setLanguage(value)
                }}
                options={Object.entries(LANGUAGES).map(([value, label]) => ({ value, label }))}
              />
            </Field>
            <Field label={t('settings.profile.theme')}>
              <div className="grid grid-cols-2 gap-2">
                {(['dark', 'light'] as const).map((option) => (
                  <button
                    key={option}
                    type="button"
                    className="btn h-14 flex-col gap-1"
                    aria-pressed={theme === option}
                    onClick={() => {
                      setTheme(option)
                      applyTheme(option)
                    }}
                  >
                    <span className={`w-8 h-4 rounded ${option === 'dark' ? 'bg-[#0a0d12] border border-white/20' : 'bg-white border border-black/10'}`} />
                    <span className="text-xs">{t(`settings.profile.theme_${option}`)}</span>
                  </button>
                ))}
              </div>
            </Field>
          </>
        )}

        {step === 2 && (
          <>
            <Switch checked={demo} onChange={setDemo} label={t('setup.demo.label')} description={t('setup.demo.help')} />
            {!demo && (
              <>
                <Switch checked={useDocker} onChange={setUseDocker} label={t('setup.docker.label')} description={t('setup.docker.help')} />
                {useDocker && (
                  <Field label={t('setup.docker.host')} htmlFor="su-docker" help={t('setup.docker.hostHelp')}>
                    <input id="su-docker" className="input font-mono text-xs" value={dockerHost} onChange={(e) => setDockerHost(e.target.value)} />
                  </Field>
                )}
              </>
            )}
          </>
        )}

        {error && (
          <p className="text-sm text-bad mt-2" role="alert">
            {error}
          </p>
        )}

        <div className="flex justify-between mt-6">
          <button className="btn" disabled={step === 0} onClick={() => setStep((s) => s - 1)}>
            {t('common.back')}
          </button>
          {step < steps.length - 1 ? (
            <button className="btn btn-accent" disabled={step === 0 && (!username.trim() || password.length < 8)} onClick={() => setStep((s) => s + 1)}>
              {t('common.next')}
            </button>
          ) : (
            <button className="btn btn-accent" disabled={busy} onClick={finish}>
              {t('setup.finish')}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
