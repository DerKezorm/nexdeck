import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, get, put } from '../../api/client'
import { Field, Toast } from '../../components/ui'
import { accentVariables, applyAppearance, type Appearance } from '../../lib/appearance'
import { SettingsCard } from './SettingsCard'

const EMPTY: Appearance = { preset: 'cyan', accent: '', css: '', colour: '#22d3ee', presets: {} }

/**
 * The look of the whole installation: one accent colour and, for whoever
 * wants it, a style sheet of their own.
 *
 * What is typed here is painted on at once, before it is saved, because a
 * colour is nothing to judge from a form field. Leaving the page without
 * saving puts the stored look back.
 */
export function AppearanceSettings() {
  const { t } = useTranslation()
  const client = useQueryClient()
  const saved = useQuery({ queryKey: ['appearance'], queryFn: () => get<Appearance>('/settings/appearance') })
  const [form, setForm] = useState<Appearance>(EMPTY)
  const [toast, setToast] = useState<{ text: string; level: 'ok' | 'error' } | null>(null)

  useEffect(() => {
    if (saved.data) setForm(saved.data)
  }, [saved.data])

  // Show it while it is being chosen, and put the stored look back on leaving.
  const preview = form.accent.trim() || form.presets?.[form.preset] || form.colour
  useEffect(() => {
    applyAppearance({ ...form, colour: preview })
    return () => {
      if (saved.data) applyAppearance(saved.data)
    }
  }, [form, preview, saved.data])

  const store = async () => {
    try {
      const answer = await put<Appearance>('/settings/appearance', { preset: form.preset, accent: form.accent, css: form.css })
      setForm(answer)
      applyAppearance(answer)
      client.setQueryData(['appearance'], answer)
      setToast({ text: t('common.saved'), level: 'ok' })
    } catch (failure) {
      setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' })
    }
  }

  const presets = Object.entries(form.presets ?? {})
  return (
    <>
      <SettingsCard title={t('settings.appearance.title')} description={t('settings.appearance.help')}>
        <Field label={t('settings.appearance.accent')} help={t('settings.appearance.accentHelp')}>
          <div className="flex flex-wrap gap-2">
            {presets.map(([name, colour]) => {
              const chosen = !form.accent.trim() && form.preset === name
              return (
                <button
                  key={name}
                  className={`h-9 w-9 rounded-full grid place-items-center border-2 ${chosen ? 'border-ink' : 'border-transparent'}`}
                  style={{ background: colour }}
                  aria-label={t(`settings.appearance.colours.${name}`, name)}
                  aria-pressed={chosen}
                  onClick={() => setForm((current) => ({ ...current, preset: name, accent: '' }))}
                >
                  {chosen && <Check size={16} className="text-black/70" />}
                </button>
              )
            })}
          </div>
        </Field>

        <Field label={t('settings.appearance.own')} htmlFor="a-own" help={t('settings.appearance.ownHelp')}>
          <div className="flex items-center gap-2">
            <input
              id="a-own"
              type="color"
              className="h-9 w-12 rounded-lg bg-transparent border border-line"
              value={/^#[0-9a-f]{6}$/i.test(form.accent) ? form.accent : preview}
              onChange={(e) => setForm((current) => ({ ...current, accent: e.target.value }))}
              aria-label={t('settings.appearance.own')}
            />
            <input
              className="input font-mono w-32"
              placeholder="#22d3ee"
              maxLength={7}
              value={form.accent}
              onChange={(e) => setForm((current) => ({ ...current, accent: e.target.value }))}
              aria-label={t('settings.appearance.ownHex')}
            />
            {form.accent && (
              <button className="btn" onClick={() => setForm((current) => ({ ...current, accent: '' }))}>
                {t('settings.appearance.backToPreset')}
              </button>
            )}
          </div>
        </Field>

        <Field label={t('settings.appearance.css')} htmlFor="a-css" help={t('settings.appearance.cssHelp')}>
          <textarea
            id="a-css"
            className="input font-mono text-[12px] min-h-40"
            spellCheck={false}
            placeholder=".card { border-radius: 4px; }"
            value={form.css}
            onChange={(e) => setForm((current) => ({ ...current, css: e.target.value }))}
          />
        </Field>
        <p className="text-xs text-faint">{t('settings.appearance.cssLimits')}</p>

        <div className="mt-4 flex gap-2">
          <button className="btn btn-accent" onClick={store}>
            {t('common.save')}
          </button>
          <button
            className="btn"
            onClick={() => {
              setForm({ ...EMPTY, presets: form.presets })
            }}
          >
            {t('settings.appearance.reset')}
          </button>
        </div>
      </SettingsCard>

      <SettingsCard title={t('settings.appearance.previewTitle')} description={t('settings.appearance.previewHelp')}>
        <div className="flex flex-wrap items-center gap-3" style={accentVariables(preview) as React.CSSProperties}>
          <button className="btn btn-accent">{t('common.save')}</button>
          <button className="btn">{t('common.cancel')}</button>
          <span className="chip">
            <span className="dot" data-status="ok" /> {t('settings.appearance.previewChip')}
          </span>
          <span className="text-accent text-sm font-medium">{t('settings.appearance.previewText')}</span>
        </div>
      </SettingsCard>
      {toast && (
        <Toast level={toast.level} onClose={() => setToast(null)}>
          {toast.text}
        </Toast>
      )}
    </>
  )
}
