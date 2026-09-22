/**
 * The colour theme: nexdeck's own look, one of the themes it ships, or one
 * pasted in as JSON, and the chosen one taken out again as a file.
 *
 * Each tile draws the theme in both brightnesses, page, card, text and
 * accent, because a name says nothing about how a theme looks. Colours that
 * would be hard to read are named before anything is saved.
 */
import { Check, Download } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { tAdapter } from '../../i18n/texts'
import { readTheme, themeFile, weakSpots, type Palette, type Theme } from '../../lib/appearance'

/** Two small cards, dark and light, painted with a palette. */
function Swatch({ theme }: { theme: Theme | null }) {
  const half = (palette: Palette | undefined, fallback: Palette) => {
    const p = { ...fallback, ...(palette ?? {}) }
    return (
      <span className="flex-1 p-1.5 flex flex-col gap-1" style={{ background: p.bg }}>
        <span className="rounded-md p-1.5 flex flex-col gap-1" style={{ background: p.surface, border: `1px solid ${p.border}` }}>
          <span className="h-1.5 w-3/4 rounded-full" style={{ background: p.text }} />
          <span className="h-1.5 w-1/2 rounded-full" style={{ background: p['text-muted'] }} />
          <span className="flex gap-1 mt-0.5">
            <span className="h-2 w-5 rounded-full" style={{ background: p.accent }} />
            <span className="h-2 w-2 rounded-full" style={{ background: p.ok }} />
            <span className="h-2 w-2 rounded-full" style={{ background: p.bad }} />
          </span>
        </span>
      </span>
    )
  }
  // nexdeck's own look, drawn from the values its style sheet ships.
  const own = {
    dark: { bg: '#0a0d12', surface: '#11161f', border: '#1f252f', text: '#e7eaf0', 'text-muted': '#94a0b3', accent: '#22d3ee', ok: '#34d399', bad: '#fb7185' },
    light: { bg: '#eef1f5', surface: '#ffffff', border: '#e2e6ec', text: '#0f172a', 'text-muted': '#55627a', accent: '#0e7490', ok: '#047857', bad: '#be123c' },
  }
  return (
    <span className="flex h-16 w-full overflow-hidden rounded-lg border border-line" aria-hidden="true">
      {half(theme?.dark, own.dark)}
      {half(theme?.light, own.light)}
    </span>
  )
}

export function ThemeChooser({ value, themes, onChange }: { value: Theme | null; themes: Record<string, Theme>; onChange: (theme: Theme | null) => void }) {
  const { t, i18n } = useTranslation()
  const [pasted, setPasted] = useState('')
  const [pasteError, setPasteError] = useState('')
  const same = (one: Theme | null, other: Theme | null) => JSON.stringify(one) === JSON.stringify(other)
  const choices: { key: string; theme: Theme | null }[] = [{ key: 'own', theme: null }, ...Object.entries(themes).map(([key, theme]) => ({ key, theme }))]
  const custom = value && !Object.values(themes).some((theme) => same(theme, value))
  const weak = weakSpots(value)

  const take = () => {
    const read = readTheme(pasted)
    if ('error' in read) {
      setPasteError(t(`settings.appearance.themePaste.${read.error}`))
      return
    }
    setPasteError('')
    onChange(read.theme)
  }

  const download = () => {
    if (!value) return
    const link = document.createElement('a')
    link.href = URL.createObjectURL(new Blob([themeFile(value)], { type: 'application/json' }))
    link.download = `${value.name.toLowerCase().replace(/[^a-z0-9]+/g, '-') || 'theme'}.nexdeck-theme.json`
    link.click()
    URL.revokeObjectURL(link.href)
  }

  return (
    <div>
      <ul className="grid gap-2 grid-cols-2 sm:grid-cols-4">
        {choices.map(({ key, theme }) => {
          const chosen = same(theme, value)
          return (
            <li key={key}>
              <button type="button" aria-pressed={chosen} onClick={() => onChange(theme)} className={`w-full text-left rounded-xl border p-2 ${chosen ? 'border-accent bg-accent-soft' : 'border-line hover:bg-surface-hover'}`}>
                <Swatch theme={theme} />
                <span className="mt-1.5 flex items-center gap-1 text-xs font-medium">
                  {chosen && <Check size={12} className="text-accent" />}
                  {theme ? tAdapter(theme.name) : t('settings.appearance.themeOwn')}
                </span>
              </button>
            </li>
          )
        })}
        {custom && value && (
          <li>
            <div className="w-full rounded-xl border border-accent bg-accent-soft p-2">
              <Swatch theme={value} />
              <span className="mt-1.5 flex items-center gap-1 text-xs font-medium">
                <Check size={12} className="text-accent" />
                {value.name}
              </span>
            </div>
          </li>
        )}
      </ul>

      {weak.length > 0 && (
        <div className="mt-3 rounded-xl border border-warn/40 p-2.5 text-xs" role="status">
          <p className="font-medium text-warn">{t('settings.appearance.themeWeak')}</p>
          <ul className="mt-1 text-muted">
            {weak.map((spot) => (
              <li key={`${spot.mode}-${spot.token}`}>
                {t(`settings.appearance.brightness.${spot.mode}`)}: {t(`settings.appearance.tokens.${spot.token}`, spot.token)} {t('settings.appearance.ratio', { ratio: spot.ratio.toLocaleString(i18n.language) })}
              </li>
            ))}
          </ul>
        </div>
      )}

      <details className="mt-3">
        <summary className="text-sm cursor-pointer">{t('settings.appearance.themeShare')}</summary>
        <p className="text-xs text-muted mt-2 mb-2">{t('settings.appearance.themeShareHelp')}</p>
        <textarea
          className="input font-mono text-[12px] min-h-28"
          spellCheck={false}
          aria-label={t('settings.appearance.themePasteLabel')}
          placeholder={'{ "name": "…", "dark": { "bg": "#0b1016", … }, "light": { … } }'}
          value={pasted}
          onChange={(event) => setPasted(event.target.value)}
        />
        {pasteError && (
          <p className="text-xs text-bad mt-1" role="alert">
            {pasteError}
          </p>
        )}
        <div className="flex gap-2 mt-2">
          <button className="btn" disabled={!pasted.trim()} onClick={take}>
            {t('settings.appearance.themeTake')}
          </button>
          <button className="btn" disabled={!value} onClick={download}>
            <Download size={14} /> {t('settings.appearance.themeExport')}
          </button>
        </div>
      </details>
    </div>
  )
}
