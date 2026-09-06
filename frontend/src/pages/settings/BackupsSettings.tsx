/**
 * Backups: write one, carry one off the machine, put one back.
 *
 * ⚠️ **The button that matters is "Download".** The copies nexdeck writes by
 * itself sit in the same directory as the database, so on the same volume;
 * when that dies they die together. They are a restore point for a bad
 * migration, not a backup. It becomes a backup when it leaves the machine.
 */
import { useQuery } from '@tanstack/react-query'
import { Download, HardDriveDownload, Plus, Trash2, Upload } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, del, downloadPost, get, post } from '../../api/client'
import { RestoreDialog } from '../../components/RestoreDialog'
import { Confirm, Dialog, EmptyState, Field, PasswordInput, Spinner, Toast } from '../../components/ui'
import { useAuth } from '../../stores/auth'
import { SettingsCard } from './SettingsCard'

interface Entry {
  name: string
  size: number
  created_at: string
  kind: 'automatic' | 'manual'
  note: string
  version: string
  restorable: boolean
  reason: string
}

interface Listing {
  entries: Entry[]
  folder: string
  keep_automatic: number
}

const SHORTEST = 8

function size(bytes: number): string {
  if (bytes >= 1048576) return `${(bytes / 1048576).toFixed(1)} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} kB`
}

export function BackupsSettings() {
  const { t } = useTranslation()
  const username = useAuth((state) => state.user?.username ?? '')
  const listing = useQuery({ queryKey: ['backups'], queryFn: () => get<Listing>('/backups') })

  const [making, setMaking] = useState(false)
  const [note, setNote] = useState('')
  const [fetching, setFetching] = useState<Entry | null>(null)
  const [password, setPassword] = useState('')
  const [again, setAgain] = useState('')
  const [dropping, setDropping] = useState<Entry | null>(null)
  const [restoring, setRestoring] = useState(false)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<{ text: string; level: 'ok' | 'error' } | null>(null)

  const failed = (failure: unknown) => setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' })

  const make = () => {
    setBusy(true)
    void post('/backups', { note: note.trim() })
      .then(() => {
        setMaking(false)
        setNote('')
        setToast({ text: t('backups.made'), level: 'ok' })
        return listing.refetch()
      })
      .catch(failed)
      .finally(() => setBusy(false))
  }

  const download = () => {
    if (!fetching) return
    setBusy(true)
    void downloadPost(`/backups/${encodeURIComponent(fetching.name)}/archive`, fetching.name.replace(/\.db$/, '.zip'), { password })
      .then(() => {
        setFetching(null)
        setPassword('')
        setAgain('')
      })
      .catch(failed)
      .finally(() => setBusy(false))
  }

  const drop = () => {
    if (!dropping) return
    void del(`/backups/${encodeURIComponent(dropping.name)}`)
      .then(() => {
        setDropping(null)
        return listing.refetch()
      })
      .catch(failed)
  }

  const matching = password.length >= SHORTEST && password === again
  const entries = listing.data?.entries ?? []

  return (
    <>
      <SettingsCard title={t('backups.title')} description={t('backups.help')}>
        <div className="flex flex-wrap gap-2">
          <button className="btn btn-accent" type="button" onClick={() => setMaking(true)}>
            <Plus size={15} /> {t('backups.make')}
          </button>
          <button className="btn" type="button" onClick={() => setRestoring(true)}>
            <Upload size={15} /> {t('backups.restore.open')}
          </button>
        </div>
        {listing.data && (
          <p className="text-[11px] text-faint mt-3 num break-all">
            {listing.data.folder}
          </p>
        )}
      </SettingsCard>

      <SettingsCard title={t('backups.listTitle')} description={t('backups.listHelp', { count: listing.data?.keep_automatic ?? 5 })}>
        {listing.isPending && <Spinner />}
        {!listing.isPending && entries.length === 0 && (
          <EmptyState title={t('backups.empty')} body={t('backups.emptyBody')} />
        )}
        {entries.length > 0 && (
          <ul className="divide-y divide-line">
            {entries.map((entry) => (
              <li key={entry.name} className="py-2.5 flex flex-wrap items-center gap-x-3 gap-y-1">
                <div className="min-w-0 flex-1">
                  <div className="text-sm flex items-center gap-2 flex-wrap">
                    <span className="num">{entry.created_at ? new Date(entry.created_at).toLocaleString() : entry.name}</span>
                    <span className="chip">{t(`backups.kind.${entry.kind}`)}</span>
                    {!entry.restorable && (
                      <span className="chip text-warn">{t(`backups.reason.${entry.reason}`, { defaultValue: entry.reason })}</span>
                    )}
                  </div>
                  <div className="text-[11px] text-muted truncate">
                    {entry.note ? `${entry.note} · ` : ''}
                    <span className="num">{entry.version}</span>
                    {' · '}
                    <span className="num">{size(entry.size)}</span>
                  </div>
                </div>
                <button className="btn btn-xs" type="button" onClick={() => setFetching(entry)} title={t('common.download')}>
                  <Download size={14} /> {t('common.download')}
                </button>
                <button className="btn btn-xs btn-danger" type="button" onClick={() => setDropping(entry)} title={t('common.delete')}>
                  <Trash2 size={14} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </SettingsCard>

      <Dialog
        open={making}
        onClose={() => setMaking(false)}
        title={t('backups.make')}
        footer={
          <>
            <button className="btn" type="button" onClick={() => setMaking(false)}>
              {t('common.cancel')}
            </button>
            <button className="btn btn-accent" type="button" disabled={busy} onClick={make}>
              {t('backups.make')}
            </button>
          </>
        }
      >
        <p className="text-sm text-muted mb-3">{t('backups.makeLead')}</p>
        <Field label={t('backups.note')} htmlFor="backup-note" help={t('backups.noteHelp')}>
          <input id="backup-note" className="input" value={note} maxLength={200} onChange={(event) => setNote(event.target.value)} />
        </Field>
      </Dialog>

      <Dialog
        open={fetching !== null}
        onClose={() => {
          setFetching(null)
          setPassword('')
          setAgain('')
        }}
        title={t('backups.download.title')}
        footer={
          <>
            <button className="btn" type="button" onClick={() => { setFetching(null); setPassword(''); setAgain('') }}>
              {t('common.cancel')}
            </button>
            <button className="btn btn-accent" type="button" disabled={busy || !matching} onClick={download}>
              <HardDriveDownload size={15} /> {t('common.download')}
            </button>
          </>
        }
      >
        {/* ⚠️ Said before the field, not after it. The archive carries
            secret.key, so the file hands over every service credential of the
            installation. Somebody who does not know that picks a weak one. */}
        <p className="text-sm text-muted mb-3">{t('backups.download.lead')}</p>
        <Field label={t('backups.download.password')} htmlFor="archive-password" help={t('backups.download.rule', { count: SHORTEST })}>
          <PasswordInput id="archive-password" autoComplete="new-password" value={password} onChange={setPassword} />
        </Field>
        <Field label={t('backups.download.again')} htmlFor="archive-again">
          <PasswordInput id="archive-again" autoComplete="new-password" value={again} onChange={setAgain} />
        </Field>
        {again.length > 0 && again !== password && <p className="text-sm text-warn">{t('auth.reset.mismatch')}</p>}
        <p className="text-[12px] text-warn">{t('backups.download.lost')}</p>
      </Dialog>

      <Confirm
        open={dropping !== null}
        title={t('backups.dropTitle')}
        body={t('backups.dropBody')}
        danger
        onCancel={() => setDropping(null)}
        onConfirm={drop}
      />

      <RestoreDialog
        open={restoring}
        username={username}
        onClose={() => setRestoring(false)}
        onDone={() => window.location.assign('/login')}
      />

      {toast && (
        <Toast level={toast.level} onClose={() => setToast(null)}>
          {toast.text}
        </Toast>
      )}
    </>
  )
}
