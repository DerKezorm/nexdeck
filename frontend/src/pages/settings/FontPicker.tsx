/**
 * The type of the interface, each choice written in itself.
 *
 * The faces are asked for when this list is on screen, because a name in the
 * wrong type says nothing about a font. That is the one place they are
 * fetched without being chosen; a board loads only the one in use.
 */
import { Check } from 'lucide-react'
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'

import { FONTS, loadFace } from '../../lib/fonts'

export function FontPicker({ value, onChange }: { value: string; onChange: (key: string) => void }) {
  const { t } = useTranslation()
  useEffect(() => {
    for (const font of FONTS) void loadFace(font.key)
  }, [])
  return (
    <ul className="grid gap-2 grid-cols-2 sm:grid-cols-3" aria-label={t('settings.appearance.fontTitle')}>
      {FONTS.map((font) => {
        const chosen = value === font.key
        const family = `${font.family}, system-ui, sans-serif`
        return (
          <li key={font.key}>
            <button
              type="button"
              aria-pressed={chosen}
              onClick={() => onChange(font.key)}
              className={`w-full text-left rounded-xl border px-3 py-2.5 ${chosen ? 'border-accent bg-accent-soft' : 'border-line hover:bg-surface-hover'}`}
            >
              <span className="block text-lg leading-tight truncate" style={{ fontFamily: family }} aria-hidden="true">
                {t('settings.appearance.fontSample')}
              </span>
              <span className="mt-1 flex items-center gap-1 text-xs text-muted" style={{ fontFamily: family }}>
                {chosen && <Check size={12} className="text-accent flex-none" />}
                <span className="truncate">{font.name || t('settings.appearance.fontSystem')}</span>
                {font.key === 'inter' && <span className="text-faint">· {t('settings.appearance.fontDefault')}</span>}
              </span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}
