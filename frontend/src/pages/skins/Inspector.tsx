/**
 * The right column of the skin editor: the part clicked on the stage, and what
 * the skin gives it. A frame, a motion, a sound and decorations are data of the
 * second layer; with "Advanced" on, a rule of the skin's own style sheet for
 * just this part, started with the selector already written.
 */
import { Plus, Trash2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import type { Draft, SkinDoc } from '../../lib/skin/draft'
import { NumberField, SpriteSelect } from './FilePanels'
import type { SkinSchema } from './SkinEditorPage'

type Record_ = Record<string, unknown>
const record = (value: unknown): Record_ => (value && typeof value === 'object' && !Array.isArray(value) ? (value as Record_) : {})
const list = (value: unknown): Record_[] => (Array.isArray(value) ? (value as Record_[]) : [])

export function Inspector({ part, doc, draft, schema, advanced, onAdvanced }: { part: string | null; doc: SkinDoc; draft: Draft; schema: SkinSchema; advanced: boolean; onAdvanced: () => void }) {
  const { t } = useTranslation()
  if (!part || !schema.parts[part]) return <p className="text-sm text-muted">{t('skinEditor.pickHelp')}</p>
  const entry = schema.parts[part]
  const look = record(record(doc.parts)[part])
  const motion = record(look.motion)
  const decorations = list(doc.decorations)
  const mine = decorations.map((decoration, index) => ({ decoration, index })).filter(({ decoration }) => decoration.part === part)
  const setLook = (field: string, value: unknown) => {
    const next = { ...look, [field]: value }
    for (const [name, inner] of Object.entries(next)) if (inner === undefined) delete next[name]
    draft.at(['parts', part], Object.keys(next).length ? next : undefined)
  }
  const states = Object.keys(entry.states ?? {})
  return (
    <div className="flex flex-col gap-3" data-testid="skin-inspector">
      <div>
        <p className="font-mono text-sm">{part}</p>
        <p className="text-xs text-muted">{entry.label}</p>
      </div>

      <label className="flex items-center gap-2 text-xs">
        <span className="w-24 shrink-0 text-muted">{t('skinEditor.frame')}</span>
        <select className="input h-8 text-xs flex-1" value={typeof look.frame === 'string' ? look.frame : ''} onChange={(event) => setLook('frame', event.target.value || undefined)} aria-label={t('skinEditor.frame')}>
          <option value="">{t('skinEditor.none')}</option>
          {Object.keys(record(doc.frames)).map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </label>

      <div className="flex flex-col gap-1">
        <label className="flex items-center gap-2 text-xs">
          <span className="w-24 shrink-0 text-muted">{t('skinEditor.motion')}</span>
          <select className="input h-8 text-xs flex-1" value={typeof motion.name === 'string' ? motion.name : ''} onChange={(event) => setLook('motion', event.target.value ? { on: 'hover', ms: 400, ...motion, name: event.target.value } : undefined)} aria-label={t('skinEditor.motion')}>
            <option value="">{t('skinEditor.none')}</option>
            {schema.motions.map((name) => (
              <option key={name} value={name}>
                {t(`skinEditor.motions.${name}`)}
              </option>
            ))}
          </select>
        </label>
        {motion.name ? (
          <>
            <label className="flex items-center gap-2 text-xs">
              <span className="w-24 shrink-0 text-muted">{t('skinEditor.when')}</span>
              <select className="input h-8 text-xs flex-1" value={String(motion.on ?? 'hover')} onChange={(event) => setLook('motion', { ...motion, on: event.target.value })} aria-label={t('skinEditor.when')}>
                {['hover', 'press', 'always'].map((on) => (
                  <option key={on} value={on}>
                    {t(`skinEditor.on.${on}`)}
                  </option>
                ))}
              </select>
            </label>
            <NumberField label={t('skinEditor.length')} value={motion.ms as number} min={schema.limits.animation_ms[0]} max={schema.limits.animation_ms[1]} step={10} onChange={(ms) => setLook('motion', { ...motion, ms })} />
          </>
        ) : null}
      </div>

      <label className="flex items-center gap-2 text-xs">
        <span className="w-24 shrink-0 text-muted">{t('skinEditor.sound')}</span>
        <select className="input h-8 text-xs flex-1" value={typeof look.sound === 'string' ? look.sound : ''} onChange={(event) => setLook('sound', event.target.value || undefined)} aria-label={t('skinEditor.sound')}>
          <option value="">{t('skinEditor.none')}</option>
          {Object.keys(record(doc.sounds)).map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </label>

      <div className="flex flex-col gap-2">
        <p className="text-xs font-medium">{t('skinEditor.decorations')}</p>
        {entry.pseudo.length === 0 && <p className="text-xs text-faint">{t('skinEditor.noDecorations')}</p>}
        {mine.map(({ decoration, index }) => (
          <div key={index} className="flex flex-col gap-1 rounded border border-line p-2">
            <div className="flex items-center gap-1">
              <select className="input h-8 text-xs flex-1" value={String(decoration.anchor)} onChange={(event) => draft.at(['decorations', index, 'anchor'], event.target.value)} aria-label={t('skinEditor.anchor')}>
                {schema.anchors.map((anchor) => (
                  <option key={anchor} value={anchor}>
                    {t(`skinEditor.anchors.${anchor}`)}
                  </option>
                ))}
              </select>
              <button type="button" className="btn btn-flat btn-icon" onClick={() => draft.at(['decorations', index], undefined)} aria-label={t('skinEditor.remove')}>
                <Trash2 size={12} />
              </button>
            </div>
            <SpriteSelect doc={doc} label={t('skinEditor.sprite')} value={decoration.sprite} empty={false} onChange={(value) => draft.at(['decorations', index, 'sprite'], value)} />
            <NumberField label={t('skinEditor.size')} value={decoration.size as number} min={8} max={32} onChange={(value) => draft.at(['decorations', index, 'size'], value)} />
            <NumberField label={t('skinEditor.offset')} value={decoration.offset as number} min={-16} max={16} onChange={(value) => draft.at(['decorations', index, 'offset'], value)} />
          </div>
        ))}
        {mine.length < entry.pseudo.length && Object.keys(record(doc.sprites)).length > 0 && (
          <button type="button" className="btn self-start" onClick={() => draft.at(['decorations', decorations.length], { part, anchor: 'top-right', sprite: Object.keys(record(doc.sprites))[0], size: 16 })}>
            <Plus size={14} /> {t('skinEditor.addDecoration')}
          </button>
        )}
      </div>

      <div className="flex flex-col gap-1 border-t border-line pt-3">
        <p className="text-xs font-medium">{t('skinEditor.ownRule')}</p>
        {states.length > 0 && <p className="text-[11px] text-faint">{t('skinEditor.states', { states: states.map((state) => `:state(${state})`).join(', ') })}</p>}
        <button
          type="button"
          className="btn self-start"
          onClick={() => {
            const css = typeof doc.css === 'string' ? doc.css : ''
            draft.set({ ...doc, css: `${css}${css && !css.endsWith('\n') ? '\n' : ''}[data-part=${part}] {\n  \n}\n` })
            onAdvanced()
          }}
        >
          <Plus size={14} /> {advanced ? t('skinEditor.addRule') : t('skinEditor.addRuleAdvanced')}
        </button>
      </div>
    </div>
  )
}
