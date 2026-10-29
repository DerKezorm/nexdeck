/**
 * The left column of the skin editor: the file in its parts, each a section to
 * open. Every field writes one value at its path in the file (`draft.at`), so
 * undo takes back exactly what was changed and the server says what is wrong
 * with it. Nothing here decides what is allowed; the server does.
 */
import { Lock, Play, Plus, Trash2 } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { Field, Select, Switch } from '../../components/ui'
import type { Appearance } from '../../lib/appearance'
import type { Draft, SkinDoc } from '../../lib/skin/draft'
import { play } from '../../lib/skin/sound'
import type { SkinSchema } from './SkinEditorPage'
import { SpriteEditor, type SpriteData } from './SpriteEditor'

export const TOKENS = ['bg', 'bg-elev', 'surface', 'surface-hover', 'border', 'border-strong', 'text', 'text-muted', 'text-faint', 'accent', 'on-accent', 'ok', 'warn', 'bad', 'unknown'] as const

type Record_ = Record<string, unknown>
const record = (value: unknown): Record_ => (value && typeof value === 'object' && !Array.isArray(value) ? (value as Record_) : {})
const list = (value: unknown): Record_[] => (Array.isArray(value) ? (value as Record_[]) : [])
const text = (value: unknown) => (typeof value === 'string' ? value : '')

export function Section({ title, children, open = false, locked = false }: { title: string; children: ReactNode; open?: boolean; locked?: boolean }) {
  const { t } = useTranslation()
  return (
    <details open={open} className="rounded-lg border border-line">
      <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium flex items-center gap-1">
        <span className="flex-1">{title}</span>
        {locked && <Lock size={12} className="text-muted" aria-label={t('skinEditor.ai.lockedForAi')} />}
      </summary>
      <div className="px-3 pb-3 flex flex-col gap-3">{children}</div>
    </details>
  )
}

export function NumberField({ label, value, min, max, step = 1, onChange }: { label: string; value: number | undefined; min: number; max: number; step?: number; onChange: (value: number | undefined) => void }) {
  return (
    <label className="flex items-center gap-2 text-xs">
      <span className="w-24 shrink-0 text-muted">{label}</span>
      <input type="range" className="flex-1 accent-[var(--nd-accent)]" min={min} max={max} step={step} value={value ?? min} onChange={(event) => onChange(Number(event.target.value))} aria-label={label} />
      <span className="num w-10 text-right">{value ?? '–'}</span>
    </label>
  )
}

export function SpriteSelect({ doc, value, onChange, label, empty = true }: { doc: SkinDoc; value: unknown; onChange: (value: string | undefined) => void; label: string; empty?: boolean }) {
  const { t } = useTranslation()
  const names = Object.keys(record(doc.sprites))
  return (
    <label className="flex items-center gap-2 text-xs">
      <span className="w-24 shrink-0 text-muted">{label}</span>
      <select className="input h-8 text-xs flex-1" value={text(value)} onChange={(event) => onChange(event.target.value || undefined)} aria-label={label}>
        {empty && <option value="">{t('skinEditor.none')}</option>}
        {names.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </select>
    </label>
  )
}

export function FilePanels({ doc, draft, schema, base, advanced, weak, keyLocked, locked = [] }: { doc: SkinDoc; draft: Draft; schema: SkinSchema; base: Appearance; advanced: boolean; weak: { mode: string; token: string; ratio: number }[]; keyLocked: boolean; locked?: string[] }) {
  const { t } = useTranslation()
  const tokens = record(doc.tokens)
  const sprites = record(doc.sprites) as Record<string, SpriteData>
  const frames = record(doc.frames)
  const sounds = record(doc.sounds)
  const switches = record(doc.switches)
  const [sprite, setSprite] = useState<string | null>(Object.keys(sprites)[0] ?? null)
  const [newName, setNewName] = useState('')
  const used = (name: string) => JSON.stringify({ ...doc, sprites: undefined }).includes(`"${name}"`)
  const free = (prefix: string, taken: Record_) => {
    let number = 1
    while (`${prefix}${number}` in taken) number += 1
    return `${prefix}${number}`
  }

  return (
    <>
      <Section title={t('skinEditor.section.general')} open>
        <Field label={t('skinEditor.name')} htmlFor="skin-name">
          <input id="skin-name" className="input" value={doc.name} maxLength={60} onChange={(event) => draft.at(['name'], event.target.value)} />
        </Field>
        <Field label={t('skinEditor.key')} help={keyLocked ? t('skinEditor.keyLocked') : t('skinEditor.keyHelp')} htmlFor="skin-key">
          <input id="skin-key" className="input font-mono" value={doc.key} maxLength={32} disabled={keyLocked} onChange={(event) => draft.at(['key'], event.target.value.toLowerCase())} />
        </Field>
        <Field label={t('skinEditor.description')} htmlFor="skin-description">
          <textarea id="skin-description" className="input h-16" value={text(doc.description)} maxLength={280} onChange={(event) => draft.at(['description'], event.target.value || undefined)} />
        </Field>
        <Field label={t('skinEditor.author')} htmlFor="skin-author">
          <input id="skin-author" className="input" value={text(doc.author)} maxLength={60} onChange={(event) => draft.at(['author'], event.target.value || undefined)} />
        </Field>
      </Section>

      <Section title={t('skinEditor.section.tokens')} locked={locked.includes('tokens')}>
        <Field label={t('skinEditor.cardStyle')} htmlFor="skin-card-style">
          <Select
            id="skin-card-style"
            value={text(tokens.card_style)}
            onChange={(value) => draft.at(['tokens', 'card_style'], value || undefined)}
            options={[{ value: '', label: t('skinEditor.installations') }, ...schema.card_styles.map((style) => ({ value: style, label: t(`settings.appearance.cardStyle.${style}`) }))]}
          />
        </Field>
        <NumberField label={t('skinEditor.radius')} value={tokens.radius as number | undefined} min={0} max={28} onChange={(value) => draft.at(['tokens', 'radius'], value)} />
        <NumberField label={t('skinEditor.gap')} value={tokens.gap as number | undefined} min={4} max={28} onChange={(value) => draft.at(['tokens', 'gap'], value)} />
        <Field label={t('skinEditor.font')} htmlFor="skin-font">
          <Select id="skin-font" value={text(tokens.font)} onChange={(value) => draft.at(['tokens', 'font'], value || undefined)} options={[{ value: '', label: t('skinEditor.installations') }, ...schema.fonts.map((font) => ({ value: font, label: font }))]} />
        </Field>
        <Field label={t('skinEditor.colours')} help={t('skinEditor.coloursHelp')} htmlFor="skin-theme">
          <select
            id="skin-theme"
            className="input"
            value=""
            onChange={(event) => {
              const theme = base.themes?.[event.target.value]
              if (theme) draft.set({ ...doc, tokens: { ...tokens, dark: theme.dark, light: theme.light } }, 'tokens.palette')
            }}
          >
            <option value="">{t('skinEditor.coloursFrom')}</option>
            {Object.entries(base.themes ?? {}).map(([key, theme]) => (
              <option key={key} value={key}>
                {theme.name}
              </option>
            ))}
          </select>
        </Field>
        {(['dark', 'light'] as const).map((brightness) =>
          tokens[brightness] ? (
            <div key={brightness}>
              <p className="text-xs font-medium mb-1">{t(`skinEditor.${brightness}`)}</p>
              <div className="grid grid-cols-3 gap-1">
                {TOKENS.map((token) => {
                  const low = weak.find((spot) => spot.mode === brightness && spot.token === token)
                  return (
                    <label key={token} className="flex items-center gap-1 text-[11px]" title={low ? t('skinEditor.weak', { ratio: low.ratio }) : undefined}>
                      <input type="color" className="w-6 h-6 p-0 border border-line rounded" value={text(record(tokens[brightness])[token]) || '#000000'} onChange={(event) => draft.at(['tokens', brightness, token], event.target.value)} aria-label={`${t(`skinEditor.${brightness}`)} ${token}`} />
                      <span className={`truncate ${low ? 'text-warn' : 'text-muted'}`}>{token}</span>
                    </label>
                  )
                })}
              </div>
            </div>
          ) : null,
        )}
        {weak.length > 0 && <p className="text-xs text-warn">{t('skinEditor.weakHelp', { count: weak.length })}</p>}
        {Boolean(tokens.dark || tokens.light) && (
          <button type="button" className="btn btn-flat self-start" onClick={() => draft.set({ ...doc, tokens: { ...tokens, dark: undefined, light: undefined } }, 'tokens.palette')}>
            {t('skinEditor.coloursOff')}
          </button>
        )}
      </Section>

      <Section title={t('skinEditor.section.sprites')} locked={locked.includes('sprites')}>
        <div className="flex flex-wrap gap-1">
          {Object.keys(sprites).map((name) => (
            <button key={name} type="button" className="btn btn-flat" aria-pressed={sprite === name} onClick={() => setSprite(name)}>
              {name}
            </button>
          ))}
        </div>
        <div className="flex gap-1">
          <input className="input h-8 text-xs font-mono" placeholder={t('skinEditor.spriteName')} value={newName} onChange={(event) => setNewName(event.target.value.toLowerCase())} aria-label={t('skinEditor.spriteName')} />
          <button
            type="button"
            className="btn"
            disabled={!/^[a-z][a-z0-9-]{0,23}$/.test(newName) || newName in sprites}
            onClick={() => {
              draft.at(['sprites', newName], { palette: { K: '#1a1a1a' }, rows: Array.from({ length: 8 }, () => '........') })
              setSprite(newName)
              setNewName('')
            }}
          >
            <Plus size={14} /> {t('skinEditor.add')}
          </button>
        </div>
        {sprite && sprites[sprite] && (
          <>
            <SpriteEditor sprite={sprites[sprite]} onChange={(next) => draft.at(['sprites', sprite], next)} limits={schema.limits} />
            <button type="button" className="btn btn-flat self-start text-bad" disabled={used(sprite)} title={used(sprite) ? t('skinEditor.spriteUsed') : undefined} onClick={() => (draft.at(['sprites', sprite], undefined), setSprite(null))}>
              <Trash2 size={14} /> {t('skinEditor.remove')}
            </button>
          </>
        )}
      </Section>

      <Section title={t('skinEditor.section.frames')} locked={locked.includes('frames')}>
        <p className="text-xs text-muted">{t('skinEditor.framesHelp')}</p>
        {Object.entries(frames).map(([name, value]) => {
          const frame = record(value)
          return (
            <div key={name} className="flex flex-col gap-1 rounded border border-line p-2">
              <div className="flex items-center justify-between text-xs font-mono">
                {name}
                <button type="button" className="btn btn-flat btn-icon" onClick={() => draft.at(['frames', name], undefined)} aria-label={t('skinEditor.remove')}>
                  <Trash2 size={12} />
                </button>
              </div>
              <SpriteSelect doc={doc} label={t('skinEditor.sprite')} value={frame.sprite} empty={false} onChange={(value) => draft.at(['frames', name, 'sprite'], value)} />
              <NumberField label={t('skinEditor.slice')} value={frame.slice as number} min={1} max={16} onChange={(value) => draft.at(['frames', name, 'slice'], value)} />
              <NumberField label={t('skinEditor.frameWidth')} value={frame.width as number} min={1} max={16} onChange={(value) => draft.at(['frames', name, 'width'], value)} />
            </div>
          )
        })}
        <button type="button" className="btn self-start" disabled={!Object.keys(sprites).length} onClick={() => draft.at(['frames', free('frame', frames)], { sprite: Object.keys(sprites)[0], slice: 2, width: 4 })}>
          <Plus size={14} /> {t('skinEditor.addFrame')}
        </button>
      </Section>

      <Section title={t('skinEditor.section.desk')} locked={locked.includes('desk')}>
        <SpriteSelect doc={doc} label={t('skinEditor.tile')} value={record(doc.desk).tile} onChange={(value) => draft.at(['desk'], value ? { tile: value, scale: (record(doc.desk).scale as number) ?? 2 } : undefined)} />
        {doc.desk ? <NumberField label={t('skinEditor.scale')} value={record(doc.desk).scale as number} min={1} max={8} onChange={(value) => draft.at(['desk', 'scale'], value)} /> : null}
      </Section>

      <Section title={t('skinEditor.section.status')} locked={locked.includes('status')}>
        <p className="text-xs text-muted">{t('skinEditor.statusHelp')}</p>
        {(['ok', 'warn', 'bad', 'unknown'] as const).map((state) => (
          <SpriteSelect
            key={state}
            doc={doc}
            label={t(`skinEditor.state.${state}`)}
            value={record(doc.status)[state]}
            onChange={(value) => {
              // The server says when ok, warning or fault is missing; with none left the skin keeps nexdeck's symbols.
              const status = Object.fromEntries(Object.entries({ ...record(doc.status), [state]: value }).filter(([, name]) => name))
              draft.set({ ...doc, status: Object.keys(status).length ? status : undefined }, `status.${state}`)
            }}
          />
        ))}
      </Section>

      <Section title={t('skinEditor.section.sounds')} locked={locked.includes('sounds')}>
        {Object.entries(sounds).map(([name, value]) => {
          const sound = record(value)
          return (
            <div key={name} className="flex flex-col gap-1 rounded border border-line p-2">
              <div className="flex items-center gap-1 text-xs font-mono">
                <span className="flex-1">{name}</span>
                <button type="button" className="btn btn-flat btn-icon" aria-label={t('skinEditor.play')} onClick={() => play({ wave: (text(sound.wave) || 'square') as OscillatorType, from: Number(sound.from ?? 520), to: Number(sound.to ?? 1040), ms: Number(sound.ms ?? 120), volume: Number(sound.volume ?? 0.06) })}>
                  <Play size={12} />
                </button>
                <button type="button" className="btn btn-flat btn-icon" onClick={() => draft.at(['sounds', name], undefined)} aria-label={t('skinEditor.remove')}>
                  <Trash2 size={12} />
                </button>
              </div>
              <label className="flex items-center gap-2 text-xs">
                <span className="w-24 shrink-0 text-muted">{t('skinEditor.wave')}</span>
                <select className="input h-8 text-xs flex-1" value={text(sound.wave) || 'square'} onChange={(event) => draft.at(['sounds', name, 'wave'], event.target.value)}>
                  {schema.waves.map((wave) => (
                    <option key={wave} value={wave}>
                      {wave}
                    </option>
                  ))}
                </select>
              </label>
              <NumberField label={t('skinEditor.pitchFrom')} value={sound.from as number} min={40} max={4000} step={10} onChange={(value) => draft.at(['sounds', name, 'from'], value)} />
              <NumberField label={t('skinEditor.pitchTo')} value={sound.to as number} min={40} max={4000} step={10} onChange={(value) => draft.at(['sounds', name, 'to'], value)} />
              <NumberField label={t('skinEditor.length')} value={sound.ms as number} min={20} max={600} step={10} onChange={(value) => draft.at(['sounds', name, 'ms'], value)} />
              <NumberField label={t('skinEditor.volume')} value={sound.volume as number} min={0.01} max={0.2} step={0.01} onChange={(value) => draft.at(['sounds', name, 'volume'], value)} />
            </div>
          )
        })}
        <button type="button" className="btn self-start" onClick={() => draft.at(['sounds', free('sound', sounds)], { wave: 'square', from: 520, to: 1040, ms: 120, volume: 0.06 })}>
          <Plus size={14} /> {t('skinEditor.addSound')}
        </button>
      </Section>

      <Section title={t('skinEditor.section.options')} locked={locked.includes('options')}>
        <p className="text-xs text-muted">{t('skinEditor.optionsHelp')}</p>
        {list(doc.options).map((option, index) => (
          <div key={index} className="flex flex-col gap-1 rounded border border-line p-2">
            <div className="flex gap-1">
              <input className="input h-8 text-xs font-mono w-24" value={text(option.key)} onChange={(event) => draft.at(['options', index, 'key'], event.target.value.toLowerCase())} aria-label={t('skinEditor.key')} />
              <input className="input h-8 text-xs flex-1" value={text(option.label)} onChange={(event) => draft.at(['options', index, 'label'], event.target.value)} aria-label={t('skinEditor.label')} />
              <button type="button" className="btn btn-flat btn-icon" onClick={() => draft.at(['options', index], undefined)} aria-label={t('skinEditor.remove')}>
                <Trash2 size={12} />
              </button>
            </div>
            {list(option.choices).map((choice, number) => (
              <div key={number} className="flex gap-1 pl-3">
                <input className="input h-7 text-xs font-mono w-24" value={text(choice.key)} onChange={(event) => draft.at(['options', index, 'choices', number, 'key'], event.target.value.toLowerCase())} aria-label={t('skinEditor.key')} />
                <input className="input h-7 text-xs flex-1" value={text(choice.label)} onChange={(event) => draft.at(['options', index, 'choices', number, 'label'], event.target.value)} aria-label={t('skinEditor.label')} />
                <input type="radio" name={`default-${index}`} checked={option.default === choice.key} onChange={() => draft.at(['options', index, 'default'], choice.key)} aria-label={t('skinEditor.default')} title={t('skinEditor.default')} />
              </div>
            ))}
            <button type="button" className="btn btn-flat self-start text-xs" onClick={() => draft.at(['options', index, 'choices', list(option.choices).length], { key: `choice-${list(option.choices).length + 1}`, label: t('skinEditor.newChoice') })}>
              <Plus size={12} /> {t('skinEditor.addChoice')}
            </button>
          </div>
        ))}
        <button
          type="button"
          className="btn self-start"
          onClick={() => draft.at(['options', list(doc.options).length], { key: `option-${list(doc.options).length + 1}`, label: t('skinEditor.newOption'), default: 'one', choices: [{ key: 'one', label: '1' }, { key: 'two', label: '2' }] })}
        >
          <Plus size={14} /> {t('skinEditor.addOption')}
        </button>
      </Section>

      <Section title={t('skinEditor.section.switches')} locked={locked.includes('switches')}>
        <Switch checked={switches.corners === 'square'} onChange={(on) => draft.at(['switches', 'corners'], on ? 'square' : undefined)} label={t('skinEditor.switch.corners')} />
        <Switch checked={switches.shadows === 'none'} onChange={(on) => draft.at(['switches', 'shadows'], on ? 'none' : undefined)} label={t('skinEditor.switch.shadows')} />
        <Switch checked={switches.blur === 'off'} onChange={(on) => draft.at(['switches', 'blur'], on ? 'off' : undefined)} label={t('skinEditor.switch.blur')} />
      </Section>

      {advanced && (
        <Section title={t('skinEditor.section.css')} open locked={locked.includes('css')}>
          <p className="text-xs text-muted">{t('skinEditor.cssHelp')}</p>
          <textarea id="skin-css" className="input font-mono text-xs h-72" spellCheck={false} value={text(doc.css)} maxLength={schema.limits.css} onChange={(event) => draft.at(['css'], event.target.value || undefined)} aria-label={t('skinEditor.section.css')} />
        </Section>
      )}
    </>
  )
}
