/**
 * The guided way of the card editor: what it reads from a card and writes into it, and what it makes of an answer.
 *
 * The guided way and "All settings" edit the same document. The guided way speaks in sentences ("count the entries
 * where state is on"); each sentence is one part of the card (`value.total.rows.filter`). A card it cannot say in its
 * sentences opens in "All settings" (`coverage`), and a part it cannot say is never thrown away: the step names it
 * and leaves it alone.
 */
import type { Document } from 'yaml'

import { adjustedInYaml, deleteAt, expandValueRef, PLAIN_PATH, readAt, readIn, setAt, type CardDoc, type CardPath, type Shown } from '../../../lib/cardDocument'
import type { CardSuggestion, Condition } from '../../../lib/cardSuggestions'
import type { CardForm } from '../../../lib/customCards'
import { everyNode, nodeAt, rowFieldsOf, splitPath, type ProbeNode } from '../probe'
import { writeText, type TextSpot } from '../texts'

export type GuidedStep = 'service' | 'data' | 'display' | 'finish'
export const GUIDED_STEPS: GuidedStep[] = ['service', 'data', 'display', 'finish']

/** The comparisons of the sentences, in the order they are offered. */
export const GUIDED_OPS = ['==', '!=', 'starts_with', 'ends_with', 'contains', '>', '<'] as const

/** How often the card looks again, as "Look again every" offers it. */
export const GUIDED_EVERY = ['30s', '60s', '5m', '15m', '1h'] as const

/** At most this many rows of the answer are shown in the table. */
export const TABLE_ROWS = 8

// -- the answer as a table ----------------------------------------------------------------------------------------

export type Cell = string | number | boolean | null

export type AnswerTable =
  | { kind: 'rows'; list: string; columns: string[]; rows: Record<string, Cell>[]; total: number }
  | { kind: 'fields'; fields: { path: string; value: Cell }[] }

const scalar = (node: ProbeNode) => node.type !== 'object' && node.type !== 'array'
const isListOfEntries = (node: ProbeNode) => node.type === 'array' && (node.children ?? []).some((child) => child.type === 'object')

/** How many entries a list has, those the probe left out counted too. */
const lengthOf = (node: ProbeNode) => (node.children?.length ?? 0) + (node.more ?? 0)

/** The node at a path inside `from`, if the probe shows it. */
function inside(from: ProbeNode, path: string): ProbeNode | null {
  const parts = splitPath(path)
  if (parts === null) return null
  let node: ProbeNode | undefined = from
  for (const part of parts) {
    node = node.children?.find((child) => child.key === part)
    if (!node) return null
  }
  return node
}

/**
 * The list whose entries are the rows: the one the suggestion names, else the largest list of entries in the answer
 * that is not itself inside a row. `null` when the answer has no list of entries, or the suggestion reads single values.
 */
export function rowsListOf(tree: ProbeNode, suggestion?: CardSuggestion | null, wanted?: string): ProbeNode | null {
  if (suggestion?.fields && !wanted) return null
  for (const path of [wanted, suggestion?.rows]) {
    if (!path) continue
    const named = path === '@' ? tree : nodeAt(tree, path) ?? inside(tree, path)
    if (named && isListOfEntries(named)) return named
  }
  const lists = everyNode(tree).filter((node) => isListOfEntries(node) && !node.path.includes('['))
  return lists.sort((one, two) => lengthOf(two) - lengthOf(one))[0] ?? null
}

/** The first rows of a list of entries, with the plain fields of a row as columns, one level deep at most. */
export function rowsTable(list: ProbeNode): Extract<AnswerTable, { kind: 'rows' }> {
  const columns = rowFieldsOf(list)
    .filter((field) => field.type !== 'object' && field.type !== 'array' && field.path !== '@')
    .filter((field) => (splitPath(field.path)?.length ?? 9) <= 2)
    .map((field) => field.path)
  const rows = (list.children ?? []).slice(0, TABLE_ROWS).map((row) => {
    const cells: Record<string, Cell> = {}
    for (const column of columns) {
      const node = inside(row, column)
      cells[column] = node && scalar(node) ? (node.value ?? null) : null
    }
    return cells
  })
  return { kind: 'rows', list: list.path, columns, rows, total: lengthOf(list) }
}

/** The answer as a table: rows of a list of entries, else every single value as Field | Value. */
export function tableOf(tree: ProbeNode, suggestion?: CardSuggestion | null, wanted?: string): AnswerTable {
  const list = rowsListOf(tree, suggestion, wanted)
  if (list) return rowsTable(list)
  const fields = everyNode(tree)
    .filter((node) => scalar(node) && node.path !== '@')
    .slice(0, 60)
    .map((node) => ({ path: node.path, value: node.value ?? null }))
  return { kind: 'fields', fields }
}

// -- comparing, as the server does ---------------------------------------------------------------------------------

const asNumber = (value: unknown): number | null => {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'string' && /^\s*-?\d+(\.\d+)?\s*$/.test(value)) return Number(value)
  return null
}

/**
 * Whether `left` stands in relation `op` to `right`, the way the card's pipeline compares (`_compare` in
 * `backend/app/cards/pipeline.py`): numbers as numbers, the start and the end as text, everything else as text.
 * Only for marking the rows shown; the number itself always comes from the server.
 */
export function compare(op: string, left: Cell | undefined, right: Cell): boolean {
  if (left === undefined || left === null) return op === '!=' && right !== null
  if (typeof left === 'boolean' || typeof right === 'boolean') {
    const one = String(left).toLowerCase()
    const two = String(right).toLowerCase()
    return op === '==' ? one === two : op === '!=' ? one !== two : false
  }
  if (op === 'starts_with') return right !== null && String(left).startsWith(String(right))
  if (op === 'ends_with') return right !== null && String(left).endsWith(String(right))
  if (op === 'contains') return right !== null && String(left).includes(String(right))
  const two = asNumber(right)
  const one = two !== null ? asNumber(left) : null
  if (one !== null && two !== null) {
    return { '==': one === two, '!=': one !== two, '>': one > two, '>=': one >= two, '<': one < two, '<=': one <= two }[op] ?? false
  }
  if (op === '==') return String(left) === String(right)
  if (op === '!=') return String(left) !== String(right)
  return false
}

export const rowMatches = (row: Record<string, Cell>, conditions: Condition[]) => conditions.every((one) => compare(one.op, row[one.field], one.value as Cell))

// -- the parts of a card in the words of the guided way -----------------------------------------------------------

/** A number of the card: the entries counted (where …), or the value of one field. */
export type NumberPart = { kind: 'count'; list: string; conditions: Condition[] } | { kind: 'field'; path: string }

const plain = (value: unknown): value is string => typeof value === 'string' && PLAIN_PATH.test(value.trim())
const isMap = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value)
const OPS: readonly string[] = GUIDED_OPS

/** A filter of a count, as a condition the sentence can say; `null` for one it cannot. */
function conditionOf(filter: unknown): Condition | null {
  if (!isMap(filter) || !plain(filter.field) || !OPS.includes(String(filter.op))) return null
  const value = filter.value
  if (value !== undefined && value !== null && typeof value === 'object') return null
  return { field: String(filter.field), op: String(filter.op), value: (value ?? '') as Condition['value'] }
}

/** A number in the guided way's words, or `null` when it is a formula, a text with fields or a total of another kind. */
export function numberOf(value: unknown): NumberPart | null {
  if (plain(value)) return { kind: 'field', path: value.trim() }
  if (!isMap(value)) return null
  if (plain(value.path) && value.total === undefined) return { kind: 'field', path: value.path.trim() }
  const total = value.total
  if (value.path !== undefined || !isMap(total) || total.fn !== 'count' || total.field !== undefined) return null
  const rows = total.rows
  if (!isMap(rows) || !plain(rows.select) || rows.sort !== undefined || rows.limit !== undefined) return null
  const filters = Array.isArray(rows.filter) ? rows.filter : rows.filter === undefined ? [] : null
  if (!filters) return null
  const conditions = filters.map(conditionOf)
  if (conditions.some((one) => one === null)) return null
  return { kind: 'count', list: rows.select.trim(), conditions: conditions as Condition[] }
}

/** The colour sentences of a number: yellow from, red from. `null` when its rules say something else. */
export function thresholdsOf(rules: unknown): { warn: number | null; bad: number | null } | null {
  if (rules === undefined) return { warn: null, bad: null }
  if (!Array.isArray(rules)) return null
  const found: { warn: number | null; bad: number | null } = { warn: null, bad: null }
  for (const rule of rules) {
    if (!isMap(rule) || rule.op !== '>=' || typeof rule.than !== 'number' || rule.value !== undefined || rule.formula !== undefined) return null
    if (rule.then !== 'warn' && rule.then !== 'bad') return null
    if (found[rule.then] !== null) return null
    found[rule.then] = rule.than
  }
  return found
}

/** The rule "row red when …" of a list, `undefined` without one, `null` for rules the sentence cannot say. */
export function rowRuleOf(status: unknown): Condition | undefined | null {
  if (status === undefined || (Array.isArray(status) && status.length === 0)) return undefined
  if (!Array.isArray(status) || status.length !== 1) return null
  const rule = status[0]
  if (!isMap(rule) || !plain(rule.value) || rule.then !== 'bad' || !OPS.includes(String(rule.op)) || rule.formula !== undefined) return null
  if (rule.than !== null && typeof rule.than === 'object') return null
  return { field: String(rule.value), op: String(rule.op), value: rule.than as Condition['value'] }
}

/** A cell of a row: a plain field, or a picture made from fields (`{template: …}`) for the picture of a poster. */
export function cellOf(value: unknown, picture = false): string | null {
  if (plain(value)) return value.trim()
  if (!isMap(value)) return null
  const keys = Object.keys(value).filter((key) => !['format', 'digits', 'unit'].includes(key))
  if (keys.length !== 1) return null
  if (keys[0] === 'path' && plain(value.path)) return value.path.trim()
  if (picture && keys[0] === 'template' && typeof value.template === 'string') return value.template
  return null
}

// -- whether the guided way can show a card -----------------------------------------------------------------------

const test = (check: (value: unknown) => boolean): Shown => ({ test: check })
const NUMBER: Shown = test((value) => numberOf(value) !== null && (!isMap(value) || (thresholdsOf(value.rules) !== null && Object.keys(value).every((key) => ['path', 'total', 'label', 'unit', 'format', 'digits', 'rules'].includes(key)))))
const CELL: Shown = test((value) => value === undefined || cellOf(value) !== null)
const PICTURE: Shown = test((value) => cellOf(value, true) !== null)
const ROWS: Shown = test((value) => isMap(value) && plain(value.select) && Object.keys(value).every((key) => key === 'select'))
const STATS_RULES_ALIKE = (stats: unknown) =>
  Array.isArray(stats) && stats.every((one) => JSON.stringify(isMap(one) ? one.rules ?? null : null) === JSON.stringify(isMap(stats[0]) ? stats[0].rules ?? null : null))

/** Everything the guided way shows or keeps as it is; whatever is not here makes the card open in "All settings". */
export const GUIDED_SHOWS: Shown = {
  keys: {
    'nexdeck-card': 'any',
    slug: 'any',
    name: 'any',
    version: 'any',
    min_nexdeck: 'any',
    author: 'any',
    description: 'any',
    category: 'any',
    // One kind of connection: the one the service tile picks.
    requires: test((value) => Array.isArray(value) && value.length <= 1),
    requests: test((value) => Array.isArray(value) && value.length === 1 && isMap(value[0]) && Object.keys(value[0]).every((key) => ['id', 'path', 'every'].includes(key))),
    rules: test((value) => Array.isArray(value) && value.length === 0),
    demo: 'any',
    size: 'any',
    min_size: 'any',
    form: 'any',
    value: NUMBER,
    stats: { items: NUMBER },
    rows: ROWS,
    item: {
      keys: {
        title: CELL,
        subtitle: CELL,
        value: CELL,
        image: PICTURE,
        status: test((value) => rowRuleOf(value) !== null),
      },
    },
    empty: 'any',
  },
}

/** Why a card opens in "All settings". */
export type Refusal = 'kinds' | 'requests' | 'expression' | 'rules' | 'parts'

/** Whether the guided way can show all of a card, and if not, why not (U1). */
export function refusalOf(card: CardDoc): Refusal | null {
  const parts = adjustedInYaml(card, GUIDED_SHOWS)
  const form = readAt(card, ['form'])
  if (form === 'stats' && !STATS_RULES_ALIKE(readAt(card, ['stats']))) parts.push({ path: ['stats'], line: null })
  if (form === 'list' && readAt(card, ['item', 'image']) !== undefined) parts.push({ path: ['item', 'image'], line: null })
  const first = parts[0]?.path[0]
  if (first === undefined) return null
  if (first === 'requires') return 'kinds'
  if (first === 'requests') return 'requests'
  if (first === 'rules') return 'rules'
  if (['value', 'stats', 'rows', 'item'].includes(String(first))) return 'expression'
  return 'parts'
}

// -- writing ------------------------------------------------------------------------------------------------------

/** A number written into the card, its label, unit and colour rules kept. */
export function writeNumber(doc: Document, path: CardPath, part: NumberPart): void {
  if (readIn(doc, path) === undefined) setAt(doc, path, {})
  expandValueRef(doc, path)
  for (const key of ['path', 'formula', 'template', 'total']) deleteAt(doc, [...path, key])
  if (part.kind === 'field') {
    setAt(doc, [...path, 'path'], part.path)
    return
  }
  const rows: Record<string, unknown> = { select: part.list }
  if (part.conditions.length) rows.filter = part.conditions.map((one) => ({ field: one.field, op: one.op, value: one.value }))
  setAt(doc, [...path, 'total'], { fn: 'count', rows })
}

/** The colour sentences into the rules of a number; an empty one is no rule. */
export function writeThresholds(doc: Document, path: CardPath, warn: number | null, bad: number | null): void {
  const rules = [
    ...(warn !== null ? [{ op: '>=', than: warn, then: 'warn' }] : []),
    ...(bad !== null ? [{ op: '>=', than: bad, then: 'bad' }] : []),
  ]
  if (!rules.length) {
    if (readIn(doc, path) !== undefined) deleteAt(doc, [...path, 'rules'])
    return
  }
  expandValueRef(doc, path)
  setAt(doc, [...path, 'rules'], rules)
}

/** A cell of a row into the card: a field, or a picture made from fields; empty takes the place off the card. */
export function writeCell(doc: Document, path: CardPath, field: string): void {
  if (!field) return deleteAt(doc, path)
  setAt(doc, path, field.startsWith('/') || field.includes('{') ? { template: field } : field)
}

/** The rule "row red when …"; without a value there is no rule. */
export function writeRowRule(doc: Document, rule: Condition | null): void {
  if (!rule || rule.value === '') return deleteAt(doc, ['item', 'status'])
  setAt(doc, ['item', 'status'], [{ value: rule.field, op: rule.op, than: rule.value, then: 'bad' }])
}

/** What the card shows, in the guided way's words. */
export type Shape =
  | { form: 'value'; number: NumberPart }
  | { form: 'stats'; numbers: NumberPart[] }
  | { form: 'list'; list: string; title: string; subtitle?: string; value?: string; bad?: Condition }
  | { form: 'posters'; list: string; image: string; title: string; subtitle?: string }

/** Make the card show `shape`: its form and its parts, the parts of another form taken off. */
export function writeShape(doc: Document, shape: Shape): void {
  for (const key of ['value', 'stats', 'rows', 'item', 'rules']) deleteAt(doc, [key])
  setAt(doc, ['form'], shape.form)
  if (shape.form === 'value') writeNumber(doc, ['value'], shape.number)
  else if (shape.form === 'stats') shape.numbers.forEach((number, index) => writeNumber(doc, ['stats', index], number))
  else {
    setAt(doc, ['rows'], { select: shape.list })
    if (shape.form === 'posters') writeCell(doc, ['item', 'image'], shape.image)
    writeCell(doc, ['item', 'title'], shape.title)
    if (shape.subtitle) writeCell(doc, ['item', 'subtitle'], shape.subtitle)
    if (shape.form === 'list') {
      if (shape.value) writeCell(doc, ['item', 'value'], shape.value)
      if (shape.bad) writeRowRule(doc, shape.bad)
    }
  }
}

/**
 * A text of the card in the language on screen. Away from English, English follows along while it is empty or the
 * same as this language, so the card always has the English it needs (KARTEN-1 AC-5); a different English stays.
 */
export function writeLocal(doc: Document, spot: TextSpot, language: string, text: string): void {
  if (language === 'en') return writeText(doc, spot, 'en', text)
  const current = readIn(doc, spot.path)
  const english = typeof current === 'string' ? current : isMap(current) ? String(current.en ?? '') : ''
  const own = isMap(current) ? String(current[language] ?? '') : ''
  if (!english || english === own) writeText(doc, spot, 'en', text)
  writeText(doc, spot, language, text)
}

// -- what the card starts as, from the answer ---------------------------------------------------------------------

const PICTURE_NAME = /thumb|poster|image|cover|picture|photo|art$/i
const PICTURE_VALUE = /\.(jpe?g|png|webp|avif)(\?|$)|\/thumb|\/images?\//i

/** The column that holds a picture, if there is one. */
export function pictureColumn(table: Extract<AnswerTable, { kind: 'rows' }>): string | null {
  return table.columns.find((column) => PICTURE_NAME.test(column) && table.rows.some((row) => typeof row[column] === 'string' && PICTURE_VALUE.test(String(row[column])))) ?? null
}

const textColumns = (table: Extract<AnswerTable, { kind: 'rows' }>) => table.columns.filter((column) => table.rows.some((row) => typeof row[column] === 'string'))
const numberColumns = (table: Extract<AnswerTable, { kind: 'rows' }>) => table.columns.filter((column) => table.rows.some((row) => typeof row[column] === 'number'))

function titleColumn(table: Extract<AnswerTable, { kind: 'rows' }>, not: (string | null)[] = []): string {
  const texts = textColumns(table).filter((one) => !not.includes(one))
  return (
    texts.find((one) => /^(name|title|friendly_name|displayname)$/i.test(one)) ??
    texts.find((one) => /name|title/i.test(one)) ??
    texts[0] ??
    table.columns[0] ??
    '@'
  )
}

/** Which forms the answer allows: pictures only when there are pictures, rows only when there are rows. */
export function formsFor(table: AnswerTable | null, suggestion?: CardSuggestion | null): CardForm[] {
  if (!table || table.kind === 'fields') return ['value', 'stats']
  return pictureColumn(table) || suggestion?.image ? ['value', 'stats', 'list', 'posters'] : ['value', 'stats', 'list']
}

/** The form the content suggests: a picture column makes a wall of pictures, rows a list, anything else a number. */
export function suggestedForm(table: AnswerTable, suggestion?: CardSuggestion | null): CardForm {
  if (suggestion?.preset) return suggestion.preset.form
  if (table.kind === 'fields') return 'value'
  return pictureColumn(table) || suggestion?.image ? 'posters' : 'list'
}

/** The first number of a Field | Value table, else its first field. */
const firstField = (table: Extract<AnswerTable, { kind: 'fields' }>) => (table.fields.find((one) => typeof one.value === 'number') ?? table.fields[0])?.path ?? '@'

/** What a card of `form` starts as for this answer (U6), the suggestion's own start where it has one. */
export function shapeFor(form: CardForm, table: AnswerTable, suggestion?: CardSuggestion | null): Shape {
  const preset = suggestion?.preset?.form === form ? suggestion.preset : null
  if (table.kind === 'fields') {
    const numbers = table.fields.filter((one) => typeof one.value === 'number').map((one) => one.path)
    const first = firstField(table)
    if (form === 'stats') return { form, numbers: [first, numbers.find((one) => one !== first) ?? first].map((path) => ({ kind: 'field' as const, path })) }
    return { form: 'value', number: { kind: 'field', path: first } }
  }
  const all = { kind: 'count' as const, list: table.list, conditions: [] }
  if (form === 'value') return { form, number: preset?.form === 'value' ? { ...all, conditions: preset.count } : all }
  if (form === 'stats') {
    const column = titleColumn(table)
    const one = table.rows[0]?.[column]
    const second = one === undefined || one === null ? all : { ...all, conditions: [{ field: column, op: '==', value: one }] }
    return { form, numbers: [all, second] }
  }
  if (form === 'list') {
    if (preset?.form === 'list') return { form, list: table.list, title: preset.title, subtitle: preset.subtitle, value: preset.value, bad: preset.bad }
    const title = titleColumn(table)
    const subtitle = textColumns(table).find((one) => one !== title && !PICTURE_NAME.test(one))
    return { form, list: table.list, title, subtitle, value: numberColumns(table)[0] }
  }
  if (preset?.form === 'posters') return { form, list: table.list, image: preset.image, title: preset.title, subtitle: preset.subtitle }
  const image = pictureColumn(table) ?? suggestion?.image ?? ''
  const title = titleColumn(table, [image])
  const subtitle = table.columns.find((one) => /year/i.test(one)) ?? textColumns(table).find((one) => one !== title && one !== image)
  return { form: 'posters', list: table.list, image, title, subtitle }
}
