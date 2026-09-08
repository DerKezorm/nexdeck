/**
 * Every file this account has uploaded, and what still draws it.
 *
 * ⚠️ Written because there was no way to take a file off the server. The
 * upload quota's own message says "delete a file you no longer need", and the
 * only delete button in the whole interface was the one for icons; the nightly
 * sweeper leaves anything with a row alone on purpose. Files piled up with
 * nothing to say how many, how large, or whether anything still drew them.
 *
 * Deleting one names the cards and boards that would go blank first, so the
 * confirmation is a decision rather than a shrug.
 */
import { useQuery } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, del, get, upload } from '../../api/client'
import { Confirm, Toast } from '../../components/ui'
import { SettingsCard } from './SettingsCard'

export interface Upload {
  id: number
  kind: string
  filename: string
  size: number
  url: string
  created_at: string
  used_by: { what: string; name: string }[]
}

export function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const kb = bytes / 1024
  if (kb < 1024) return `${Math.round(kb)} kB`
  return `${(kb / 1024).toFixed(1)} MB`
}

export function MediaSettings() {
  const { t, i18n } = useTranslation()
  const files = useQuery({ queryKey: ['uploads'], queryFn: () => get<Upload[]>('/assets') })
  const [removing, setRemoving] = useState<Upload | null>(null)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<{ text: string; level: 'ok' | 'error' } | null>(null)
  const rows = files.data ?? []
  const total = rows.reduce((sum, one) => sum + one.size, 0)

  const fail = (why: unknown) =>
    setToast({ text: why instanceof ApiError ? why.message : t('errors.network'), level: 'error' })

  const remove = (one: Upload) => {
    // ⚠️ `anyway` only once the confirmation named what would go blank. The
    // server refuses without it, which is what keeps a second client honest
    // as well.
    void del(`/assets/${one.id}${one.used_by.length ? '?anyway=true' : ''}`)
      .then(() => files.refetch())
      .catch(fail)
  }

  return (
    <>
      <SettingsCard title={t('settings.media.title')} description={t('settings.media.help')}>
        <label className="btn cursor-pointer mb-4 inline-flex">
          {busy ? t('common.loading') : t('settings.media.upload')}
          <input
            type="file"
            accept="image/*"
            className="sr-only"
            aria-label={t('settings.media.upload')}
            disabled={busy}
            onChange={(event) => {
              const chosen = event.target.files?.[0]
              event.target.value = ''
              if (!chosen) return
              setBusy(true)
              upload('/assets', chosen, { kind: 'picture' })
                .then(() => files.refetch())
                .catch(fail)
                .finally(() => setBusy(false))
            }}
          />
        </label>

        {files.isPending && <p className="text-sm text-muted">{t('common.loading')}</p>}
        {rows.length === 0 && !files.isPending && <p className="text-sm text-muted">{t('settings.media.none')}</p>}

        {rows.length > 0 && (
          <>
            <ul className="flex flex-col gap-1.5">
              {rows.map((one) => (
                <li key={one.id} className="flex items-center gap-3 rounded-xl border border-line p-2">
                  <img src={one.url} alt="" className="h-10 w-14 rounded object-cover flex-none bg-elev" />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm truncate">{one.filename}</div>
                    <div className="text-[11px] text-faint">
                      <span className="num">{humanSize(one.size)}</span>
                      {' · '}
                      {new Date(one.created_at).toLocaleDateString(i18n.language)}
                      {' · '}
                      {t(`settings.media.kind.${one.kind}`, { defaultValue: one.kind })}
                    </div>
                  </div>
                  {/* Where it is drawn, or that it is drawn nowhere. Both are
                      worth saying: "nowhere" is the answer that makes deleting
                      an easy decision. */}
                  <span className={`chip !py-0 text-[10px] ${one.used_by.length ? '' : 'text-faint'}`} title={one.used_by.map((where) => where.name).join(', ')}>
                    {one.used_by.length
                      ? t('settings.media.usedBy', { count: one.used_by.length, names: one.used_by.map((where) => where.name).join(', ') })
                      : t('settings.media.unused')}
                  </span>
                  <button
                    className="btn btn-icon h-8 w-8 btn-danger flex-none"
                    aria-label={t('settings.media.remove', { name: one.filename })}
                    title={t('settings.media.remove', { name: one.filename })}
                    onClick={() => setRemoving(one)}
                  >
                    <Trash2 size={14} />
                  </button>
                </li>
              ))}
            </ul>
            <p className="text-[11px] text-faint mt-3">
              {t('settings.media.total', { count: rows.length, size: humanSize(total) })}
            </p>
          </>
        )}
      </SettingsCard>

      <Confirm
        open={removing !== null}
        title={t('settings.media.remove', { name: removing?.filename ?? '' })}
        body={
          removing?.used_by.length
            ? t('settings.media.stillUsed', { names: removing.used_by.map((where) => where.name).join(', ') })
            : t('settings.media.removeHelp')
        }
        confirmLabel={t('common.delete')}
        danger
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          const one = removing
          setRemoving(null)
          if (one) remove(one)
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
