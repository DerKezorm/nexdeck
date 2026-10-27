/**
 * The forms of the Look and Rules steps (KARTEN-9 AC-6, AC-7): a value with where it comes from and how it is shown,
 * the rows of a list with filter, order and limit, and a rule. Everything can be picked without typing an
 * expression; whoever wants types one into the same field.
 */
import { Plus, Trash2 } from 'lucide-react'
import { useId, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import type { Document } from 'yaml'

import { deleteAt, expandValueRef, pathText, readIn, setAt, type CardPath } from '../../../lib/cardDocument'
import { hintsOf, treesOf, type Hints } from '../hints'
import { listsOf, rowFieldsOf } from '../probe'
import { cardPath, referencesOf } from '../slots'
import { useCardEditor, useCardField } from '../store'
import { writeText } from '../texts'
import { FieldProblems } from './SourceStep'

export const SHAPES = ['text', 'number', 'bytes', 'rate', 'duration', 'ago', 'percent', 'date', 'datetime', 'time'] as const
export const OPS = ['==', '!=', '>', '>=', '<', '<=', 'contains', 'starts_with', 'ends_with'] as const
export const FNS = ['count', 'sum', 'min', 'max', 'avg'] as const
export const STATUSES = ['ok', 'warn', 'bad'] as const
const SOURCES = ['path', 'formula', 'template', 'total'] as const
type SourceKind = (typeof SOURCES)[number]

const LABEL = 'text-[12px] font-medium text-muted break-words hyphens-auto'

/** What the probes offer on screen: fields, lists and the fields of a row. */
export function useHints(): Hints {
  const card = useCardEditor((state) => state.card ?? state.lastValid?.card ?? null)
  const probes = useCardEditor((state) => state.probes)
  return useMemo(() => hintsOf(card, treesOf(probes)), [card, probes])
}

/** The fields of one row of the list `select`, from the probes. */
function useRowFieldsOf(select: string | undefined): string[] {
  const card = useCardEditor((state) => state.card ?? state.lastValid?.card ?? null)
  const probes = useCardEditor((state) => state.probes)
  return useMemo(() => {
    if (!card || !select) return []
    for (const { requestId, tree } of treesOf(probes)) {
      const list = listsOf(tree).find((one) => cardPath(card, requestId, one.path) === select.trim())
      if (list) return rowFieldsOf(list).map((field) => field.path)
    }
    return []
  }, [card, probes, select])
}

/** The comparisons that look at text only: what they are compared with is kept as typed ("007" is not 7). */
export const TEXT_OPS: readonly string[] = ['contains', 'starts_with', 'ends_with']

/**
 * A typed comparison value: for `contains`, `starts_with` and `ends_with` the text as typed; otherwise a number reads
 * as a number, true and false as yes or no, anything else as text.
 */
export function typedValue(text: string, op?: string): string | number | boolean {
  if (op !== undefined && TEXT_OPS.includes(op)) return text
  const trimmed = text.trim()
  if (trimmed === 'true') return true
  if (trimmed === 'false') return false
  if (trimmed !== '' && /^-?\d+(\.\d+)?$/.test(trimmed)) return Number(trimmed)
  return text
}

/** What stands as the value of a comparison once its operator is `op`: a text operator takes the text of a number. */
export function valueForOp(op: string, value: unknown): unknown {
  return TEXT_OPS.includes(op) && value !== undefined && value !== null && typeof value !== 'string' ? String(value) : value
}

/** A path, picked from the fields of the probe or typed as an expression. */
export function PathInput({ id, value, onChange, choices, disabled, label, placeholder }: { id?: string; value: string; onChange: (value: string) => void; choices: string[]; disabled?: boolean; label?: string; placeholder?: string }) {
  const list = useId()
  return (
    <>
      <input id={id} className="input font-mono min-w-0" list={choices.length ? list : undefined} value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled} aria-label={label} placeholder={placeholder} />
      {choices.length > 0 && (
        <datalist id={list}>
          {[...new Set(choices)].map((choice) => (
            <option key={choice} value={choice} />
          ))}
        </datalist>
      )}
    </>
  )
}

/** Where a value comes from: a path (also written short), a formula, a template or a total. */
export function sourceOf(value: unknown): SourceKind {
  if (value && typeof value === 'object') {
    for (const kind of SOURCES) if ((value as Record<string, unknown>)[kind] !== undefined) return kind
  }
  return 'path'
}

/** The text of a value's source, for the field and for turning one kind into another. */
function sourceText(value: unknown): string {
  if (typeof value === 'string') return value
  if (value && typeof value === 'object') {
    const own = value as Record<string, unknown>
    for (const kind of ['path', 'formula', 'template'] as const) if (typeof own[kind] === 'string') return own[kind] as string
  }
  return ''
}

/** Turn a value into another kind; what it read so far goes along where it can (`{path}` in a formula). */
function changeSource(doc: Document, path: CardPath, to: SourceKind, lists: string[]): void {
  const now = readIn(doc, path)
  const kind = sourceOf(now)
  const text = sourceText(now)
  if (kind === to) return
  const read = kind === 'path' ? text : referencesOf(text)[0] ?? ''
  expandValueRef(doc, path)
  if (readIn(doc, path) === undefined) setAt(doc, path, {})
  for (const one of SOURCES) deleteAt(doc, [...path, one])
  if (to === 'path') setAt(doc, [...path, 'path'], read || '@')
  if (to === 'formula') setAt(doc, [...path, 'formula'], read ? `{${read}}` : '0')
  if (to === 'template') setAt(doc, [...path, 'template'], read ? `{${read}}` : '{@}')
  if (to === 'total') setAt(doc, [...path, 'total'], { fn: 'count', rows: { select: lists[0] ?? (read || '@') } })
}

/**
 * One value of the card (AC-6, AC-7): where it comes from, its format, digits, unit and, outside a row, its label.
 * A value written short (`value: totalRecords`) stays short until something more is set on it.
 */
export function ValueFields({ path, row, title, required, labelled }: { path: CardPath; row?: boolean; title: string; required?: boolean; labelled?: boolean }) {
  const { t } = useTranslation()
  const ids = useId()
  const hints = useHints()
  const editable = useCardEditor((state) => state.card !== null)
  const change = useCardEditor((state) => state.change)
  const [value] = useCardField<unknown>(path)
  const key = pathText(path)
  const kind = sourceOf(value)
  const own = value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
  const there = value !== undefined
  const choices = row ? hints.rowFields : hints.fields

  const write = (part: string, next: unknown) =>
    change((doc) => {
      expandValueRef(doc, path)
      if (next === undefined || next === '') deleteAt(doc, [...path, part])
      else setAt(doc, [...path, part], next)
    }, `field:${key}.${part}`)

  const writeSource = (text: string) =>
    change((doc) => {
      const now = readIn(doc, path)
      if (kind === 'path' && (now === undefined || typeof now === 'string')) {
        // Short it stays; emptied, an optional value goes.
        if (text) setAt(doc, path, text)
        else if (!required) deleteAt(doc, path)
        else setAt(doc, path, text)
        return
      }
      setAt(doc, [...path, kind], text)
    }, `field:${key}.source`)

  const writeText_ = (part: 'label' | 'unit', text: string) =>
    change((doc) => writeText(doc, { id: `${key}.${part}`, path: [...path, part], label: { key: '' }, valueRef: path }, 'en', text), `field:${key}.${part}`)
  const englishOf = (part: 'label' | 'unit') => {
    const text = own[part]
    if (typeof text === 'string') return text
    if (text && typeof text === 'object') return String((text as Record<string, unknown>).en ?? '')
    return ''
  }

  return (
    <fieldset className="grid gap-2 min-w-0 rounded-xl border border-line p-3" data-testid={`card-value-${key}`}>
      <legend className="px-1 text-sm font-medium break-words hyphens-auto">
        {title}
        {required ? ' *' : ''}
      </legend>
      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)] min-w-0">
        <label className="grid gap-1 min-w-0">
          <span className={LABEL}>{t('editor.look.from')}</span>
          <select className="input" value={kind} disabled={!editable} onChange={(event) => change((doc) => changeSource(doc, path, event.target.value as SourceKind, hints.lists))}>
            {SOURCES.filter((one) => !row || one !== 'total').map((one) => (
              <option key={one} value={one}>
                {t(`editor.look.source.${one}`)}
              </option>
            ))}
          </select>
        </label>
        {kind !== 'total' ? (
          <label className="grid gap-1 min-w-0" htmlFor={`${ids}-source`}>
            <span className={LABEL}>{t(`editor.look.sourceField.${kind}`)}</span>
            {kind === 'path' ? (
              <PathInput id={`${ids}-source`} value={sourceText(value)} onChange={writeSource} choices={choices} disabled={!editable} placeholder={t('editor.look.pickField')} />
            ) : (
              <input id={`${ids}-source`} className="input font-mono min-w-0" value={sourceText(value)} disabled={!editable} onChange={(event) => writeSource(event.target.value)} placeholder={t(`editor.look.example.${kind}`)} />
            )}
          </label>
        ) : (
          <TotalFields path={[...path, 'total']} />
        )}
      </div>
      <FieldProblems path={path} />
      {there && (
        <div className="grid gap-2 grid-cols-2 sm:grid-cols-4 min-w-0">
          <label className="grid gap-1 min-w-0">
            <span className={LABEL}>{t('editor.look.format')}</span>
            <select className="input" value={typeof own.format === 'string' ? own.format : ''} disabled={!editable} onChange={(event) => write('format', event.target.value || undefined)}>
              <option value="">{t('editor.look.formatAuto')}</option>
              {SHAPES.map((shape) => (
                <option key={shape} value={shape}>
                  {t(`editor.look.shape.${shape}`)}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 min-w-0">
            <span className={LABEL}>{t('editor.look.digits')}</span>
            <input
              className="input"
              type="number"
              min={0}
              max={6}
              value={typeof own.digits === 'number' ? own.digits : ''}
              disabled={!editable}
              onChange={(event) => write('digits', event.target.value === '' ? undefined : Math.max(0, Math.min(6, Math.round(Number(event.target.value)))))}
            />
          </label>
          <label className="grid gap-1 min-w-0">
            <span className={LABEL}>{t('editor.look.unit')}</span>
            <input className="input" value={englishOf('unit')} disabled={!editable} onChange={(event) => writeText_('unit', event.target.value)} />
          </label>
          {(!row || labelled) && (
            <label className="grid gap-1 min-w-0">
              <span className={LABEL}>{t('editor.look.label')}</span>
              <input className="input" value={englishOf('label')} disabled={!editable} onChange={(event) => writeText_('label', event.target.value)} />
            </label>
          )}
        </div>
      )}
    </fieldset>
  )
}

/** A total over rows (`total`): what is worked out, over which rows, of which field. */
function TotalFields({ path }: { path: CardPath }) {
  const { t } = useTranslation()
  const hints = useHints()
  const editable = useCardEditor((state) => state.card !== null)
  const [fn, setFn] = useCardField<string>([...path, 'fn'])
  const [field, setField] = useCardField<string>([...path, 'field'])
  const [select] = useCardField<string>([...path, 'rows', 'select'])
  const fields = useRowFieldsOf(select)
  return (
    <div className="grid gap-2 min-w-0">
      <div className="grid gap-2 sm:grid-cols-2 min-w-0">
        <label className="grid gap-1 min-w-0">
          <span className={LABEL}>{t('editor.look.fn')}</span>
          <select className="input" value={fn ?? 'count'} disabled={!editable} onChange={(event) => setFn(event.target.value)}>
            {FNS.map((one) => (
              <option key={one} value={one}>
                {t(`editor.look.fns.${one}`)}
              </option>
            ))}
          </select>
        </label>
        {fn !== 'count' && (
          <label className="grid gap-1 min-w-0">
            <span className={LABEL}>{t('editor.look.ofField')}</span>
            <PathInput value={field ?? ''} onChange={(next) => setField(next || undefined)} choices={fields} disabled={!editable} />
          </label>
        )}
      </div>
      <RowsFields path={[...path, 'rows']} total lists={hints.lists} />
    </div>
  )
}

/** Which rows (AC-7): the list they come from, filters, order and how many. A total counts all rows, so no limit there. */
export function RowsFields({ path, total, lists }: { path: CardPath; total?: boolean; lists: string[] }) {
  const { t } = useTranslation()
  const editable = useCardEditor((state) => state.card !== null)
  const change = useCardEditor((state) => state.change)
  const [select, setSelect] = useCardField<string>([...path, 'select'])
  const [filters] = useCardField<{ field?: string; op?: string; value?: unknown }[]>([...path, 'filter'])
  const [sort] = useCardField<{ field?: string; desc?: boolean }>([...path, 'sort'])
  const [limit, setLimit] = useCardField<number>([...path, 'limit'])
  const fields = useRowFieldsOf(select)
  const key = pathText(path)
  const rows = Array.isArray(filters) ? filters : []

  const removeFilter = (index: number) =>
    change((doc) => {
      deleteAt(doc, [...path, 'filter', index])
      const left = readIn(doc, [...path, 'filter'])
      if (Array.isArray(left) && left.length === 0) deleteAt(doc, [...path, 'filter'])
    })
  const writeFilter = (index: number, part: string, next: unknown) => change((doc) => setAt(doc, [...path, 'filter', index, part], next), `field:${key}.filter.${index}.${part}`)
  const writeFilterOp = (index: number, op: string) =>
    change((doc) => {
      setAt(doc, [...path, 'filter', index, 'op'], op)
      const value = readIn(doc, [...path, 'filter', index, 'value'])
      if (valueForOp(op, value) !== value) setAt(doc, [...path, 'filter', index, 'value'], valueForOp(op, value))
    }, `field:${key}.filter.${index}.op`)
  const writeSort = (part: 'field' | 'desc', next: unknown) =>
    change((doc) => {
      if (part === 'field' && !next) return deleteAt(doc, [...path, 'sort'])
      if (part === 'desc' && !next) return deleteAt(doc, [...path, 'sort', 'desc'])
      setAt(doc, [...path, 'sort', part], next)
    }, `field:${key}.sort.${part}`)

  return (
    <div className="grid gap-2 min-w-0" role="group" aria-label={t('editor.look.whichRows')}>
      <label className="grid gap-1 min-w-0">
        <span className={LABEL}>{t('editor.look.rowsFrom')}</span>
        <PathInput value={select ?? ''} onChange={(next) => setSelect(next)} choices={lists} disabled={!editable} placeholder={t('editor.look.pickList')} />
      </label>
      <FieldProblems path={[...path, 'select']} />
      {rows.map((filter, index) => (
        <div key={index} className="flex flex-wrap items-center gap-2 min-w-0" role="group" aria-label={t('editor.look.filter', { number: index + 1 })}>
          <span className="text-sm text-muted break-words hyphens-auto">{t('editor.look.onlyWhere')}</span>
          <span className="min-w-0 flex-1 basis-32 grid">
            <PathInput value={filter?.field ?? ''} onChange={(next) => writeFilter(index, 'field', next)} choices={fields} disabled={!editable} label={t('editor.look.filterField')} />
          </span>
          <select className="input !w-auto" value={filter?.op ?? '=='} disabled={!editable} aria-label={t('editor.look.filterOp')} onChange={(event) => writeFilterOp(index, event.target.value)}>
            {OPS.map((op) => (
              <option key={op} value={op}>
                {t(`editor.ops.${opKey(op)}`)}
              </option>
            ))}
          </select>
          <input
            className="input !w-28 min-w-0"
            value={filter?.value === undefined || filter.value === null ? '' : String(filter.value)}
            disabled={!editable}
            aria-label={t('editor.look.filterValue')}
            onChange={(event) => writeFilter(index, 'value', typedValue(event.target.value, filter?.op))}
          />
          <button type="button" className="btn btn-icon btn-flat" onClick={() => removeFilter(index)} disabled={!editable} aria-label={t('editor.look.removeFilter', { number: index + 1 })}>
            <Trash2 size={14} />
          </button>
        </div>
      ))}
      {rows.length < 10 && (
        <button type="button" className="btn btn-flat justify-self-start" disabled={!editable} onClick={() => change((doc) => setAt(doc, [...path, 'filter', rows.length], { field: fields[0] ?? '@', op: '==', value: '' }))}>
          <Plus size={14} />
          {t('editor.look.addFilter')}
        </button>
      )}
      <div className="flex flex-wrap items-center gap-2 min-w-0">
        <span className="text-sm text-muted break-words hyphens-auto">{t('editor.look.sortBy')}</span>
        <span className="min-w-0 flex-1 basis-32 grid">
          <PathInput value={sort?.field ?? ''} onChange={(next) => writeSort('field', next)} choices={fields} disabled={!editable} label={t('editor.look.sortField')} placeholder={t('editor.look.unsorted')} />
        </span>
        <select className="input !w-auto" value={sort?.desc ? 'desc' : 'asc'} disabled={!editable || !sort?.field} aria-label={t('editor.look.sortOrder')} onChange={(event) => writeSort('desc', event.target.value === 'desc')}>
          <option value="asc">{t('editor.look.ascending')}</option>
          <option value="desc">{t('editor.look.descending')}</option>
        </select>
        {!total && (
          <>
            <span className="text-sm text-muted break-words hyphens-auto">{t('editor.look.show')}</span>
            <input
              className="input !w-20"
              type="number"
              min={1}
              max={50}
              value={typeof limit === 'number' ? limit : ''}
              placeholder="10"
              disabled={!editable}
              aria-label={t('editor.look.limit')}
              onChange={(event) => setLimit(event.target.value === '' ? undefined : Math.max(1, Math.min(50, Math.round(Number(event.target.value)))))}
            />
          </>
        )}
      </div>
    </div>
  )
}

/** The words of a comparison as a key: `>=` is `gte`. */
export function opKey(op: string): string {
  return { '==': 'eq', '!=': 'ne', '>': 'gt', '>=': 'gte', '<': 'lt', '<=': 'lte', contains: 'contains' }[op] ?? op
}

type Rule = { value?: string; formula?: string; op?: string; than?: unknown; then?: string }

/**
 * The rules at `path` (AC-7): what is compared (the value itself, a field, a formula), how, with what, and the
 * colour then. `own` says whether a rule may look at the value it belongs to.
 */
export function RulesFields({ path, own, title, defaultField }: { path: CardPath; own: boolean; title: string; defaultField?: string }) {
  const { t } = useTranslation()
  const hints = useHints()
  const editable = useCardEditor((state) => state.card !== null)
  const change = useCardEditor((state) => state.change)
  const [rules] = useCardField<Rule[]>(path)
  const list = Array.isArray(rules) ? rules : []
  const key = pathText(path)
  const choices = path[0] === 'item' ? hints.rowFields : hints.fields

  const write = (index: number, part: string, next: unknown) => change((doc) => setAt(doc, [...path, index, part], next), `field:${key}.${index}.${part}`)
  const writeOp = (index: number, op: string) =>
    change((doc) => {
      setAt(doc, [...path, index, 'op'], op)
      const than = readIn(doc, [...path, index, 'than'])
      if (valueForOp(op, than) !== than) setAt(doc, [...path, index, 'than'], valueForOp(op, than))
    }, `field:${key}.${index}.op`)
  const writeSubject = (index: number, to: 'own' | 'value' | 'formula') =>
    change((doc) => {
      const rule = (readIn(doc, [...path, index]) ?? {}) as Rule
      deleteAt(doc, [...path, index, 'value'])
      deleteAt(doc, [...path, index, 'formula'])
      if (to === 'value') setAt(doc, [...path, index, 'value'], rule.formula ? referencesOf(rule.formula)[0] ?? defaultField ?? '@' : defaultField ?? '@')
      if (to === 'formula') setAt(doc, [...path, index, 'formula'], rule.value ? `{${rule.value}}` : '0')
    })
  const remove = (index: number) =>
    change((doc) => {
      deleteAt(doc, [...path, index])
      const left = readIn(doc, path)
      if (Array.isArray(left) && left.length === 0) deleteAt(doc, path)
    })
  const add = () =>
    change((doc) => {
      // A value written short (`value: total`) is written out long before a rule can go on it.
      if (path.length > 1) expandValueRef(doc, path.slice(0, -1))
      setAt(doc, [...path, list.length], own ? { op: '>', than: 0, then: 'warn' } : { value: defaultField ?? '@', op: '>', than: 0, then: 'warn' })
    })

  return (
    <fieldset className="grid gap-2 min-w-0 rounded-xl border border-line p-3" data-testid={`card-rules-${key}`}>
      <legend className="px-1 text-sm font-medium break-words hyphens-auto">{title}</legend>
      {list.length === 0 && <p className="text-[12px] text-muted break-words hyphens-auto">{t('editor.rules.none')}</p>}
      {list.map((rule, index) => {
        const subject = rule?.formula !== undefined ? 'formula' : rule?.value !== undefined ? 'value' : 'own'
        return (
          <div key={index} className="flex flex-wrap items-center gap-2 min-w-0" role="group" aria-label={t('editor.rules.rule', { number: index + 1 })}>
            <span className="text-sm text-muted">{t('editor.rules.if')}</span>
            <select className="input !w-auto" value={subject} disabled={!editable} aria-label={t('editor.rules.subject')} onChange={(event) => writeSubject(index, event.target.value as 'own' | 'value' | 'formula')}>
              {own && <option value="own">{t(path[0] === 'item' ? 'editor.rules.rowValue' : 'editor.rules.thisValue')}</option>}
              <option value="value">{t('editor.rules.field')}</option>
              <option value="formula">{t('editor.rules.formula')}</option>
            </select>
            {subject === 'value' && (
              <span className="min-w-0 flex-1 basis-32 grid">
                <PathInput value={rule.value ?? ''} onChange={(next) => write(index, 'value', next)} choices={choices} disabled={!editable} label={t('editor.rules.field')} />
              </span>
            )}
            {subject === 'formula' && (
              <input className="input font-mono min-w-0 flex-1 basis-32" value={rule.formula ?? ''} disabled={!editable} aria-label={t('editor.rules.formula')} onChange={(event) => write(index, 'formula', event.target.value)} />
            )}
            <select className="input !w-auto" value={rule?.op ?? '>'} disabled={!editable} aria-label={t('editor.rules.op')} onChange={(event) => writeOp(index, event.target.value)}>
              {OPS.map((op) => (
                <option key={op} value={op}>
                  {t(`editor.ops.${opKey(op)}`)}
                </option>
              ))}
            </select>
            <input
              className="input !w-24 min-w-0"
              value={rule?.than === undefined || rule.than === null ? '' : String(rule.than)}
              disabled={!editable}
              aria-label={t('editor.rules.than')}
              onChange={(event) => write(index, 'than', typedValue(event.target.value, rule?.op))}
            />
            <span className="text-sm text-muted">{t('editor.rules.then')}</span>
            <select className="input !w-auto" value={rule?.then ?? 'warn'} disabled={!editable} aria-label={t('editor.rules.colour')} onChange={(event) => write(index, 'then', event.target.value)}>
              {STATUSES.map((status) => (
                <option key={status} value={status}>
                  {t(`editor.rules.status.${status}`)}
                </option>
              ))}
            </select>
            <button type="button" className="btn btn-icon btn-flat" onClick={() => remove(index)} disabled={!editable} aria-label={t('editor.rules.remove', { number: index + 1 })}>
              <Trash2 size={14} />
            </button>
          </div>
        )
      })}
      <FieldProblems path={path} />
      {list.length < 10 && (
        <button type="button" className="btn btn-flat justify-self-start" onClick={add} disabled={!editable}>
          <Plus size={14} />
          {t('editor.rules.add')}
        </button>
      )}
    </fieldset>
  )
}
