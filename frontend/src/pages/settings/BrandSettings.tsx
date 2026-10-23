import { useQuery } from '@tanstack/react-query'
import { ImageUp, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, ApiError, del, get, put, serverUrl } from '../../api/client'
import { LogoMark } from '../../components/Logo'
import { Field, Switch, Toast } from '../../components/ui'
import { applyBrand, NO_BRAND, tabTitle, type Brand } from '../../lib/brand'
import { SettingsCard } from './SettingsCard'

type Source = 'logo' | 'nexdeck'
interface Stored {
  name: string
  logo: string
  favicon: Source
  app_icon: Source
  board_in_title: boolean
  urls: Brand
}

/** The two sizes an installed app asks for. */
const ICON_SIZES = [192, 512] as const

/**
 * An app icon drawn from the logo: the logo in the middle of nexdeck's dark
 * ground, with room around it for the rounding a phone puts on every icon.
 *
 * ⚠️ Drawn here and not on the server: the server cannot draw an SVG, and a
 * home screen does not take one.
 */
export async function drawIcon(file: Blob, size: number): Promise<Blob> {
  const address = URL.createObjectURL(file)
  try {
    const picture = new Image()
    picture.src = address
    await picture.decode()
    const canvas = document.createElement('canvas')
    canvas.width = size
    canvas.height = size
    const pen = canvas.getContext('2d')
    if (!pen) throw new Error('no canvas')
    pen.fillStyle = '#0a0d12'
    pen.fillRect(0, 0, size, size)
    // An SVG without a size of its own reports none; it is drawn square.
    const width = picture.naturalWidth || size
    const height = picture.naturalHeight || size
    const room = size * 0.7
    const scale = Math.min(room / width, room / height)
    pen.drawImage(picture, (size - width * scale) / 2, (size - height * scale) / 2, width * scale, height * scale)
    return await new Promise<Blob>((done, fail) => canvas.toBlob((blob) => (blob ? done(blob) : fail(new Error('no png'))), 'image/png'))
  } finally {
    URL.revokeObjectURL(address)
  }
}

/** Name and logo of the installation, for the tab, the bar, the sign-in page and the installed app. */
export function BrandSettings() {
  const { t } = useTranslation()
  const saved = useQuery({ queryKey: ['brand-settings'], queryFn: () => get<Stored>('/settings/brand') })
  const [form, setForm] = useState({ name: '', favicon: 'logo' as Source, app_icon: 'logo' as Source, board_in_title: true })
  const [logo, setLogo] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<{ text: string; level: 'ok' | 'error' } | null>(null)
  const chooser = useRef<HTMLInputElement>(null)

  // ⚠️ Filled once. Refilled on every answer, a logo uploaded while a new
  // name was typed but not saved put the old name back into the field.
  const filled = useRef(false)
  useEffect(() => {
    if (!saved.data || filled.current) return
    filled.current = true
    setForm({ name: saved.data.name, favicon: saved.data.favicon, app_icon: saved.data.app_icon, board_in_title: saved.data.board_in_title })
    setLogo(saved.data.urls.logo)
  }, [saved.data])

  const took = (answer: Stored, text: string) => {
    applyBrand({ ...NO_BRAND, ...answer.urls })
    setLogo(answer.urls.logo)
    setToast({ text, level: 'ok' })
  }
  const failed = (failure: unknown) => setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' })

  const store = async () => {
    try {
      const answer = await put<Stored>('/settings/brand', form)
      setForm({ name: answer.name, favicon: answer.favicon, app_icon: answer.app_icon, board_in_title: answer.board_in_title })
      took(answer, t('common.saved'))
    } catch (failure) {
      failed(failure)
    }
  }

  const send = async (file: File) => {
    setBusy(true)
    try {
      const body = new FormData()
      body.append('logo', file)
      for (const size of ICON_SIZES) {
        let icon: Blob
        try {
          icon = await drawIcon(file, size)
        } catch {
          setToast({ text: t('settings.brand.unreadable'), level: 'error' })
          return
        }
        body.append(`icon${size}`, icon, `icon-${size}.png`)
      }
      took(await api<Stored>('/settings/brand/logo', { method: 'POST', body }), t('settings.brand.uploaded'))
    } catch (failure) {
      failed(failure)
    } finally {
      setBusy(false)
      if (chooser.current) chooser.current.value = ''
    }
  }

  const drop = async () => {
    try {
      took(await del<Stored>('/settings/brand/logo'), t('settings.brand.removed'))
    } catch (failure) {
      failed(failure)
    }
  }

  if (!saved.data) return null
  const name = form.name.trim()
  const mark = (size: number, source: Source = 'logo') =>
    logo && source === 'logo' ? <img src={serverUrl(logo)} alt="" className="object-contain" style={{ width: size, height: size }} /> : <LogoMark size={size} />

  return (
    <SettingsCard title={t('settings.brand.title')} description={t('settings.brand.help')}>
      <div className="grid lg:grid-cols-[minmax(0,1fr)_minmax(0,20rem)] gap-6">
        <div>
          <Field label={t('settings.brand.name')} htmlFor="b-name" help={t('settings.brand.nameHelp')}>
            <input id="b-name" className="input" maxLength={40} placeholder="nexdeck" value={form.name} onChange={(e) => setForm((current) => ({ ...current, name: e.target.value }))} />
          </Field>

          <Field label={t('settings.brand.logo')} help={t('settings.brand.logoHelp')}>
            <div className="flex flex-wrap items-center gap-3">
              <span className="grid place-items-center w-12 h-12 rounded-xl border border-line bg-surface">{mark(32)}</span>
              <input
                ref={chooser}
                type="file"
                accept="image/svg+xml,image/png,image/webp"
                className="sr-only"
                id="b-logo"
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  if (file) void send(file)
                }}
              />
              <label htmlFor="b-logo" className={`btn ${busy ? 'opacity-60 pointer-events-none' : ''}`}>
                <ImageUp size={15} /> {t('settings.brand.choose')}
              </label>
              {logo && (
                <button className="btn" onClick={() => void drop()}>
                  <Trash2 size={15} /> {t('settings.brand.remove')}
                </button>
              )}
            </div>
          </Field>

          <Field label={t('settings.brand.favicon')}>
            <div className="grid gap-1.5" role="radiogroup" aria-label={t('settings.brand.favicon')}>
              {(['logo', 'nexdeck'] as const).map((source) => (
                <label key={source} className="flex items-center gap-2 text-sm">
                  <input type="radio" name="b-favicon" checked={form.favicon === source} onChange={() => setForm((current) => ({ ...current, favicon: source }))} />
                  {t(`settings.brand.favicon_${source}`)}
                </label>
              ))}
            </div>
          </Field>

          <Field label={t('settings.brand.appIcon')} help={t('settings.brand.appIconHelp')}>
            <div className="grid gap-1.5" role="radiogroup" aria-label={t('settings.brand.appIcon')}>
              {(['logo', 'nexdeck'] as const).map((source) => (
                <label key={source} className="flex items-center gap-2 text-sm">
                  <input type="radio" name="b-app" checked={form.app_icon === source} onChange={() => setForm((current) => ({ ...current, app_icon: source }))} />
                  {t(`settings.brand.appIcon_${source}`)}
                </label>
              ))}
            </div>
          </Field>

          <Switch
            checked={form.board_in_title}
            onChange={(board_in_title) => setForm((current) => ({ ...current, board_in_title }))}
            label={t('settings.brand.boardInTitle')}
          />

          <button className="btn btn-accent mt-4" onClick={() => void store()}>
            {t('common.save')}
          </button>
        </div>

        {/* What it will look like: the tab, the bar and the home screen. */}
        <div className="grid gap-3 content-start" aria-hidden="true">
          <p className="text-xs text-muted uppercase tracking-wide">{t('settings.brand.preview')}</p>
          <div className="rounded-xl border border-line overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-2 text-xs bg-surface">
              <span className="shrink-0 grid place-items-center">{mark(14, form.favicon)}</span>
              <span className="truncate">{tabTitle({ ...NO_BRAND, name, board_in_title: form.board_in_title }, t('settings.brand.sampleBoard'))}</span>
            </div>
            <div className="flex items-center gap-2 px-3 py-2.5 border-t border-line">
              {mark(22)}
              <span className="font-semibold truncate" data-preview-name>
                {name || (
                  <>
                    nex<span className="text-accent">deck</span>
                  </>
                )}
              </span>
            </div>
          </div>
          <div className="flex items-end gap-4">
            <span className="grid justify-items-center gap-1 text-[11px] text-muted">
              <span className="grid place-items-center w-14 h-14 rounded-[14px] bg-[#0a0d12] overflow-hidden">{mark(36, form.app_icon)}</span>
              <span className="truncate max-w-20">{name || 'nexdeck'}</span>
            </span>
          </div>
        </div>
      </div>
      {toast && (
        <Toast level={toast.level} onClose={() => setToast(null)}>
          {toast.text}
        </Toast>
      )}
    </SettingsCard>
  )
}
