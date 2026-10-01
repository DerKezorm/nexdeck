import { Check, Copy } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { type Appearance, type CardStyle, lookFile, readLook } from '../../lib/appearance'
import { SettingsCard } from './SettingsCard'

/**
 * A look is the whole of it at once: the colour theme, a colour of one's own,
 * how cards are drawn, their corners and the gap between them. It travels as
 * a short text, to copy here and paste into another nexdeck, and a few
 * ready-made ones stand here to start from.
 */
export interface Look {
  key: string
  theme: string | null
  card_style: CardStyle
  radius: number
  gap: number
}

/** Looks that go together, tried on the demo board. The first is nexdeck as it ships. */
export const LOOKS: Look[] = [
  { key: 'classic', theme: null, card_style: 'glass', radius: 16, gap: 12 },
  { key: 'midnight', theme: 'tokyonight', card_style: 'neon', radius: 14, gap: 12 },
  { key: 'frost', theme: 'nord', card_style: 'outline', radius: 8, gap: 10 },
  { key: 'latte', theme: 'catppuccin', card_style: 'flat', radius: 12, gap: 14 },
  { key: 'castle', theme: 'dracula', card_style: 'glass', radius: 18, gap: 12 },
  { key: 'workshop', theme: 'gruvbox', card_style: 'flat', radius: 4, gap: 8 },
  { key: 'evening', theme: 'rosepine', card_style: 'glass', radius: 20, gap: 16 },
]

function Sample({ form, look }: { form: Appearance; look: Look }) {
  const palette = look.theme ? form.themes?.[look.theme]?.dark : undefined
  const ground = palette?.bg ?? '#0a0d12'
  const surface = palette?.surface ?? '#11161f'
  const accent = palette?.accent ?? '#22d3ee'
  const card: React.CSSProperties = {
    borderRadius: Math.min(look.radius, 10),
    background: look.card_style === 'outline' ? 'transparent' : surface,
    border: `1px solid ${look.card_style === 'neon' ? accent : look.card_style === 'outline' ? `${accent}66` : 'rgba(255,255,255,0.08)'}`,
    boxShadow: look.card_style === 'neon' ? `0 0 10px -3px ${accent}` : undefined,
  }
  return (
    <span className="grid grid-cols-3 gap-1 h-14 p-1.5 rounded-lg" style={{ background: ground, gap: Math.max(2, look.gap / 3) }} aria-hidden="true">
      <span className="col-span-2" style={card}>
        <span className="block m-1.5 h-1 w-1/2 rounded-full" style={{ background: accent }} />
      </span>
      <span style={card} />
      <span style={card} />
      <span className="col-span-2" style={card} />
    </span>
  )
}

export function LookShare({ form, onChange, onSave }: { form: Appearance; onChange: (next: Appearance) => void; onSave: () => void }) {
  const { t } = useTranslation()
  const [pasted, setPasted] = useState('')
  const [problem, setProblem] = useState('')
  const [copied, setCopied] = useState(false)
  const chosen = (look: Look) =>
    (form.card_style ?? 'glass') === look.card_style && (form.radius ?? 16) === look.radius && (form.gap ?? 12) === look.gap &&
    (look.theme ? form.theme?.name === form.themes?.[look.theme]?.name : !form.theme)
  const take = (look: Look) => onChange({ ...form, theme: look.theme ? (form.themes?.[look.theme] ?? null) : null, accent: '', card_style: look.card_style, radius: look.radius, gap: look.gap })
  const paste = () => {
    const read = readLook(pasted)
    if ('error' in read) {
      setProblem(t(`settings.appearance.themePaste.${read.error}`))
      return
    }
    setProblem('')
    onChange({ ...form, ...read.look })
  }
  const copy = () => {
    void navigator.clipboard?.writeText(lookFile(form)).then(() => setCopied(true))
  }
  return (
    <SettingsCard title={t('settings.appearance.looksTitle')} description={t('settings.appearance.looksHelp')}>
      <ul className="grid gap-2 grid-cols-2 sm:grid-cols-4" aria-label={t('settings.appearance.looksTitle')}>
        {LOOKS.map((look) => (
          <li key={look.key}>
            <button type="button" aria-pressed={chosen(look)} onClick={() => take(look)} className={`w-full text-left rounded-xl border p-2 ${chosen(look) ? 'border-accent bg-accent-soft' : 'border-line hover:bg-surface-hover'}`}>
              <Sample form={form} look={look} />
              <span className="mt-1.5 flex items-center gap-1 text-xs font-medium">
                {chosen(look) && <Check size={12} className="text-accent" />}
                {t(`settings.appearance.looks.${look.key}`)}
              </span>
            </button>
          </li>
        ))}
      </ul>
      <button className="btn btn-accent mt-3" onClick={onSave}>
        {t('common.save')}
      </button>
      <details className="mt-4">
        <summary className="text-sm cursor-pointer">{t('settings.appearance.lookShare')}</summary>
        <p className="text-xs text-muted mt-2 mb-2">{t('settings.appearance.lookShareHelp')}</p>
        <button className="btn mb-3" onClick={copy}>
          <Copy size={14} /> {copied ? t('settings.appearance.lookCopied') : t('settings.appearance.lookCopy')}
        </button>
        <textarea
          className="input font-mono text-[12px] min-h-24"
          spellCheck={false}
          aria-label={t('settings.appearance.lookPasteLabel')}
          placeholder='{ "nexdeck_look": 1, … }'
          value={pasted}
          onChange={(event) => setPasted(event.target.value)}
        />
        {problem && (
          <p className="text-xs text-bad mt-1" role="alert">
            {problem}
          </p>
        )}
        <button className="btn mt-2" disabled={!pasted.trim()} onClick={paste}>
          {t('settings.appearance.lookTake')}
        </button>
      </details>
    </SettingsCard>
  )
}
