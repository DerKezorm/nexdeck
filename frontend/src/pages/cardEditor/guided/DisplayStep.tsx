import { X } from 'lucide-react'
import { useId, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { pathText, readAt, type CardDoc, type CardPath } from '../../../lib/cardDocument'
import type { CardSuggestion, Condition } from '../../../lib/cardSuggestions'
import type { CardForm } from '../../../lib/customCards'
import { FailureNote } from '../FailureNote'
import { useConnections } from '../connections'
import { usePreviewQuery } from '../Preview'
import { MAX_STATS, MIN_STATS } from '../slots'
import { typedValue, valueForOp } from '../steps/fields'
import { useCardEditor } from '../store'
import { textIn, type TextSpot } from '../texts'
import { AnswerTable } from './AnswerTable'
import { columnLabel } from './columns'
import {
  cellOf,
  changeForm,
  formsFor,
  GUIDED_OPS,
  hiddenIn,
  numberOf,
  refusalOf,
  rowRuleOf,
  shapeFor,
  writeCell,
  writeLocal,
  writeNumber,
  writeRowRule,
  type AnswerTable as Table,
  type NumberPart,
} from './guided'
import { GuidedFrame, StepNav } from './GuidedWay'
import { useReplaceGuard } from './ReplaceGuard'
import { useAnswerTable, useGuidedAnswer } from './useGuided'

const FORMS: { form: CardForm; glyph: string }[] = [
  { form: 'value', glyph: '12' },
  { form: 'stats', glyph: '3 · 7' },
  { form: 'list', glyph: '≡' },
  { form: 'posters', glyph: '▦' },
]
const LABEL = 'text-[12px] font-medium text-muted break-words hyphens-auto'
const SUB = 'text-[12px] uppercase tracking-wide text-faint font-semibold break-words hyphens-auto'

/** The language of the screen, without its region: the language a text of the card is written in. */
export function useLanguage(): string {
  const { i18n } = useTranslation()
  return (i18n.language || 'en').split('-')[0]
}

const useCard = () => useCardEditor((state) => state.card ?? state.lastValid?.card ?? null)

/** The list a card counts in or shows rows of, so that the table shows that one. */
function listOf(card: CardDoc | null): string | undefined {
  if (!card) return undefined
  const form = readAt(card, ['form'])
  if (form === 'list' || form === 'posters') {
    const select = readAt(card, ['rows', 'select'])
    return typeof select === 'string' ? select : undefined
  }
  const values = form === 'stats' ? readAt(card, ['stats']) : [readAt(card, ['value'])]
  const count = (Array.isArray(values) ? values : []).map(numberOf).find((one) => one?.kind === 'count')
  return count?.kind === 'count' ? count.list : undefined
}

/** A part the sentences cannot say: kept as it is, and where to change it. */
export function ExpressionNote() {
  const { t } = useTranslation()
  return (
    <div className="rounded-xl border border-warn/40 px-3 py-2 flex flex-wrap items-center gap-2 min-w-0" role="note" data-testid="card-guided-expression">
      <p className="text-sm min-w-0 flex-1 basis-60 break-words hyphens-auto">{t('editor.guided.display.expression')}</p>
      <button type="button" className="btn" onClick={() => useCardEditor.getState().setView('editor')}>
        {t('editor.guided.display.openAll')}
      </button>
    </div>
  )
}

function opWords(t: (key: string) => string, op: string) {
  return t(`editor.guided.ops.${{ '==': 'eq', '!=': 'ne', '>': 'gt', '<': 'lt' }[op] ?? op}`)
}

/** Column | comparison | value: one condition of a count, or the rule of a row. */
function ConditionFields({ condition, columns, onChange }: { condition: Condition; columns: string[]; onChange: (next: Condition) => void }) {
  const { t } = useTranslation()
  const choices = columns.includes(condition.field) ? columns : [condition.field, ...columns]
  const ops: readonly string[] = GUIDED_OPS.includes(condition.op as (typeof GUIDED_OPS)[number]) ? GUIDED_OPS : [condition.op, ...GUIDED_OPS]
  return (
    <>
      <select className="input !w-auto max-w-full font-mono text-[12.5px]" aria-label={t('editor.guided.display.column')} value={condition.field} onChange={(event) => onChange({ ...condition, field: event.target.value })}>
        {choices.map((one) => (
          <option key={one} value={one}>
            {columnLabel(t, one)}
          </option>
        ))}
      </select>
      <select className="input !w-auto max-w-full" aria-label={t('editor.guided.display.compare')} value={condition.op} onChange={(event) => onChange({ ...condition, op: event.target.value, value: valueForOp(event.target.value, condition.value) as Condition['value'] })}>
        {ops.map((op) => (
          <option key={op} value={op}>
            {opWords(t, op)}
          </option>
        ))}
      </select>
      <input className="input !w-36 max-w-full" aria-label={t('editor.guided.display.value')} value={String(condition.value ?? '')} onChange={(event) => onChange({ ...condition, value: typedValue(event.target.value, condition.op) })} />
    </>
  )
}

/**
 * One number of the card (U6): "Count the entries (where …)" with conditions, or the value of one field, and the
 * label below it. The result is the server's; the rows of the table that the conditions keep are marked.
 */
function NumberFields({ path, table, result, highlight }: { path: CardPath; table: Table | null; result?: string; highlight?: boolean }) {
  const { t, i18n } = useTranslation()
  const ids = useId()
  const language = useLanguage()
  const card = useCard()
  const change = useCardEditor((state) => state.change)
  const part = card ? numberOf(readAt(card, path)) : null
  const key = pathText(path)
  if (!card) return null
  if (!part) return <ExpressionNote />

  const rows = table?.kind === 'rows' ? table : null
  const columns = rows?.columns ?? []
  const write = (next: NumberPart, group?: string) => change((doc) => writeNumber(doc, path, next), group)
  const conditions = part.kind === 'count' ? part.conditions : []
  const setConditions = (next: Condition[], group?: string) => part.kind === 'count' && write({ ...part, conditions: next }, group)
  const fieldChoices = rows
    ? rows.columns.map((column) => ({ path: `${rows.list === '@' ? '@' : rows.list}[0].${column}`, label: t('editor.guided.display.ofFirst', { field: columnLabel(t, column) }) }))
    : table?.kind === 'fields'
      ? table.fields.map((one) => ({ path: one.path, label: columnLabel(t, one.path) }))
      : []
  const fields = part.kind === 'field' && !fieldChoices.some((one) => one.path === part.path) ? [{ path: part.path, label: part.path }, ...fieldChoices] : fieldChoices
  const spot: TextSpot = { id: `${key}.label`, path: [...path, 'label'], label: { key: 'editor.texts.label' }, valueRef: path }

  return (
    <div className="grid gap-3 min-w-0">
      <div className="inline-flex flex-wrap rounded-lg bg-surface p-0.5 gap-0.5 justify-self-start" role="group" aria-label={t('editor.guided.display.how')}>
        {(['count', 'field'] as const).map((one) => (
          <button
            key={one}
            type="button"
            aria-pressed={part.kind === one}
            disabled={one === 'count' && !rows}
            className={`px-2.5 h-7 rounded-md text-[12.5px] break-words hyphens-auto disabled:opacity-50 ${part.kind === one ? 'bg-accent-soft text-ink font-medium' : 'text-muted'}`}
            onClick={() => {
              if (part.kind === one) return
              if (one === 'count' && rows) write({ kind: 'count', list: rows.list, conditions: [] })
              if (one === 'field') write({ kind: 'field', path: fields[0]?.path ?? '@' })
            }}
          >
            {t(one === 'count' ? 'editor.guided.display.howCount' : 'editor.guided.display.howField')}
          </button>
        ))}
      </div>

      {part.kind === 'count' ? (
        <>
          <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-line px-3.5 py-3 text-sm">
            <span>{t('editor.guided.display.count')}</span>
            <span className="text-muted">{conditions.length ? t('editor.guided.display.where') : t('editor.guided.display.all')}</span>
          </div>
          <div className="grid gap-2 min-w-0">
            {conditions.map((condition, index) => (
              <div key={index} className="flex flex-wrap items-center gap-2 min-w-0" role="group" aria-label={`${t('editor.guided.display.where')} ${index + 1}`}>
                <span className="text-[12px] text-faint w-10">{index ? t('editor.guided.display.and') : ''}</span>
                <ConditionFields
                  condition={condition}
                  columns={columns}
                  onChange={(next) => setConditions(conditions.map((one, at) => (at === index ? next : one)), `field:guided.${key}.${index}`)}
                />
                <button type="button" className="btn btn-icon btn-flat" aria-label={t('editor.guided.display.removeCondition')} onClick={() => setConditions(conditions.filter((_, at) => at !== index))}>
                  <X size={15} />
                </button>
              </div>
            ))}
            <div>
              <button type="button" className="text-accent font-medium text-sm" onClick={() => setConditions([...conditions, { field: columns[0] ?? '@', op: '==', value: '' }])}>
                {t('editor.guided.display.addCondition')}
              </button>
            </div>
          </div>
          {rows && (
            <p className="text-[13px] text-muted break-words hyphens-auto" data-testid="card-guided-result">
              {t('editor.guided.display.result')} <strong className="text-ink tabular-nums">{result ?? '…'}</strong>{' '}
              {t('editor.guided.display.resultOf', { number: rows.total.toLocaleString(i18n.language) })}
            </p>
          )}
          {highlight && rows && <AnswerTable table={rows} highlight={conditions} />}
        </>
      ) : (
        <div className="grid gap-1 min-w-0">
          <label className={LABEL} htmlFor={`${ids}-field`}>
            {t('editor.guided.display.field')}
          </label>
          <select id={`${ids}-field`} className="input" value={part.path} onChange={(event) => write({ kind: 'field', path: event.target.value })}>
            {fields.map((one) => (
              <option key={one.path} value={one.path}>
                {one.label}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="grid gap-1 min-w-0">
        <label className={LABEL} htmlFor={`${ids}-label`}>
          {t('editor.guided.display.label')}
        </label>
        <input id={`${ids}-label`} className="input" value={textIn(card, spot, language)} maxLength={40} onChange={(event) => change((doc) => writeLocal(doc, spot, language, event.target.value), `field:guided.${key}.label`)} />
      </div>
    </div>
  )
}

/** A place of a row: which column goes there, and what the first entry has in it. */
function CellSelect({ id, label, place, table, choices, optional }: { id: string; label: string; place: CardPath; table: Extract<Table, { kind: 'rows' }>; choices: { value: string; label: string }[]; optional?: boolean }) {
  const { t } = useTranslation()
  const card = useCard()
  const change = useCardEditor((state) => state.change)
  if (!card) return null
  const raw = readAt(card, place)
  const cell = raw === undefined ? '' : cellOf(raw, place[1] === 'image')
  if (cell === null) {
    return (
      <div className="grid gap-1.5 rounded-xl border border-line px-3 py-2.5 min-w-0">
        <span className={LABEL}>{label}</span>
        <ExpressionNote />
      </div>
    )
  }
  const options = cell && !choices.some((one) => one.value === cell) ? [{ value: cell, label: cell }, ...choices] : choices
  const example = table.rows[0]?.[cell]
  return (
    <div className="grid gap-1.5 rounded-xl border border-line px-3 py-2.5 min-w-0">
      <label className={LABEL} htmlFor={id}>
        {label}
      </label>
      <select id={id} className="input" value={cell} onChange={(event) => change((doc) => writeCell(doc, place, event.target.value))}>
        {optional && <option value="">{t('editor.guided.display.nothing')}</option>}
        {options.map((one) => (
          <option key={one.value} value={one.value}>
            {one.label}
          </option>
        ))}
      </select>
      {example !== undefined && example !== null && example !== '' && <span className="text-[11.5px] text-faint truncate">{t('editor.guided.display.example', { value: String(example) })}</span>}
    </div>
  )
}

/** A list (U6): main text, below it, on the right, and "Line red when …". */
function ListFields({ table }: { table: Extract<Table, { kind: 'rows' }> }) {
  const { t } = useTranslation()
  const ids = useId()
  const card = useCard()
  const change = useCardEditor((state) => state.change)
  const rule = card ? rowRuleOf(readAt(card, ['item', 'status'])) : undefined
  const [draft, setDraft] = useState<Condition>(() => ({ field: table.columns.includes('status') ? 'status' : (table.columns[0] ?? '@'), op: '!=', value: '' }))
  const columns = table.columns.map((one) => ({ value: one, label: columnLabel(t, one) }))
  const shown = rule ?? draft
  return (
    <>
      <p className={SUB}>{t('editor.guided.display.lines')}</p>
      <div className="grid gap-2.5 grid-cols-[repeat(auto-fill,minmax(200px,1fr))] min-w-0">
        <CellSelect id={`${ids}-title`} label={t('editor.guided.display.main')} place={['item', 'title']} table={table} choices={columns} />
        <CellSelect id={`${ids}-subtitle`} label={t('editor.guided.display.below')} place={['item', 'subtitle']} table={table} choices={columns} optional />
        <CellSelect id={`${ids}-value`} label={t('editor.guided.display.right')} place={['item', 'value']} table={table} choices={columns} optional />
      </div>
      {rule === null ? (
        <ExpressionNote />
      ) : (
        <div className="grid gap-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-line px-3.5 py-3 text-sm min-w-0" role="group" aria-label={t('editor.guided.display.rowRed')}>
            <span>{t('editor.guided.display.rowRed')}</span>
            <ConditionFields
              condition={shown}
              columns={table.columns}
              onChange={(next) => {
                setDraft(next)
                change((doc) => writeRowRule(doc, next), 'field:guided.item.status')
              }}
            />
          </div>
          <span className="text-[12px] text-faint break-words hyphens-auto">{t('editor.guided.display.rowRedHint')}</span>
        </div>
      )}
      <AnswerTable table={table} />
    </>
  )
}

/** Pictures (U6): picture, title, below. */
function PosterFields({ table, suggestion }: { table: Extract<Table, { kind: 'rows' }>; suggestion: CardSuggestion | null }) {
  const { t } = useTranslation()
  const ids = useId()
  const card = useCard()
  const columns = table.columns.map((one) => ({ value: one, label: columnLabel(t, one) }))
  const image = card ? cellOf(readAt(card, ['item', 'image']), true) : null
  const pictures = [...(suggestion?.image ? [{ value: suggestion.image, label: t('editor.guided.display.pictureOfEntry') }] : []), ...columns]
  if (image && image.includes('{') && !pictures.some((one) => one.value === image)) pictures.unshift({ value: image, label: t('editor.guided.display.pictureOfEntry') })
  return (
    <>
      <p className={SUB}>{t('editor.guided.display.pictures')}</p>
      <div className="grid gap-2.5 grid-cols-[repeat(auto-fill,minmax(200px,1fr))] min-w-0">
        <CellSelect id={`${ids}-image`} label={t('editor.guided.display.picture')} place={['item', 'image']} table={table} choices={pictures} />
        <CellSelect id={`${ids}-title`} label={t('editor.guided.display.pictureTitle')} place={['item', 'title']} table={table} choices={columns} />
        <CellSelect id={`${ids}-subtitle`} label={t('editor.guided.display.pictureBelow')} place={['item', 'subtitle']} table={table} choices={columns} optional />
      </div>
      <AnswerTable table={table} />
    </>
  )
}

/**
 * Step 3, Display (U6): the four forms, the one the answer suggests already chosen, and the sentences of that form.
 * A form the answer has nothing for cannot be picked. What a sentence cannot say stays as it is (ExpressionNote).
 */
export function DisplayStep() {
  const { t } = useTranslation()
  const card = useCard()
  const { suggestion, probe, path } = useGuidedAnswer()
  const change = useCardEditor((state) => state.change)
  const guard = useReplaceGuard()
  const { chosen, loaded } = useConnections()
  const whole = useAnswerTable()
  const table = useAnswerTable(listOf(card))
  const refusal = useMemo(() => (card ? refusalOf(card) : null), [card])
  // A part inside a number or a cell that the sentences cannot say keeps the forms shut; the others are asked about.
  const locked = useMemo(() => (card ? hiddenIn(card) : []).some((kind) => kind === 'expression' || kind === 'formula' || kind === 'template'), [card])
  const { preview } = usePreviewQuery()
  const form = (card ? readAt(card, ['form']) : 'value') as CardForm
  const offered = formsFor(whole, suggestion)
  const results = preview.data ? [preview.data.primary, ...(preview.data.secondary ?? [])].map((one) => (one ? String((one as { text?: unknown }).text ?? (one as { value?: unknown }).value ?? '') : undefined)) : []
  const stats = card ? readAt(card, ['stats']) : undefined
  const statCount = Array.isArray(stats) ? stats.length : 0

  return (
    <GuidedFrame id="display" title={t('editor.guided.display.title')} lead={t('editor.guided.display.lead')}>
      {refusal && (
        <div className="rounded-xl border border-warn/40 px-3 py-2 flex flex-wrap items-center gap-2 min-w-0" role="note" data-testid="card-guided-refused">
          <p className="text-sm min-w-0 flex-1 basis-60 break-words hyphens-auto">{t('editor.guided.why.text', { why: t(`editor.guided.why.${refusal}`) })}</p>
          <button type="button" className="btn" onClick={() => useCardEditor.getState().setView('editor')}>
            {t('editor.guided.display.openAll')}
          </button>
        </div>
      )}
      <div className="grid gap-2.5 grid-cols-[repeat(auto-fill,minmax(150px,1fr))] min-w-0" role="group" aria-label={t('editor.guided.display.forms')}>
        {FORMS.map(({ form: one, glyph }) => {
          const possible = whole !== null && offered.includes(one) && !locked
          const why = !whole || locked ? undefined : !possible ? t(one === 'posters' && whole.kind === 'rows' ? 'editor.guided.display.formNeedsPictures' : 'editor.guided.display.formNeedsRows') : undefined
          return (
            <button
              key={one}
              type="button"
              aria-pressed={form === one}
              disabled={!possible}
              title={why}
              className={`text-left grid gap-1 rounded-2xl border p-3 min-w-0 disabled:opacity-50 disabled:cursor-not-allowed ${form === one ? 'border-accent ring-[3px] ring-accent/20' : 'border-line hover:bg-surface-hover'}`}
              onClick={() => {
                if (form === one || !whole) return
                // Another form makes the display again: what the guided way cannot show is asked about first.
                guard.ask(() => {
                  // The sentences of the form that is left are kept for the way back, and what both forms know goes along.
                  let memory = useCardEditor.getState().shapeMemory
                  change((doc) => {
                    memory = changeForm(doc, form, one, shapeFor(one, whole, suggestion), memory)
                  })
                  useCardEditor.setState({ shapeMemory: memory })
                })
              }}
            >
              <span className="text-[20px] leading-none text-accent" aria-hidden="true">
                {glyph}
              </span>
              <span className="font-semibold text-sm break-words hyphens-auto">{t(`editor.guided.display.form.${one}.title`)}</span>
              <small className="text-[12px] text-muted break-words hyphens-auto">{t(`editor.guided.display.form.${one}.text`)}</small>
            </button>
          )
        })}
      </div>

      {!table && probe?.status !== 'failed' && path && path !== '/' && chosen && <p className="text-sm text-muted">{t('editor.guided.display.waiting')}</p>}
      {!table && loaded && !chosen && path && path !== '/' && (
        <p className="text-sm text-muted break-words hyphens-auto" role="status" data-testid="card-guided-unanswered">
          {t('editor.guided.display.noAnswer')}
        </p>
      )}
      {probe?.status === 'failed' && probe.path === path && <FailureNote failure={probe} />}

      {form === 'value' && (
        <>
          <p className={SUB}>{t('editor.guided.display.counted')}</p>
          <NumberFields path={['value']} table={table} result={results[0]} highlight />
        </>
      )}
      {form === 'stats' && (
        <>
          {Array.from({ length: statCount }, (_, index) => (
            <section key={index} className="grid gap-2 rounded-2xl border border-line p-3 min-w-0" aria-label={t('editor.guided.display.number', { number: index + 1 })}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-semibold">{t('editor.guided.display.number', { number: index + 1 })}</h3>
                {statCount > MIN_STATS && (
                  <button type="button" className="btn btn-icon btn-flat" aria-label={t('editor.guided.display.removeNumber', { number: index + 1 })} onClick={() => useCardEditor.getState().remove(['stats', index])}>
                    <X size={15} />
                  </button>
                )}
              </div>
              <NumberFields path={['stats', index]} table={table} result={results[index]} />
            </section>
          ))}
          {statCount < MAX_STATS && (
            <div>
              <button
                type="button"
                className="text-accent font-medium text-sm"
                onClick={() =>
                  change((doc) => writeNumber(doc, ['stats', statCount], table?.kind === 'rows' ? { kind: 'count', list: table.list, conditions: [] } : { kind: 'field', path: table?.kind === 'fields' ? (table.fields[0]?.path ?? '@') : '@' }))
                }
              >
                {t('editor.guided.display.addNumber')}
              </button>
            </div>
          )}
          {table && <AnswerTable table={table} />}
        </>
      )}
      {form === 'list' && table?.kind === 'rows' && <ListFields table={table} />}
      {form === 'posters' && table?.kind === 'rows' && <PosterFields table={table} suggestion={suggestion} />}
      {(form === 'list' || form === 'posters') && table?.kind === 'fields' && <ExpressionNote />}

      {guard.dialog}
      <StepNav />
    </GuidedFrame>
  )
}
