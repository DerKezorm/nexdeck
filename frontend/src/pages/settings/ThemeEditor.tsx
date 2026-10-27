/**
 * A colour theme of one's own, made with colour pickers.
 *
 * The fifteen colours of a theme, for dark and for light, each with a picker
 * and its hex. What is chosen is painted onto the whole page at once (the
 * page shows the brightness being edited while the editor is open), a small
 * preview shows the other one beside it, and a colour that would be hard to
 * read says so where it is chosen, by the rule the server keeps
 * (`themes.weak_spots`). It is saved the way a pasted theme is: as the
 * installation's theme, with the page's own Save.
 *
 * Loaded when it is opened, not with the settings.
 */
import { AlertTriangle, RotateCcw } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { OWN_PALETTES, THEME_TOKENS, weakSpots, type Palette, type Theme } from '../../lib/appearance'

type Mode = 'dark' | 'light'
const HEX = /^#[0-9a-f]{6}$/i
const GROUPS: { key: string; tokens: string[] }[] = [
  { key: 'ground', tokens: ['bg', 'bg-elev', 'surface', 'surface-hover', 'border', 'border-strong'] },
  { key: 'text', tokens: ['text', 'text-muted', 'text-faint'] },
  { key: 'accent', tokens: ['accent', 'on-accent'] },
  { key: 'status', tokens: ['ok', 'warn', 'bad', 'unknown'] },
]

/** Every colour of both brightnesses, from what is there and nexdeck's own for what is not. */
export function fullTheme(theme: Theme | null, fallbackName: string): Theme {
  const fill = (mode: Mode): Palette => {
    const given = theme?.[mode] ?? {}
    return Object.fromEntries(THEME_TOKENS.map((token) => [token, HEX.test(given[token] ?? '') ? given[token].toLowerCase() : OWN_PALETTES[mode][token]]))
  }
  return { name: theme?.name || fallbackName, dark: fill('dark'), light: fill('light') }
}

/** A small board painted with one brightness of the theme: page, card, the three texts, the accent and the four states. */
function Preview({ palette, label }: { palette: Palette; label: string }) {
  const { t } = useTranslation()
  return (
    <figure className="rounded-xl p-2.5 border" style={{ background: palette.bg, borderColor: palette.border }} aria-label={label}>
      <figcaption className="text-[10px] uppercase tracking-wider mb-1.5" style={{ color: palette['text-faint'] }}>
        {label}
      </figcaption>
      <div className="rounded-lg p-2.5" style={{ background: palette.surface, border: `1px solid ${palette.border}` }}>
        <div className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full" style={{ background: palette.ok }} />
          <span className="text-xs font-semibold truncate" style={{ color: palette.text }}>
            {t('settings.appearance.editor.sampleTitle')}
          </span>
        </div>
        <p className="text-[11px] mt-1" style={{ color: palette['text-muted'] }}>
          {t('settings.appearance.editor.sampleLine')}
        </p>
        <p className="text-[10px]" style={{ color: palette['text-faint'] }}>
          {t('settings.appearance.editor.sampleSmall')}
        </p>
        <div className="flex items-center gap-1.5 mt-2">
          <span className="rounded-md px-2 py-0.5 text-[11px] font-medium" style={{ background: palette.accent, color: palette['on-accent'] }}>
            {t('settings.appearance.editor.sampleButton')}
          </span>
          <span className="rounded-md px-2 py-0.5 text-[11px]" style={{ background: palette['surface-hover'], color: palette.text, border: `1px solid ${palette['border-strong']}` }}>
            {t('settings.appearance.editor.sampleOther')}
          </span>
        </div>
        <div className="flex gap-2 mt-2 text-[10px] font-medium">
          {(['ok', 'warn', 'bad', 'unknown'] as const).map((state) => (
            <span key={state} style={{ color: palette[state] }}>
              {t(`settings.appearance.tokens.${state}`)}
            </span>
          ))}
        </div>
      </div>
    </figure>
  )
}

export default function ThemeEditor({ value, onChange, onClose }: { value: Theme | null; onChange: (theme: Theme) => void; onClose: () => void }) {
  const { t, i18n } = useTranslation()
  const [draft, setDraft] = useState<Theme>(() => fullTheme(value, t('settings.appearance.editor.nameDefault')))
  const [mode, setMode] = useState<Mode>(() => (document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'))
  // Typed hex that is not a colour yet stays in the field and goes nowhere.
  const [typing, setTyping] = useState<Record<string, string>>({})

  // The page in the brightness being edited, and back as it was when the editor closes.
  useEffect(() => {
    const before = document.documentElement.dataset.theme
    return () => {
      if (before) document.documentElement.dataset.theme = before
    }
  }, [])
  useEffect(() => {
    document.documentElement.dataset.theme = mode
  }, [mode])

  const change = (next: Theme) => {
    setDraft(next)
    onChange(next)
  }
  const set = (token: string, colour: string) => change({ ...draft, [mode]: { ...draft[mode], [token]: colour.toLowerCase() } })
  const weak = useMemo(() => weakSpots(draft), [draft])
  const weakHere = (token: string) => weak.find((spot) => spot.mode === mode && spot.token === token)
  const other: Mode = mode === 'dark' ? 'light' : 'dark'

  return (
    <section className="mt-3 rounded-xl border border-line p-3" aria-label={t('settings.appearance.editor.title')} data-testid="theme-editor">
      <div className="flex flex-wrap items-end gap-3 mb-3">
        <label className="flex-1 min-w-48">
          <span className="text-xs text-muted block mb-1">{t('settings.appearance.editor.name')}</span>
          <input className="input" maxLength={40} value={draft.name} onChange={(event) => change({ ...draft, name: event.target.value.slice(0, 40) })} />
        </label>
        <div className="flex gap-1 p-1 rounded-lg bg-surface-hover" role="group" aria-label={t('settings.appearance.editor.brightness')}>
          {(['dark', 'light'] as const).map((one) => (
            <button key={one} type="button" aria-pressed={mode === one} onClick={() => setMode(one)} className={`h-8 px-3 rounded-md text-xs ${mode === one ? 'bg-surface-strong font-medium shadow-sm' : 'text-muted'}`}>
              {t(`settings.appearance.brightness.${one}`)}
            </button>
          ))}
        </div>
      </div>

      <div className="grid md:grid-cols-[1fr_220px] gap-4">
        <div className="space-y-3">
          {GROUPS.map((group) => (
            <fieldset key={group.key}>
              <legend className="text-[11px] font-medium uppercase tracking-wider text-faint mb-1">{t(`settings.appearance.editor.groups.${group.key}`)}</legend>
              <ul className="grid sm:grid-cols-2 gap-x-3 gap-y-1">
                {group.tokens.map((token) => {
                  const colour = draft[mode]?.[token] ?? OWN_PALETTES[mode][token]
                  const label = t(`settings.appearance.tokens.${token}`)
                  const spot = weakHere(token)
                  const key = `${mode}-${token}`
                  return (
                    <li key={token} className="flex items-center gap-2 min-w-0">
                      <input
                        type="color"
                        className="h-8 w-9 flex-none rounded-md border border-line-strong bg-transparent p-0.5 cursor-pointer"
                        value={colour}
                        aria-label={label}
                        onChange={(event) => set(token, event.target.value)}
                      />
                      {/* The name, and under it what is hard to read about the colour: the name keeps its room. */}
                      <span className="flex-1 min-w-0 leading-tight">
                        <span className="text-xs block truncate" title={label}>
                          {label}
                        </span>
                        {spot && (
                          <span className="text-[10px] text-warn flex items-center gap-0.5" title={t('settings.appearance.themeWeak')} data-testid={`weak-${token}`}>
                            <AlertTriangle size={10} aria-hidden="true" />
                            {t('settings.appearance.ratio', { ratio: spot.ratio.toLocaleString(i18n.language) })}
                          </span>
                        )}
                      </span>
                      <input
                        className="input !w-[5.6rem] !h-8 !py-0 font-mono text-[11px] flex-none"
                        maxLength={7}
                        aria-label={t('settings.appearance.editor.hex', { name: label })}
                        value={typing[key] ?? colour}
                        onChange={(event) => {
                          const text = event.target.value.trim()
                          const hex = text.startsWith('#') ? text : `#${text}`
                          setTyping((current) => ({ ...current, [key]: text }))
                          if (HEX.test(hex)) set(token, hex)
                        }}
                        onBlur={() => setTyping(({ [key]: _gone, ...rest }) => rest)}
                      />
                    </li>
                  )
                })}
              </ul>
            </fieldset>
          ))}
        </div>
        <div className="space-y-2">
          <Preview palette={draft[mode]!} label={t(`settings.appearance.brightness.${mode}`)} />
          <Preview palette={draft[other]!} label={t(`settings.appearance.brightness.${other}`)} />
          {weak.length === 0 && <p className="text-[11px] text-ok">{t('settings.appearance.editor.allReadable')}</p>}
        </div>
      </div>

      <div className="flex flex-wrap gap-2 mt-3">
        <button type="button" className="btn" onClick={onClose}>
          {t('settings.appearance.editor.close')}
        </button>
        <button type="button" className="btn" onClick={() => change(fullTheme(null, draft.name))}>
          <RotateCcw size={14} /> {t('settings.appearance.editor.fromOwn')}
        </button>
      </div>
      <p className="text-[11px] text-faint mt-2">{t('settings.appearance.editor.saveHint')}</p>
    </section>
  )
}
