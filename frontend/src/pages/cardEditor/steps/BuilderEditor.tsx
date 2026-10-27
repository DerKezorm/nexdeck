import { ArrowDown, ArrowUp, ChartLine, Columns3, Gauge, Hash, Image as ImageIcon, List, Minus, MousePointerClick, Rows3, Shapes, Tag, Trash2, Type, TriangleAlert, type LucideIcon } from 'lucide-react'
import { useEffect, useId, useMemo, useRef, useState, type DragEvent, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { LucideByName } from '../../../components/ServiceIcon'
import { Confirm } from '../../../components/ui'
import { colorOf } from '../../../lib/blocks'
import { deleteAt, pathText, readAt, setAt, type CardPath } from '../../../lib/cardDocument'
import {
  addBlock,
  ALIGNS,
  buttonFor,
  BLOCK_COLORS,
  BLOCK_TYPES,
  canAdd,
  childKey,
  countOf,
  dropBlock,
  flatten,
  GAPS,
  GROUPS,
  HEIGHTS,
  mainChoices,
  MAX_BLOCKS,
  moveBlock,
  removeBlock,
  setBlockId,
  SIZES,
  totalOf,
  WEIGHTS,
  type BlockNode,
  type BlockType,
} from '../blocks'
import { buttonsOf, SYMBOLS } from '../buttons'
import { useFit } from '../fit'
import { useCardEditor, useCardField } from '../store'
import { languagesOf, textIn, textSpots, writeText, type TextSpot } from '../texts'
import { RowsFields, useHints, ValueFields } from './fields'
import { FieldProblems } from './SourceStep'
import { languageName } from './TextsStep'

const LABEL = 'text-[12px] font-medium text-muted break-words hyphens-auto'
/** What travels with a block that is dragged: a block of the card by its place, or a new one by its kind. */
const DRAG_TYPE = 'application/x-nexdeck-block'

const MARKS: Record<BlockType, LucideIcon> = {
  row: Columns3,
  column: Rows3,
  divider: Minus,
  text: Type,
  value: Hash,
  badge: Tag,
  symbol: Shapes,
  image: ImageIcon,
  progress: Gauge,
  sparkline: ChartLine,
  list: List,
  button: MousePointerClick,
}

type Dragged = { kind: 'move'; path: CardPath } | { kind: 'new'; type: BlockType }

function readDrag(event: DragEvent): Dragged | null {
  try {
    const raw = event.dataTransfer?.getData(DRAG_TYPE)
    const one = raw ? (JSON.parse(raw) as Dragged) : null
    if (one?.kind === 'move' && Array.isArray(one.path)) return one
    if (one?.kind === 'new' && BLOCK_TYPES.includes(one.type)) return one
  } catch {
    // Something else was dragged here.
  }
  return null
}

const carries = (event: DragEvent) => Boolean(event.dataTransfer?.types?.includes(DRAG_TYPE))

/**
 * The builder (KARTEN-7 AC-1 to AC-5, EC-4 to EC-6), in the Look step of a card of the form "Builder": the twelve
 * blocks in four groups, the tree of the card, and the settings of the block chosen. Tapping a block adds it under the
 * chosen one; on a computer it can be dragged as well. The arrows move a block, with the mouse or from the keyboard.
 * Everything is written into the card's `blocks:`, so the YAML view shows the same.
 */
export function BuilderEditor() {
  const { t } = useTranslation()
  const card = useCardEditor((state) => state.card ?? state.lastValid?.card ?? null)
  const editable = useCardEditor((state) => state.card !== null)
  const change = useCardEditor((state) => state.change)
  const hints = useHints()
  const overflowing = useFit((state) => state.overflowing)
  const [chosen, setChosen] = useState<CardPath | null>(null)
  const [asking, setAsking] = useState<{ path: CardPath; count: number } | null>(null)
  const [over, setOver] = useState<string | null>(null)
  const refocus = useRef<string | null>(null)

  const nodes = useMemo(() => flatten(card), [card])
  const total = useMemo(() => totalOf(card), [card])
  const buttons = useMemo(() => buttonsOf(card), [card])
  // The chosen block, as long as it is still there (a step back may have taken it away).
  const selected = chosen && nodes.some((node) => pathText(node.path) === pathText(chosen)) ? chosen : null
  const full = total >= MAX_BLOCKS

  // After a change the block that moved keeps the focus, so that the next arrow acts on it.
  useEffect(() => {
    if (refocus.current === null) return
    const key = refocus.current
    refocus.current = null
    const target = [...document.querySelectorAll<HTMLElement>('[data-node]')].find((one) => one.dataset.node === key)
    target?.focus()
  }, [card])

  const buttonList = buttons.map((one) => ({ id: String(one.id ?? ''), where: String(one.where ?? 'card') }))
  const options = (onto: CardPath | null) => ({ field: hints.fields[0], button: buttonFor(card, onto, buttonList), lists: hints.lists })

  const add = (type: BlockType, onto: CardPath | null = selected) => {
    if (!card || !canAdd(card, onto, type)) return
    let made: CardPath | null = null
    change((doc) => {
      made = addBlock(doc, card, onto, type, options(onto))
    })
    if (made) {
      setChosen(made)
      refocus.current = pathText(made)
    }
  }

  const move = (path: CardPath, by: -1 | 1) => {
    let now: CardPath | null = null
    change((doc) => {
      now = moveBlock(doc, path, by)
    })
    if (now) {
      setChosen(now)
      refocus.current = pathText(now)
    }
  }

  const take = (path: CardPath) => {
    const count = countOf(card ? readAt(card, path) : undefined)
    // A block with blocks inside takes them with it: say how many first (EC-6).
    if (count > 1) return setAsking({ path, count })
    reallyTake(path)
  }
  const reallyTake = (path: CardPath) => {
    change((doc) => removeBlock(doc, path))
    setChosen(null)
  }

  const dropOn = (event: DragEvent, onto: CardPath | null) => {
    event.preventDefault()
    setOver(null)
    const what = readDrag(event)
    if (!what || !card) return
    if (what.kind === 'new') return add(what.type, onto)
    if (onto === null) return
    let now: CardPath | null = null
    change((doc) => {
      now = dropBlock(doc, card, what.path, onto)
    })
    if (now) setChosen(now)
  }

  const keys = (event: KeyboardEvent, node: BlockNode) => {
    if (event.target !== event.currentTarget) return
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      setChosen(node.path)
    } else if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
      event.preventDefault()
      move(node.path, event.key === 'ArrowUp' ? -1 : 1)
    } else if (event.key === 'Delete') {
      event.preventDefault()
      take(node.path)
    }
  }

  if (!card) return null

  return (
    <div className="grid gap-3 min-w-0 md:grid-cols-[minmax(0,9.5rem)_minmax(0,1fr)] xl:grid-cols-[minmax(0,9.5rem)_minmax(0,1fr)_minmax(0,1.1fr)]" data-testid="card-builder">
      <div className="grid gap-3 content-start min-w-0 grid-cols-2 md:grid-cols-1" role="group" aria-label={t('editor.builder.palette')}>
        {GROUPS.map(({ group, types }) => (
          <div key={group} className="grid gap-1 min-w-0 content-start">
            <h3 className="text-[11px] uppercase tracking-wide text-faint font-semibold break-words">{t(`editor.builder.groups.${group}`)}</h3>
            {types.map((type) => {
              const Mark = MARKS[type]
              const blocked = !editable || !canAdd(card, selected, type) || (type === 'button' && buttonFor(card, selected, buttonList) === '')
              return (
                <button
                  key={type}
                  type="button"
                  className="btn btn-flat justify-start min-w-0"
                  disabled={blocked}
                  draggable={!blocked}
                  title={type === 'button' && blocked && editable && canAdd(card, selected, type) ? t('editor.builder.needButton') : undefined}
                  onClick={() => add(type)}
                  onDragStart={(event) => {
                    event.dataTransfer.setData(DRAG_TYPE, JSON.stringify({ kind: 'new', type } satisfies Dragged))
                    event.dataTransfer.effectAllowed = 'copy'
                  }}
                >
                  <Mark size={14} aria-hidden="true" className="flex-none" />
                  <span className="truncate">{t(`editor.builder.types.${type}`)}</span>
                </button>
              )
            })}
          </div>
        ))}
      </div>

      <div className="grid gap-2 content-start min-w-0">
        <div className="flex flex-wrap items-center justify-between gap-2 min-w-0">
          <h3 className="text-sm font-semibold break-words hyphens-auto">{t('editor.builder.tree')}</h3>
          <span className={`text-[12px] ${full ? 'text-warn' : 'text-muted'}`} data-testid="card-builder-count">
            {t('editor.builder.count', { have: total, max: MAX_BLOCKS })}
          </span>
        </div>
        {full && <p className="text-[12px] text-warn break-words hyphens-auto">{t('editor.builder.full', { max: MAX_BLOCKS })}</p>}
        {overflowing && total > 0 && (
          <p className="rounded-lg border border-warn/40 px-2.5 py-1.5 text-[12px] flex gap-2 items-start break-words hyphens-auto" role="status" data-testid="card-builder-overflow">
            <TriangleAlert size={14} className="flex-none mt-0.5 text-warn" aria-hidden="true" />
            <span>{t('editor.builder.overflow')}</span>
          </p>
        )}

        <div
          role="tree"
          aria-label={t('editor.builder.tree')}
          className={`grid gap-1 content-start min-w-0 rounded-xl border p-1.5 min-h-24 ${over === 'end' ? 'border-accent bg-accent-soft' : 'border-dashed border-line'}`}
          data-testid="card-builder-tree"
          onDragOver={(event) => {
            if (!carries(event)) return
            event.preventDefault()
            setOver('end')
          }}
          onDragLeave={() => setOver(null)}
          onDrop={(event) => {
            // Dropped on the empty part of the tree: a new block goes to the end of the card.
            if (event.target === event.currentTarget) dropOn(event, null)
          }}
        >
          {nodes.length === 0 && <p className="text-[12px] text-muted px-1.5 py-2 break-words hyphens-auto">{t('editor.builder.empty')}</p>}
          {nodes.map((node) => {
            const key = pathText(node.path)
            const isChosen = selected !== null && pathText(selected) === key
            const type = BLOCK_TYPES.includes(node.type as BlockType) ? (node.type as BlockType) : null
            const Mark = type ? MARKS[type] : Shapes
            return (
              <div
                key={key}
                role="treeitem"
                aria-level={node.depth}
                aria-selected={isChosen}
                tabIndex={0}
                data-node={key}
                draggable={editable}
                className={`flex items-center gap-2 min-w-0 rounded-lg border px-2 py-1.5 text-sm cursor-pointer ${isChosen ? 'border-accent/60 bg-accent-soft text-ink' : over === key ? 'border-accent border-dashed' : 'border-line hover:bg-surface-hover'}`}
                style={{ marginLeft: `${(node.depth - 1) * 14}px` }}
                onClick={() => setChosen(node.path)}
                onKeyDown={(event) => keys(event, node)}
                onDragStart={(event) => {
                  event.dataTransfer.setData(DRAG_TYPE, JSON.stringify({ kind: 'move', path: node.path } satisfies Dragged))
                  event.dataTransfer.effectAllowed = 'move'
                }}
                onDragOver={(event) => {
                  if (!carries(event)) return
                  event.preventDefault()
                  event.stopPropagation()
                  setOver(key)
                }}
                onDragLeave={() => setOver(null)}
                onDrop={(event) => {
                  event.stopPropagation()
                  dropOn(event, node.path)
                }}
              >
                <Mark size={14} className="flex-none text-muted" aria-hidden="true" />
                <span className="font-medium flex-none">{type ? t(`editor.builder.types.${type}`) : node.type || '?'}</span>
                <span className="text-[12px] text-muted truncate min-w-0">{summaryOf(node)}</span>
              </div>
            )
          })}
        </div>

        <div className="flex flex-wrap items-center gap-2 min-w-0" role="toolbar" aria-label={t('editor.builder.toolbar')}>
          <button type="button" className="btn btn-flat" disabled={!editable || !selected} onClick={() => selected && move(selected, -1)}>
            <ArrowUp size={14} /> {t('editor.builder.moveUp')}
          </button>
          <button type="button" className="btn btn-flat" disabled={!editable || !selected} onClick={() => selected && move(selected, 1)}>
            <ArrowDown size={14} /> {t('editor.builder.moveDown')}
          </button>
          <button type="button" className="btn btn-flat btn-danger" disabled={!editable || !selected} onClick={() => selected && take(selected)}>
            <Trash2 size={14} /> {t('editor.builder.remove')}
          </button>
        </div>
        <p className="text-[12px] text-faint break-words hyphens-auto">{t('editor.builder.help')}</p>

        <MainValue />
      </div>

      <div className="min-w-0 md:col-span-2 xl:col-span-1">
        {selected ? (
          <BlockSettings path={selected} />
        ) : (
          <p className="text-[13px] text-muted rounded-xl border border-dashed border-line px-3 py-3 break-words hyphens-auto" data-testid="card-builder-nothing">
            {t('editor.builder.chooseOne')}
          </p>
        )}
      </div>

      <Confirm
        open={asking !== null}
        title={t('editor.builder.removeTitle')}
        body={asking ? t('editor.builder.removes', { count: asking.count }) : ''}
        danger
        confirmLabel={t('editor.builder.remove')}
        onCancel={() => setAsking(null)}
        onConfirm={() => {
          if (asking) reallyTake(asking.path)
          setAsking(null)
        }}
      />
    </div>
  )
}

/** A few words that tell two blocks of one kind apart in the tree. */
function summaryOf(node: BlockNode): string {
  const { block } = node
  const text = (value: unknown): string => (typeof value === 'string' ? value : value && typeof value === 'object' ? String((value as Record<string, unknown>).en ?? Object.values(value)[0] ?? '') : '')
  const reads = (value: unknown): string => (typeof value === 'string' ? value : value && typeof value === 'object' ? String((value as Record<string, unknown>).path ?? (value as Record<string, unknown>).formula ?? (value as Record<string, unknown>).template ?? '') : '')
  const parts: string[] = []
  if (typeof block.id === 'string' && block.id) parts.push(`#${block.id}`)
  if (node.type === 'text' || node.type === 'badge') parts.push(block.text !== undefined ? text(block.text) : reads(block.value))
  else if (node.type === 'value') parts.push(text(block.label) || reads(block.path ?? block.formula ?? block.template))
  else if (node.type === 'symbol') parts.push(text(block.icon))
  else if (node.type === 'button') parts.push(text(block.button))
  else if (node.type === 'progress' || node.type === 'sparkline') parts.push(reads(block.value))
  else if (node.type === 'image') parts.push(reads(block.src))
  return parts.filter(Boolean).join(' · ')
}

/** The value that stands for the card in Key figures (AC-8): one of the value blocks that has a short name. */
function MainValue() {
  const { t } = useTranslation()
  const card = useCardEditor((state) => state.card ?? state.lastValid?.card ?? null)
  const editable = useCardEditor((state) => state.card !== null)
  const [main, setMain] = useCardField<string>(['main'])
  const choices = useMemo(() => mainChoices(card), [card])
  const id = useId()
  return (
    <div className="grid gap-1 min-w-0" data-testid="card-builder-main">
      <label htmlFor={id} className={LABEL}>
        {t('editor.builder.main')}
      </label>
      <select id={id} className="input" value={main ?? ''} disabled={!editable} onChange={(event) => setMain(event.target.value || undefined)}>
        <option value="">{t('editor.builder.mainNone')}</option>
        {main && !choices.includes(main) && <option value={main}>{main}</option>}
        {choices.map((one) => (
          <option key={one} value={one}>
            {one}
          </option>
        ))}
      </select>
      <p className="text-[12px] text-faint break-words hyphens-auto">{t(choices.length ? 'editor.builder.mainHelp' : 'editor.builder.mainNeedsId')}</p>
      <FieldProblems path={['main']} />
    </div>
  )
}

// -- the settings of one block ------------------------------------------------------------------------------------

/**
 * The short name of a block. It is written when the field is left (or Enter is pressed), not with every key: the main
 * value follows its block's name, and a name half typed would have it follow a name that is not there yet.
 */
function IdField({ path, id, required }: { path: CardPath; id: string; required: boolean }) {
  const { t } = useTranslation()
  const editable = useCardEditor((state) => state.card !== null)
  const change = useCardEditor((state) => state.change)
  const [draft, setDraft] = useState(id)
  // Another block, a step back or the YAML view changed the name: show that one.
  useEffect(() => setDraft(id), [id, pathText(path)]) // eslint-disable-line react-hooks/exhaustive-deps
  const write = () => {
    if (draft !== id) change((doc) => setBlockId(doc, path, draft.trim()))
  }
  return (
    <label className="grid gap-1 min-w-0">
      <span className={LABEL}>
        {t('editor.builder.fields.id')}
        {required ? ' *' : ''}
      </span>
      <input
        className="input font-mono min-w-0"
        value={draft}
        disabled={!editable}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={write}
        onKeyDown={(event) => {
          if (event.key === 'Enter') write()
        }}
      />
      <FieldProblems path={[...path, 'id']} />
    </label>
  )
}

/** A setting chosen from fixed steps (AC-3): the block writes the name, the screen has the words. */
function Pick({ path, name, options, fallback, label }: { path: CardPath; name: string; options: readonly string[]; fallback: string; label: string }) {
  const { t } = useTranslation()
  const editable = useCardEditor((state) => state.card !== null)
  const [value, set] = useCardField<string>([...path, name])
  const current = value ?? fallback
  return (
    <label className="grid gap-1 min-w-0">
      <span className={LABEL}>{label}</span>
      <select className="input" value={current} disabled={!editable} onChange={(event) => set(event.target.value)}>
        {!options.includes(current) && <option value={current}>{current}</option>}
        {options.map((one) => (
          <option key={one} value={one}>
            {t(`editor.builder.options.${name}.${one}`)}
          </option>
        ))}
      </select>
      <FieldProblems path={[...path, name]} />
    </label>
  )
}

function ColorPick({ path }: { path: CardPath }) {
  const { t } = useTranslation()
  const editable = useCardEditor((state) => state.card !== null)
  const [value, set] = useCardField<string>([...path, 'color'])
  const current = value ?? 'text'
  return (
    <label className="grid gap-1 min-w-0">
      <span className={LABEL}>{t('editor.builder.fields.color')}</span>
      <span className="flex items-center gap-2 min-w-0">
        <span aria-hidden="true" className="flex-none w-4 h-4 rounded-full border border-line" style={{ background: colorOf(current) }} />
        <select className="input min-w-0 flex-1" value={current} disabled={!editable} onChange={(event) => set(event.target.value)}>
          {!(BLOCK_COLORS as readonly string[]).includes(current) && <option value={current}>{current}</option>}
          {BLOCK_COLORS.map((one) => (
            <option key={one} value={one}>
              {t(`editor.builder.options.color.${one}`)}
            </option>
          ))}
        </select>
      </span>
      <FieldProblems path={[...path, 'color']} />
    </label>
  )
}

/** The text of a block in every language the card is written in; the English one is the one that has to be there. */
function TextFields({ spot }: { spot: TextSpot }) {
  const { t, i18n } = useTranslation()
  const card = useCardEditor((state) => state.card ?? state.lastValid?.card ?? null)
  const editable = useCardEditor((state) => state.card !== null)
  const change = useCardEditor((state) => state.change)
  const spots = useMemo(() => (card ? textSpots(card) : []), [card])
  const languages = useMemo(() => (card ? languagesOf(card, spots) : ['en']), [card, spots])
  if (!card) return null
  return (
    <div className="grid gap-2 min-w-0">
      {languages.map((code) => {
        const name = code === 'en' ? t('editor.texts.englishRequired') : languageName(code, i18n.language)
        const value = textIn(card, spot, code)
        return (
          <label key={code} className="grid gap-1 min-w-0">
            <span className={LABEL}>
              {t('editor.builder.fields.text')}, {name}
            </span>
            <input className="input" lang={code} value={value} disabled={!editable} aria-invalid={code === 'en' && !value ? true : undefined} onChange={(event) => change((doc) => writeText(doc, spot, code, event.target.value), `text:${spot.id}:${code}`)} />
          </label>
        )
      })}
    </div>
  )
}

/** A text block and a badge show a fixed text or a value of the data; the choice is here, the fields follow it. */
function TextOrValue({ path, title }: { path: CardPath; title: string }) {
  const { t } = useTranslation()
  const editable = useCardEditor((state) => state.card !== null)
  const change = useCardEditor((state) => state.change)
  const hints = useHints()
  const [block] = useCardField<Record<string, unknown>>(path)
  const inList = path.includes('item')
  const kind = block?.value !== undefined && block?.text === undefined ? 'value' : 'text'
  const spot: TextSpot = { id: `${pathText(path)}.text`, path: [...path, 'text'], label: { key: 'editor.texts.blockText' }, required: true }
  return (
    <div className="grid gap-2 min-w-0">
      <label className="grid gap-1 min-w-0">
        <span className={LABEL}>{t('editor.builder.fields.shows')}</span>
        <select
          className="input"
          value={kind}
          disabled={!editable}
          onChange={(event) =>
            change((doc) => {
              if (event.target.value === 'text') {
                deleteAt(doc, [...path, 'value'])
                setAt(doc, [...path, 'text'], 'Text')
              } else {
                deleteAt(doc, [...path, 'text'])
                setAt(doc, [...path, 'value'], { path: (inList ? hints.rowFields[0] : hints.fields[0]) ?? '@' })
              }
            })
          }
        >
          <option value="text">{t('editor.builder.fields.fixed')}</option>
          <option value="value">{t('editor.builder.fields.fromData')}</option>
        </select>
      </label>
      {kind === 'text' ? <TextFields spot={spot} /> : <ValueFields path={[...path, 'value']} row={inList} title={title} required />}
      <FieldProblems path={[...path, 'text']} />
    </div>
  )
}

function BlockSettings({ path }: { path: CardPath }) {
  const { t } = useTranslation()
  const card = useCardEditor((state) => state.card ?? state.lastValid?.card ?? null)
  const editable = useCardEditor((state) => state.card !== null)
  const change = useCardEditor((state) => state.change)
  const hints = useHints()
  const [block] = useCardField<Record<string, unknown>>(path)
  const key = pathText(path)
  const buttons = useMemo(() => buttonsOf(card), [card])
  const symbols = useId()
  const type = typeof block?.type === 'string' ? block.type : ''
  const inList = path.includes('item')
  const needsId = type === 'sparkline'

  if (!block || !type) return null
  // A button of a row stands on each row of the list, one of the card on the card itself.
  const fits = buttons.filter((one) => (inList ? one.where === 'row' : one.where !== 'row'))
  const chosenButton = typeof block.button === 'string' ? block.button : ''

  return (
    <fieldset className="grid gap-3 min-w-0 rounded-xl border border-line p-3 content-start" data-testid={`card-block-${key}`}>
      <legend className="px-1 text-sm font-medium break-words hyphens-auto">{t('editor.builder.settings', { name: t(`editor.builder.types.${type}`, { defaultValue: type }) })}</legend>

      <IdField path={path} id={typeof block.id === 'string' ? block.id : ''} required={needsId} />

      {(type === 'row' || type === 'column') && <Pick path={path} name="gap" options={GAPS} fallback="m" label={t('editor.builder.fields.gap')} />}
      {type === 'row' && (
        <>
          <Pick path={path} name="align" options={ALIGNS} fallback="start" label={t('editor.builder.fields.align')} />
          <label className="flex items-center gap-2 text-sm min-w-0">
            <input type="checkbox" checked={block.wrap !== false} disabled={!editable} onChange={(event) => change((doc) => setAt(doc, [...path, 'wrap'], event.target.checked), `field:${key}.wrap`)} />
            <span className="break-words hyphens-auto">{t('editor.builder.fields.wrap')}</span>
          </label>
        </>
      )}
      {type === 'divider' && <p className="text-[12px] text-muted break-words hyphens-auto">{t('editor.builder.noSettings')}</p>}

      {type === 'text' && (
        <>
          <TextOrValue path={path} title={t('editor.builder.fields.value')} />
          <div className="grid gap-2 grid-cols-2 min-w-0">
            <Pick path={path} name="size" options={SIZES} fallback="m" label={t('editor.builder.fields.size')} />
            <Pick path={path} name="weight" options={WEIGHTS} fallback="normal" label={t('editor.builder.fields.weight')} />
          </div>
          <ColorPick path={path} />
        </>
      )}

      {type === 'value' && (
        <>
          <ValueFields path={path} row={inList} labelled title={t('editor.builder.fields.value')} required />
          <Pick path={path} name="size" options={SIZES} fallback="m" label={t('editor.builder.fields.size')} />
          <ColorPick path={path} />
          {!(typeof block.id === 'string' && block.id) && <p className="text-[12px] text-faint break-words hyphens-auto">{t('editor.builder.valueNeedsId')}</p>}
        </>
      )}

      {type === 'badge' && (
        <>
          <TextOrValue path={path} title={t('editor.builder.fields.value')} />
          <ColorPick path={path} />
        </>
      )}

      {type === 'symbol' && (
        <>
          <label className="grid gap-1 min-w-0">
            <span className={LABEL}>{t('editor.builder.fields.icon')}</span>
            <span className="flex items-center gap-2 min-w-0">
              <input className="input font-mono min-w-0 flex-1" list={symbols} value={typeof block.icon === 'string' ? block.icon : ''} disabled={!editable} onChange={(event) => change((doc) => setAt(doc, [...path, 'icon'], event.target.value), `field:${key}.icon`)} />
              {typeof block.icon === 'string' && block.icon ? <LucideByName name={block.icon} size={16} /> : null}
            </span>
            <datalist id={symbols}>
              {SYMBOLS.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
            <FieldProblems path={[...path, 'icon']} />
          </label>
          <Pick path={path} name="size" options={SIZES} fallback="m" label={t('editor.builder.fields.size')} />
          <ColorPick path={path} />
        </>
      )}

      {type === 'image' && (
        <>
          <ValueFields path={[...path, 'src']} row={inList} title={t('editor.builder.fields.address')} required />
          <Pick path={path} name="height" options={HEIGHTS} fallback="m" label={t('editor.builder.fields.height')} />
          <p className="text-[12px] text-faint break-words hyphens-auto">{t('editor.builder.imageHelp')}</p>
        </>
      )}

      {type === 'progress' && (
        <>
          <ValueFields path={[...path, 'value']} row={inList} title={t('editor.builder.fields.value')} required />
          <label className="grid gap-1 min-w-0">
            <span className={LABEL}>{t('editor.builder.fields.max')}</span>
            {typeof block.max === 'number' || block.max === undefined ? (
              <input
                className="input"
                type="number"
                min={1}
                value={typeof block.max === 'number' ? block.max : ''}
                placeholder="100"
                disabled={!editable}
                onChange={(event) =>
                  change((doc) => {
                    if (event.target.value === '') deleteAt(doc, [...path, 'max'])
                    else setAt(doc, [...path, 'max'], Number(event.target.value))
                  }, `field:${key}.max`)
                }
              />
            ) : (
              <span className="text-[12px] text-muted break-words hyphens-auto">{t('editor.builder.maxFromData')}</span>
            )}
            <FieldProblems path={[...path, 'max']} />
          </label>
          <ColorPick path={path} />
        </>
      )}

      {type === 'sparkline' && (
        <>
          <ValueFields path={[...path, 'value']} row={inList} title={t('editor.builder.fields.value')} required />
          <p className="text-[12px] text-faint break-words hyphens-auto">{t('editor.builder.sparklineHelp')}</p>
        </>
      )}

      {type === 'list' && (
        <>
          <p className="text-[12px] text-muted break-words hyphens-auto">{t('editor.builder.listHelp', { max: 50 })}</p>
          <RowsFields path={['rows']} lists={hints.lists} />
        </>
      )}

      {type === 'button' && (
        <label className="grid gap-1 min-w-0">
          <span className={LABEL}>{t('editor.builder.fields.button')}</span>
          <select className="input" value={chosenButton} disabled={!editable} onChange={(event) => change((doc) => setAt(doc, [...path, 'button'], event.target.value), `field:${key}.button`)}>
            {chosenButton === '' && <option value="">{t('editor.builder.fields.pickButton')}</option>}
            {chosenButton !== '' && !fits.some((one) => one.id === chosenButton) && <option value={chosenButton}>{chosenButton}</option>}
            {fits.map((one) => (
              <option key={String(one.id)} value={String(one.id)}>
                {buttonName(one)}
              </option>
            ))}
          </select>
          <span className="text-[12px] text-faint break-words hyphens-auto">{t(inList ? 'editor.builder.buttonInList' : 'editor.builder.buttonOnCard')}</span>
          <FieldProblems path={[...path, 'button']} />
        </label>
      )}

      {childKey(type) !== null && <p className="text-[12px] text-faint break-words hyphens-auto">{t('editor.builder.containerHelp')}</p>}
    </fieldset>
  )
}

/** A button as the list offers it: its short name and its words. */
function buttonName(button: Record<string, unknown>): string {
  const label = button.label
  const words = typeof label === 'string' ? label : label && typeof label === 'object' ? String((label as Record<string, unknown>).en ?? Object.values(label)[0] ?? '') : ''
  return words ? `${button.id} · ${words}` : String(button.id)
}

