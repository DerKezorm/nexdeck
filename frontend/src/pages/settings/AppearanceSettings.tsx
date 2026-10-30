import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Check } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { ApiError, get, put } from '../../api/client'
import { Field, Spinner, Switch, Toast } from '../../components/ui'
import { accentVariables, applyAppearance, CARD_STYLES, type Appearance, type CardStyle } from '../../lib/appearance'
import { canRefract } from '../../lib/refraction'
import { retroOf } from '../../lib/retro'
import { compiledSkin, NATIVE_1984, replaces, usePaint, wear, type Replaced, type SkinChoice } from '../../lib/skin/wear'
import { BrandSettings } from './BrandSettings'
import { SettingsCard } from './SettingsCard'
import { SkinChooser, useSkins } from './SkinChooser'
import { FontPicker } from './FontPicker'
import { ThemeChooser } from './ThemeChooser'

/**
 * What the skin chosen for everybody puts in place of the settings of one card of this page, said above them: those
 * settings stay stored and come back when the skin goes.
 */
function SkinReplaces({ name, replaced, parts }: { name: string; replaced: Replaced[]; parts: Replaced[] }) {
  const { t } = useTranslation()
  const shown = parts.filter((part) => replaced.includes(part))
  if (shown.length === 0) return null
  return (
    <p className="text-sm text-warn rounded-xl border border-warn/40 px-3 py-2 mb-3" role="note" data-testid="skin-replaces">
      {t('settings.appearance.skinReplaces', { name, parts: shown.map((part) => t(`settings.appearance.replacedPart.${part}`)).join(', ') })}
    </p>
  )
}

/** What choosing 1984 sets besides its card style, as the look 1984 did before it was a skin. */
const LOOK_1984 = (look: Appearance): Partial<Appearance> => ({ theme: look.themes?.['1984'] ?? look.theme, radius: 0, gap: 14 })

const EMPTY: Appearance = { preset: 'cyan', accent: '', css: '', colour: '#22d3ee', presets: {}, card_style: 'glass', radius: 16, gap: 12, refraction: true, font: 'inter' }

/** What each style looks like in its button, drawn with the same colours the card will use. */
const SAMPLE: Record<CardStyle, React.CSSProperties> = {
  glass: { background: 'var(--nd-surface)', border: '1px solid var(--nd-border)', backdropFilter: 'blur(8px)' },
  liquid: {
    background: 'linear-gradient(140deg, rgba(255,255,255,0.28), rgba(255,255,255,0.04) 45%, rgba(255,255,255,0.14)), var(--nd-lg-fill)',
    border: '1px solid rgba(255,255,255,0.45)',
    boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.4), 0 6px 14px -6px rgba(0,0,0,0.4)',
    backdropFilter: 'blur(8px) saturate(180%)',
  },
  flat: { background: 'var(--nd-bg-elev)', border: '1px solid var(--nd-border)' },
  outline: { background: 'transparent', border: '1.5px solid var(--nd-border-strong)' },
  neon: { background: 'var(--nd-surface)', border: '1px solid color-mix(in srgb, var(--nd-accent) 45%, transparent)', boxShadow: '0 0 14px -4px var(--nd-accent-glow)' },
  calm: { background: 'color-mix(in srgb, var(--nd-bg-elev) 82%, var(--nd-bg))', border: '1px solid color-mix(in srgb, var(--nd-border) 75%, transparent)' },
  // 1984: white with a black hairline, a hard shadow, and the stripes of a title bar.
  window: {
    background: 'linear-gradient(#000 0 0) top / 100% 1px no-repeat, repeating-linear-gradient(#000 0 1px, #fff 1px 2px) 0 3px / 100% 9px no-repeat, #fff',
    border: '1px solid #000',
    boxShadow: '2px 2px 0 #000',
    borderRadius: 0,
  },
}

/**
 * The skin to store with the look. ⚠️ Always sent: a save without it would take the installation's skin off.
 * 1984 is kept as the card style window with its choices in retro (what 1.0 reads), so that style says so.
 */
function skinOf(form: Appearance): SkinChoice {
  if (form.card_style === 'window') return { key: NATIVE_1984, options: { ...retroOf(form.retro) } }
  return form.skin?.key && form.skin.key !== NATIVE_1984 ? form.skin : {}
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
  // The skin chosen for everybody, saved or not yet: what it replaces of the settings below is said beside them.
  const skinKey = form.card_style === 'window' || form.skin?.key === NATIVE_1984 ? '' : (form.skin?.key ?? '')
  const worn = useQuery({ queryKey: ['skin-compiled', skinKey], queryFn: () => compiledSkin(skinKey), enabled: skinKey !== '' })
  const skins = useSkins()
  const replaced = skinKey ? replaces(worn.data ?? null) : []
  const skinName = (skins.data?.skins ?? []).find((skin) => skin.key === skinKey)?.name ?? skinKey

  useEffect(() => {
    if (saved.data) setForm(saved.data)
  }, [saved.data])

  // Show it while it is being chosen, with the skin chosen for everybody (its colours: this page keeps nexdeck's own
  // drawing). ⚠️ Painted without the skin, choosing or saving one showed nothing and took off the one worn.
  const preview = form.accent.trim() || form.presets?.[form.preset] || form.colour
  useEffect(() => {
    applyAppearance(wear({ ...form, colour: preview }, skinOf(form), skinKey ? (worn.data ?? null) : null))
  }, [form, preview, skinKey, worn.data])
  // On leaving, this account's own look goes back on, as the app puts it on: from the server, with its skin.
  useEffect(() => () => usePaint.getState().again(), [])

  const store = async () => {
    try {
      const answer = await put<Appearance>('/settings/appearance', { preset: form.preset, accent: form.accent, css: form.css, theme: form.theme ?? null, card_style: form.card_style ?? 'glass', radius: form.radius ?? 16, gap: form.gap ?? 12, refraction: form.refraction !== false, font: form.font ?? 'inter', retro: retroOf(form.retro), skin: skinOf(form) })
      setForm(answer)
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
      <BrandSettings />
      <SettingsCard title={t('settings.skins.defaultTitle')} description={`${t('settings.skins.defaultLead')} ${t('settings.skins.help')}`}>
        <SkinChooser
          value={skinOf(form)}
          onChange={(skin) =>
            setForm((current) =>
              // 1984 brings what its look always brought: its one-bit theme, square corners and its gap.
              skin.key === NATIVE_1984
                ? { ...current, card_style: 'window', retro: { ...retroOf(current.retro), ...skin.options }, skin: {}, ...(current.card_style === 'window' ? {} : LOOK_1984(current)) }
                : { ...current, skin, card_style: current.card_style === 'window' ? 'glass' : current.card_style },
            )
          }
        />
        <button className="btn btn-accent mt-4" onClick={store}>
          {t('common.save')}
        </button>
        <p className="mt-4 text-sm text-muted">
          {t('settings.skins.toWorkshop')}{' '}
          <Link className="inline-flex items-center gap-1 text-accent" to="/system/skins">
            {t('settings.skins.toWorkshopLink')} <ArrowRight size={14} />
          </Link>
        </p>
      </SettingsCard>
      <SettingsCard title={t('settings.appearance.themeTitle')} description={t('settings.appearance.themeHelp')}>
        <SkinReplaces name={skinName} replaced={replaced} parts={['theme']} />
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
        <SkinReplaces name={skinName} replaced={replaced} parts={['card_style', 'radius', 'gap']} />
        <ul className="grid gap-2 grid-cols-3 sm:grid-cols-7" aria-label={t('settings.appearance.cardsTitle')}>
          {(form.card_styles ?? CARD_STYLES).filter((style) => style in SAMPLE && style !== 'window').map((style) => {
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
                    <span className="block h-full p-1.5" style={{ borderRadius: Math.min(form.radius ?? 16, 14), ...SAMPLE[style] }}>
                      {/* Calm draws its title small and its small print soft, as its cards do. */}
                      <span className={`block rounded-full ${style === 'calm' ? 'h-1 w-1/3 bg-faint/70' : 'h-1.5 w-2/3 bg-ink/70'}`} />
                      <span className={`block h-1.5 rounded-full mt-1.5 ${style === 'calm' ? 'w-1/2 bg-ink/60' : 'w-1/3 bg-accent'}`} />
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
        {form.card_style === 'liquid' && (
          <div className="mt-3">
            <Switch
              checked={form.refraction !== false}
              onChange={(refraction) => setForm((current) => ({ ...current, refraction }))}
              label={t('settings.appearance.refraction')}
              description={canRefract() ? t('settings.appearance.refractionHelp') : `${t('settings.appearance.refractionHelp')} ${t('settings.appearance.refractionNotHere')}`}
            />
          </div>
        )}
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
      <SettingsCard title={t('settings.appearance.fontTitle')} description={form.card_style === 'window' ? `${t('settings.appearance.fontHelp')} ${t('settings.appearance.retro.fontNote')}` : t('settings.appearance.fontHelp')}>
        <SkinReplaces name={skinName} replaced={replaced} parts={['font']} />
        <FontPicker value={form.font ?? 'inter'} onChange={(font) => setForm((current) => ({ ...current, font }))} />
        <button className="btn btn-accent mt-4" onClick={store}>
          {t('common.save')}
        </button>
      </SettingsCard>
      <SettingsCard title={t('settings.appearance.title')} description={t('settings.appearance.help')}>
        <SkinReplaces name={skinName} replaced={replaced} parts={['accent']} />
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
              setForm({ ...EMPTY, presets: form.presets, themes: form.themes, card_styles: form.card_styles, fonts: form.fonts })
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
