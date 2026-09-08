/**
 * The pictures of a picture card: upload them, or name an address.
 *
 * ⚠️ Both, in one list. It shipped as a text field with one line per picture,
 * which is fine for somebody who already has the addresses and useless for
 * somebody with a photo on their disk. An address is still allowed, because a
 * camera snapshot or a chart from another service has one and uploading it
 * would mean uploading it again every time it changes.
 */
import { Menu, Trash2 } from 'lucide-react'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useQuery } from '@tanstack/react-query'

import { ApiError, get, upload } from '../api/client'
import { safeUrl } from '../lib/safeUrl'
import { useHandleReorder } from '../lib/useHandleReorder'
import { Dialog, Field } from './ui'

export interface Picture {
  url: string
  caption?: string
}

/** What the field holds, whatever shape it was written in before. */
export function asPictures(value: unknown): Picture[] {
  if (Array.isArray(value)) {
    return value
      .filter((one): one is Record<string, unknown> => Boolean(one) && typeof one === 'object')
      .map((one) => ({ url: String(one.url ?? ''), caption: String(one.caption ?? one.title ?? '') }))
      .filter((one) => one.url)
  }
  // ⚠️ The shape this field used before the picker existed. A card filled in
  // then must not lose its pictures the day the field changed.
  return String(value ?? '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [url, caption] = line.split('|')
      return { url: url.trim(), caption: (caption ?? '').trim() }
    })
    .filter((one) => one.url)
}

export function PicturePicker({ value, onChange, label, help }: {
  value: unknown
  onChange: (value: unknown) => void
  label: string
  help?: string
}) {
  const { t } = useTranslation()
  const pictures = asPictures(value)
  const [address, setAddress] = useState('')
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState('')
  const [browsing, setBrowsing] = useState(false)
  const file = useRef<HTMLInputElement>(null)
  //: What is already on this server. ⚠️ Only asked for once the library is
  //: opened: on a board being edited it would otherwise be a request per
  //: settings sheet for a list most people never look at.
  const library = useQuery({
    queryKey: ['uploads'],
    queryFn: () => get<{ id: number; filename: string; url: string }[]>('/assets'),
    enabled: browsing,
  })

  const put = (next: Picture[]) => onChange(next)
  const order = useHandleReorder(pictures, (one) => one.url, put)

  const take = (chosen: File) => {
    setFailed('')
    setBusy(true)
    upload('/assets', chosen, { kind: 'picture' })
      .then((asset) => put([...pictures, { url: (asset as { url: string }).url, caption: '' }]))
      .catch((why) => setFailed(why instanceof ApiError ? why.message : t('errors.network')))
      .finally(() => setBusy(false))
  }

  const addAddress = () => {
    const url = safeUrl(address.trim())
    if (!url) {
      setFailed(t('widget.pictureBadAddress'))
      return
    }
    setFailed('')
    setAddress('')
    put([...pictures, { url, caption: '' }])
  }

  return (
    <Field label={label} help={help}>
      {pictures.length > 0 && (
        <ul className="flex flex-col gap-1.5 mb-2">
          {order.rows.map((one, index) => (
            <li
              key={one.url}
              ref={order.rowRef(one.url)}
              className={`flex items-center gap-2 rounded-lg border p-1.5 ${order.holding === one.url ? 'border-accent bg-surface-hover' : 'border-line'}`}
            >
              <button
                type="button"
                className="btn btn-icon h-7 w-7 border-0 bg-transparent cursor-grab touch-none active:cursor-grabbing"
                aria-label={t('widget.pictureMove', { at: index + 1 })}
                title={t('widget.pictureMove', { at: index + 1 })}
                {...order.handleProps(one.url)}
              >
                <Menu size={14} />
              </button>
              <img src={one.url} alt="" className="h-9 w-12 rounded object-cover flex-none bg-elev" />
              <input
                className="input flex-1 !py-1 text-[12px]"
                value={one.caption ?? ''}
                placeholder={t('widget.pictureCaption')}
                aria-label={t('widget.pictureCaptionOf', { at: index + 1 })}
                onChange={(event) =>
                  put(order.rows.map((other) => (other.url === one.url ? { ...other, caption: event.target.value } : other)))
                }
              />
              <button
                type="button"
                className="btn btn-icon h-7 w-7 btn-danger flex-none"
                aria-label={t('widget.pictureRemove', { at: index + 1 })}
                title={t('widget.pictureRemove', { at: index + 1 })}
                onClick={() => put(order.rows.filter((other) => other.url !== one.url))}
              >
                <Trash2 size={13} />
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <label className="btn cursor-pointer">
          {busy ? t('common.loading') : t('widget.pictureUpload')}
          <input
            ref={file}
            type="file"
            accept="image/*"
            className="sr-only"
            aria-label={t('widget.pictureUpload')}
            disabled={busy}
            onChange={(event) => {
              const chosen = event.target.files?.[0]
              event.target.value = ''
              if (chosen) take(chosen)
            }}
          />
        </label>
        <input
          className="input flex-1 min-w-[10rem] !py-1.5 text-[13px]"
          value={address}
          placeholder="https://example.com/picture.jpg"
          aria-label={t('widget.pictureAddress')}
          onChange={(event) => setAddress(event.target.value)}
          onKeyDown={(event) => {
            if (event.key !== 'Enter') return
            event.preventDefault()
            addAddress()
          }}
        />
        <button type="button" className="btn" disabled={!address.trim()} onClick={addAddress}>
          {t('widget.pictureAdd')}
        </button>
        <button type="button" className="btn" onClick={() => setBrowsing(true)}>
          {t('widget.pictureLibrary')}
        </button>
      </div>
      {failed && (
        <p className="text-[12px] text-bad mt-1" role="alert">
          {failed}
        </p>
      )}

      {/* ⚠️ Uploading is not the only way to get a picture onto a card. The
          same file often belongs on two of them, and uploading it again made
          a second copy that counted against the quota twice. */}
      <Dialog open={browsing} onClose={() => setBrowsing(false)} title={t('widget.pictureLibrary')}>
        {library.isPending && <p className="text-sm text-muted">{t('common.loading')}</p>}
        {library.isSuccess && (library.data ?? []).length === 0 && (
          <p className="text-sm text-muted">{t('widget.pictureLibraryEmpty')}</p>
        )}
        <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
          {(library.data ?? []).map((one) => {
            const already = pictures.some((other) => other.url === one.url)
            return (
              <button
                key={one.id}
                type="button"
                className={`rounded-lg border p-1 text-left ${already ? 'border-accent bg-accent-soft' : 'border-line hover:bg-surface-hover'}`}
                aria-pressed={already}
                title={one.filename}
                onClick={() => {
                  if (!already) put([...pictures, { url: one.url, caption: '' }])
                  setBrowsing(false)
                }}
              >
                <img src={one.url} alt="" className="h-16 w-full rounded object-cover bg-elev" />
                <span className="block truncate text-[10px] text-muted mt-1">{one.filename}</span>
              </button>
            )
          })}
        </div>
      </Dialog>
    </Field>
  )
}
