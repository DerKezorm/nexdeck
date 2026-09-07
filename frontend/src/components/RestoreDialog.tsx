/**
 * Putting a backup back: look first, replace second.
 *
 * ⚠️ **Two steps, not one.** Restoring swaps the whole installation. Whoever
 * presses the button should have seen what they are about to put back: which
 * version, from when, with which note. The first step reads and changes
 * nothing.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, api } from '../api/client'
import { Dialog, Field, PasswordInput } from './ui'

interface Verdict {
  version: string
  created_at: string
  kind: string
  note: string
  contains: string[]
  restorable: boolean
  reason: string
  key_inside: boolean
  key_from_env: boolean
}

/**
 * Which warning about the key applies, if any.
 *
 * ⚠️ **Two questions, not one.** Whether the archive brings a key, and
 * whether this installation would ignore it because the variable is set. The
 * worst combination is "no key in the archive and no variable here": nexdeck
 * makes a new one, and afterwards not a single stored credential can be read,
 * with nothing pointing at the key as the cause.
 */
function keyWarning(verdict: Verdict): { text: string; heavy: boolean } | null {
  if (!verdict.key_inside) {
    return verdict.key_from_env
      ? { text: 'backups.restore.keyOnlyFromEnv', heavy: false }
      : { text: 'backups.restore.noKeyAtAll', heavy: true }
  }
  return verdict.key_from_env ? { text: 'backups.restore.envKeyWins', heavy: false } : null
}

export function RestoreDialog({ open, onClose, username, onDone }: {
  open: boolean
  onClose: () => void
  username: string
  onDone: () => void
}) {
  const { t } = useTranslation()
  const [file, setFile] = useState<File | null>(null)
  const [password, setPassword] = useState('')
  const [verdict, setVerdict] = useState<Verdict | null>(null)
  const [confirm, setConfirm] = useState('')
  const [anyway, setAnyway] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const reset = () => {
    setFile(null)
    setPassword('')
    setVerdict(null)
    setConfirm('')
    setError('')
    setBusy(false)
  }

  const close = () => {
    reset()
    onClose()
  }

  const body = (extra: Record<string, string> = {}) => {
    const form = new FormData()
    form.append('file', file as File)
    form.append('password', password)
    for (const [key, value] of Object.entries(extra)) form.append(key, value)
    return form
  }

  const look = async () => {
    setBusy(true)
    setError('')
    try {
      setVerdict(await api<Verdict>('/backups/inspect', { method: 'POST', body: body() }))
    } catch (failure) {
      setVerdict(null)
      setError(failure instanceof ApiError ? failure.message : t('errors.network'))
    } finally {
      setBusy(false)
    }
  }

  const put = async () => {
    setBusy(true)
    setError('')
    try {
      await api('/backups/restore', { method: 'POST', body: body({ confirm, without_safety_copy: anyway ? 'true' : 'false' }) })
      onDone()
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : t('errors.network'))
      setBusy(false)
    }
  }

  const warning = verdict ? keyWarning(verdict) : null
  const ready = verdict?.restorable === true && confirm.trim() === username

  return (
    <Dialog
      open={open}
      onClose={close}
      title={t('backups.restore.title')}
      size="lg"
      footer={
        <>
          <button className="btn" type="button" onClick={close}>
            {t('common.cancel')}
          </button>
          {verdict ? (
            <button className="btn btn-danger" type="button" disabled={busy || !ready} onClick={put}>
              {t('backups.restore.go')}
            </button>
          ) : (
            <button className="btn btn-accent" type="button" disabled={busy || !file || !password} onClick={look}>
              {t('backups.restore.look')}
            </button>
          )}
        </>
      }
    >
      <p className="text-sm text-muted mb-4">{t('backups.restore.lead')}</p>

      <Field label={t('backups.restore.file')} htmlFor="restore-file">
        <input
          id="restore-file"
          type="file"
          accept=".zip,application/zip"
          className="input"
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null)
            setVerdict(null)
            setError('')
          }}
        />
      </Field>
      <Field label={t('backups.restore.password')} htmlFor="restore-password">
        <PasswordInput
          id="restore-password"
          autoComplete="new-password"
          value={password}
          onChange={(value) => {
            setPassword(value)
            setVerdict(null)
          }}
        />
      </Field>

      {verdict && (
        <div className="rounded-lg border border-strong p-3 mb-3 text-sm">
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
            <dt className="text-muted">{t('backups.list.created')}</dt>
            <dd className="num">{verdict.created_at ? new Date(verdict.created_at).toLocaleString() : '?'}</dd>
            <dt className="text-muted">{t('backups.list.version')}</dt>
            <dd className="num">{verdict.version}</dd>
            {verdict.note && (
              <>
                <dt className="text-muted">{t('backups.list.note')}</dt>
                <dd>{verdict.note}</dd>
              </>
            )}
            <dt className="text-muted">{t('backups.restore.contains')}</dt>
            <dd>{t('backups.restore.fileCount', { count: verdict.contains.length })}</dd>
          </dl>
          {!verdict.restorable && (
            <p className="text-sm text-bad mt-2">{t(`backups.reason.${verdict.reason}`, { defaultValue: verdict.reason })}</p>
          )}
          {warning && <p className={`text-sm mt-2 ${warning.heavy ? 'text-bad' : 'text-warn'}`}>{t(warning.text)}</p>}
        </div>
      )}

      {verdict?.restorable && (
        <>
          {/* ⚠️ Not a checkbox. A checkbox is one careless click, and this is
              the one action that cannot be undone from inside nexdeck. */}
          <p className="text-sm text-bad mb-2">{t('backups.restore.warning')}</p>
          <Field label={t('backups.restore.confirm', { name: username })} htmlFor="restore-confirm">
            <input id="restore-confirm" className="input" autoComplete="off" value={confirm} onChange={(event) => setConfirm(event.target.value)} />
          </Field>
          {/* The way through for the case the copy is what is broken: since
              07.09.2026 a restore stops when the safety copy of the current
              state cannot be written, and the reason for restoring may well be
              that the current database is past saving. */}
          <label className="flex items-start gap-2 text-xs text-muted mt-2">
            <input type="checkbox" className="mt-0.5" checked={anyway} onChange={(event) => setAnyway(event.target.checked)} />
            <span>{t('backups.restore.withoutSafetyCopy')}</span>
          </label>
        </>
      )}

      {error && (
        <p className="text-sm text-bad" role="alert">
          {error}
        </p>
      )}
    </Dialog>
  )
}
