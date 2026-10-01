import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, get, put } from '../../api/client'
import { Field, Spinner, Toast } from '../../components/ui'
import { accentVariables, applyAppearance, type Appearance, type CardStyle } from '../../lib/appearance'
import { SettingsCard } from './SettingsCard'
import { LookShare } from './LookShare'
import { ThemeChooser } from './ThemeChooser'

const EMPTY: Appearance = { preset: 'cyan', accent: '', css: '', colour: '#22d3ee', presets: {}, card_style: 'glass', radius: 16, gap: 12 }

/** What each style looks like in its button, drawn with the same colours the card will use. */
const SAMPLE: Record<CardStyle, React.CSSProperties> = {
  glass: { background: 'var(--nd-surface)', border: '1px solid var(--nd-border)', backdropFilter: 'blur(8px)' },
  flat: { background: 'var(--nd-bg-elev)', border: '1px solid var(--nd-border)' },
  outline: { background: 'transparent', border: '1.5px solid var(--nd-border-strong)' },
  neon: { background: 'var(--nd-surface)', border: '1px solid color-mix(in srgb, var(--nd-accent) 45%, transparent)', boxShadow: '0 0 14px -4px var(--nd-accent-glow)' },
}

/**
 * The look of the whole installation: a colour theme, one accent colour
 * and, for whoever wants it, a style sheet of their own.
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
      const answer = await put<Appearance>('/settings/appearance', { preset: form.preset, accent: form.accent, css: form.css, theme: form.theme ?? null, card_style: form.card_style ?? 'glass', radius: form.radius ?? 16, gap: form.gap ?? 12 })
      setForm(answer)
      applyAppearance(answer)
      client.setQueryData(['appearance'], answer)
      setToast({ text: t('common.saved'), level: 'ok' })
    } catch (failure) {
      setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' })
    }
  }

  // ⚠️ Nothing to show until the stored look is here. The page used to draw
  // its empty starting form while the request was out or had failed: no
  // themes, no colours, "nexdeck" ticked, and a save from there would have
  // put the look back to nothing. Reported on 22.09.2026 after the server had
  // restarted under a page that was loading.
  if (saved.isLoading) return <Spinner />
  if (saved.isError || !saved.data) {
    return (
      <SettingsCard title={t('settings.appearance.title')}>
        <p className="text-sm text-bad mb-3" role="alert">
          {t('settings.appearance.loadFailed')}
        </p>
        <button className="btn" onClick={() => void saved.refetch()}>
          {t('settings.appearance.retry')}
        </button>
      </SettingsCard>
    )
  }

  const presets = Object.entries(form.presets ?? {})
  return (
    <>
      <SettingsCard title={t('settings.appearance.themeTitle')} description={t('settings.appearance.themeHelp')}>
        <ThemeChooser
          value={form.theme ?? null}
          themes={form.themes ?? {}}
          onChange={(theme) => setForm((current) => ({ ...current, theme }))}
        />
        <button className="btn btn-accent mt-4" onClick={store}>
          {t('common.save')}
        </button>
      </SettingsCard>
      <SettingsCard title={t('settings.appearance.cardsTitle')} description={t('settings.appearance.cardsHelp')}>
        <ul className="grid gap-2 grid-cols-2 sm:grid-cols-4" aria-label={t('settings.appearance.cardsTitle')}>
          {(form.card_styles ?? ['glass', 'flat', 'outline', 'neon']).map((style) => {
            const chosen = (form.card_style ?? 'glass') === style
            return (
              <li key={style}>
                <button
                  type="button"
                  aria-pressed={chosen}
                  onClick={() => setForm((current) => ({ ...current, card_style: style }))}
                  className={`w-full text-left rounded-xl border p-2 ${chosen ? 'border-accent bg-accent-soft' : 'border-line hover:bg-surface-hover'}`}
                >
                  <span className="block h-12 p-1.5" aria-hidden="true">
                    <span className="block h-full p-1.5" style={{ ...SAMPLE[style], borderRadius: Math.min(form.radius ?? 16, 14) }}>
                      <span className="block h-1.5 w-2/3 rounded-full bg-ink/70" />
                      <span className="block h-1.5 w-1/3 rounded-full bg-accent mt-1.5" />
                    </span>
                  </span>
                  <span className="mt-1 flex items-center gap-1 text-xs font-medium">
                    {chosen && <Check size={12} className="text-accent" />}
                    {t(`settings.appearance.cardStyle.${style}`)}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
        <div className="grid sm:grid-cols-2 gap-x-6 mt-4">
          <Field label={t('settings.appearance.radius')} htmlFor="a-radius">
            <div className="flex items-center gap-3">
              <input id="a-radius" type="range" min={0} max={28} className="flex-1 accent-[var(--nd-accent)]" value={form.radius ?? 16} onChange={(e) => setForm((current) => ({ ...current, radius: Number(e.target.value) }))} />
              <span className="num text-xs text-muted w-12 text-right">{t('settings.appearance.pixels', { count: form.radius ?? 16 })}</span>
            </div>
          </Field>
          <Field label={t('settings.appearance.gap')} htmlFor="a-gap">
            <div className="flex items-center gap-3">
              <input id="a-gap" type="range" min={4} max={28} className="flex-1 accent-[var(--nd-accent)]" value={form.gap ?? 12} onChange={(e) => setForm((current) => ({ ...current, gap: Number(e.target.value) }))} />
              <span className="num text-xs text-muted w-12 text-right">{t('settings.appearance.pixels', { count: form.gap ?? 12 })}</span>
            </div>
          </Field>
        </div>
        <button className="btn btn-accent mt-2" onClick={store}>
          {t('common.save')}
        </button>
      </SettingsCard>
      <LookShare form={form} onChange={setForm} onSave={store} />
      <SettingsCard title={t('settings.appearance.title')} description={t('settings.appearance.help')}>
        <Field label={t('settings.appearance.accent')} help={t('settings.appearance.accentHelp')}>
          <div className="flex flex-wrap gap-2">
            {presets.map(([name, colour]) => {
              const chosen = !form.accent.trim() && !form.theme && form.preset === name
              return (
                <button
                  key={name}
                  className={`h-9 w-9 rounded-full grid place-items-center border-2 ${chosen ? 'border-ink' : 'border-transparent'}`}
                  style={{ background: colour }}
                  aria-label={t(`settings.appearance.colours.${name}`, name)}
                  aria-pressed={chosen}
                  // A theme brings an accent for dark and one for light; a preset would be one for both.
                  disabled={Boolean(form.theme)}
                  onClick={() => setForm((current) => ({ ...current, preset: name, accent: '' }))}
                >
                  {chosen && <Check size={16} className="text-black/70" />}
                </button>
              )
            })}
          </div>
          {form.theme && <p className="text-xs text-muted mt-1.5">{t('settings.appearance.themeAccent')}</p>}
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
              setForm({ ...EMPTY, presets: form.presets, themes: form.themes, card_styles: form.card_styles })
            }}
          >
            {t('settings.appearance.reset')}
          </button>
        </div>
      </SettingsCard>

      <SettingsCard title={t('settings.appearance.previewTitle')} description={t('settings.appearance.previewHelp')}>
        <div className="flex flex-wrap items-center gap-3" style={(form.theme && !form.accent.trim() ? undefined : accentVariables(preview)) as React.CSSProperties | undefined}>
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
