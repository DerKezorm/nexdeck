import { Check } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { colourKind, EFFECTS, effectOf, PALETTE, type PaletteColour } from '../lib/cardLook'
import { ServiceIcon } from './ServiceIcon'
import { Switch } from './ui'

const SWATCH: Record<PaletteColour, string> = {
  accent: 'var(--nd-accent)',
  blue: 'var(--nd-c-blue)',
  violet: 'var(--nd-c-violet)',
  pink: 'var(--nd-c-pink)',
  red: 'var(--nd-bad)',
  orange: 'var(--nd-c-orange)',
  yellow: 'var(--nd-warn)',
  green: 'var(--nd-ok)',
}
const HEX = /^#[0-9a-f]{6}$/i

interface Props {
  options: Record<string, unknown>
  icon: string
  onChange: (patch: Record<string, unknown>) => void
}

/**
 * A card's colour and how it shows: none, one of eight, the colour of its
 * logo, or one of one's own; as a frame, a tint or the whole card. Every card
 * has it, in the same place, below its own options. Below the colour, the
 * head and the frame can go, for a clock, a search or a line of text that
 * should stand free on the board.
 */
export function CardLookFields({ options, icon, onChange }: Props) {
  const { t } = useTranslation()
  const value = options.card_colour
  const kind = colourKind(value)
  const own = kind === 'own' ? String(value) : ''
  const [typed, setTyped] = useState(own)
  useEffect(() => setTyped(own), [own])
  const choose = (card_colour: string) => onChange({ card_colour })
  const swatch = (key: string, label: string, chosen: boolean, background: string, inside?: React.ReactNode) => (
    <li key={key} className="flex flex-col items-center gap-1 min-w-0">
      <button
        type="button"
        className="relative h-9 w-full rounded-lg border border-line-strong grid place-items-center"
        style={{ background }}
        aria-pressed={chosen}
        aria-label={label}
        title={label}
        onClick={() => choose(key)}
      >
        {inside}
        {chosen && <Check size={15} className="absolute right-1 top-1 drop-shadow text-white" aria-hidden="true" />}
      </button>
      <span className="text-[10px] text-faint text-center leading-tight max-w-full" aria-hidden="true">{label}</span>
    </li>
  )
  return (
    <div className="rounded-xl border border-line p-3 mb-3" data-testid="card-look">
      <p className="text-xs font-medium text-muted mb-2">{t('widget.look.title')}</p>
      <ul className="grid grid-cols-5 gap-x-2 gap-y-2" aria-label={t('widget.look.colour')}>
        {swatch('', t('widget.look.none'), kind === 'none', 'repeating-linear-gradient(135deg, transparent 0 6px, color-mix(in srgb, var(--nd-text) 15%, transparent) 6px 7px)')}
        {PALETTE.map((key) => swatch(key, t(`widget.look.colours.${key}`), kind === 'palette' && value === key, SWATCH[key]))}
        {icon && swatch('icon', t('widget.look.fromIcon'), kind === 'icon', 'conic-gradient(from 90deg, #f97316, #ec4899, #8b5cf6, #22d3ee, #34d399, #f97316)', <ServiceIcon icon={icon} size={20} />)}
      </ul>
      <div className="flex items-center gap-2 mt-3">
        <input
          type="color"
          className="h-9 w-11 rounded-lg border border-line-strong bg-transparent p-0.5 cursor-pointer"
          value={own || '#3b82f6'}
          aria-label={t('widget.look.own')}
          onChange={(event) => choose(event.target.value.toLowerCase())}
        />
        <input
          className="input w-28"
          value={typed}
          placeholder="#3b82f6"
          maxLength={7}
          aria-label={t('widget.look.ownHex')}
          onChange={(event) => {
            const text = event.target.value.trim()
            setTyped(text)
            const hex = text.startsWith('#') ? text : `#${text}`
            if (HEX.test(hex)) choose(hex.toLowerCase())
          }}
        />
        <span className="text-xs text-muted">{t('widget.look.own')}</span>
      </div>
      <p className="text-[11px] text-faint mt-2">{t('widget.look.help')}</p>
      {kind !== 'none' && (
        <div className="flex gap-1 mt-3 p-1 rounded-lg bg-surface-hover" role="group" aria-label={t('widget.look.effect')}>
          {EFFECTS.map((effect) => (
            <button
              key={effect}
              type="button"
              className={`flex-1 h-8 rounded-md text-xs ${effectOf(options.card_effect) === effect ? 'bg-surface-strong font-medium shadow-sm' : 'text-muted'}`}
              aria-pressed={effectOf(options.card_effect) === effect}
              onClick={() => onChange({ card_effect: effect })}
            >
              {t(`widget.look.effects.${effect}`)}
            </button>
          ))}
        </div>
      )}
      <div className="mt-2 border-t border-line pt-1">
        <Switch checked={options.hide_head === true} onChange={(hide_head) => onChange({ hide_head })} label={t('widget.look.hideHead')} description={t('widget.look.hideHeadHelp')} />
        <Switch checked={options.frameless === true} onChange={(frameless) => onChange({ frameless })} label={t('widget.look.frameless')} description={t('widget.look.framelessHelp')} />
      </div>
    </div>
  )
}
