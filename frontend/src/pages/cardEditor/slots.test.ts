/**
 * The places of a card and the paths of a probe (KARTEN-9 AC-4 to AC-6): what each form has room for, how a field is
 * put on a place, what a change of form takes away, and how a path is read in the tree.
 */
import { describe, expect, it } from 'vitest'

import { changeCard, parseCard, readAt, type CardDoc } from '../../lib/cardDocument'
import { HA_STATES, IMMICH_STORAGE, SONARR_QUEUE } from '../../test/probeAnswers'
import { findsInAnswers, hintsOf, missingOf } from './hints'
import { enclosingList, nodeAt, pathFinds, rowFieldsOf, splitPath } from './probe'
import { assign, cardPath, changeForm, insideRow, lostByForm, placesOf, slotsOf, usedOf } from './slots'

function card(text: string): CardDoc {
  const parsed = parseCard(text)
  if (!parsed.ok) throw new Error(JSON.stringify(parsed.problems))
  return parsed.card
}

const VALUE = { id: 'value', path: ['value'], row: false, label: { key: '' } }
const HEAD = 'nexdeck-card: 1\nslug: q\nname: Q\nversion: "1"\nrequires: [sonarr]\nrequests:\n  - id: queue\n    path: /api/v3/queue\n'

describe('karten9 AC-6: the places of each form', () => {
  it('a number has one value, numbers have one each and one more up to six, a list and pictures their cells', () => {
    expect(slotsOf(card(`${HEAD}form: value\nvalue: a\n`)).map((slot) => slot.id)).toEqual(['value'])
    expect(slotsOf(card(`${HEAD}form: stats\nstats: [a, b]\n`)).map((slot) => slot.id)).toEqual(['stats.0', 'stats.1', 'stats.2'])
    expect(slotsOf(card(`${HEAD}form: stats\nstats: [a, b, c, d, e, f]\n`))).toHaveLength(6)
    expect(slotsOf(card(`${HEAD}form: list\nrows: {select: records}\nitem: {title: t}\n`)).map((slot) => slot.id)).toEqual(['item.title', 'item.subtitle', 'item.value', 'item.link', 'item.image'])
    expect(slotsOf(card(`${HEAD}form: posters\nrows: {select: records}\nitem: {title: t, image: i}\n`)).map((slot) => slot.id)).toEqual(['item.image', 'item.title', 'item.subtitle', 'item.link'])
  })
})

describe('karten9 AC-4 AC-5: paths of the answer as the card reads them', () => {
  it('one request reads from its answer, several from all answers by name', () => {
    const one = card(`${HEAD}form: value\nvalue: a\n`)
    expect(cardPath(one, 'queue', 'records[0].title')).toBe('records[0].title')
    const two = card(HEAD.replace('requests:\n', 'requests:\n  - id: system\n    path: /s\n') + 'form: value\nvalue: a\n')
    expect(cardPath(two, 'queue', 'records[0].title')).toBe('queue.records[0].title')
    expect(cardPath(two, 'queue', '@')).toBe('queue')
    expect(cardPath(two, 'queue', '[0].id')).toBe('queue[0].id')
  })

  it('a path inside a row is read from the row; outside it is no cell of the row', () => {
    expect(insideRow('records', 'records[3].series.title')).toBe('series.title')
    expect(insideRow('records', 'records[3]')).toBe('@')
    expect(insideRow('@', '[1].entity_id')).toBe('entity_id')
    expect(insideRow('records', 'recordsOld[0].x')).toBeNull()
    expect(insideRow('records', 'totalRecords')).toBeNull()
  })

  it('a short value stays short; a long one keeps its label and loses its formula', () => {
    const short = changeCard(card(`${HEAD}form: value\n# the count\nvalue: totalRecords\n`), (doc) => assign(doc, VALUE, 'records[0].sizeleft'))
    expect(short.text).toContain('# the count\nvalue: records[0].sizeleft\n')
    const long = changeCard(card(`${HEAD}form: value\nvalue: {formula: "{a} * 2", label: Waiting}\n`), (doc) => assign(doc, VALUE, 'totalRecords'))
    expect(readAt(long, ['value'])).toEqual({ label: 'Waiting', path: 'totalRecords' })
  })

  it('a cell of each row makes its list the rows of the card', () => {
    const list = card(`${HEAD}form: list\nrows: {select: other}\nitem: {title: t}\n`)
    const done = changeCard(list, (doc) => assign(doc, { id: 'item.subtitle', path: ['item', 'subtitle'], row: true, label: { key: '' } }, 'series.title', 'records'))
    expect(readAt(done, ['rows', 'select'])).toBe('records')
    expect(readAt(done, ['item', 'subtitle'])).toBe('series.title')
  })

  it('marks what the card uses: values by their path, cells inside any row of the list, names in formulas', () => {
    const used = usedOf(card(`${HEAD}form: list\nrows: {select: records}\nitem: {title: series.title, subtitle: {template: "S{season}"}}\n`))
    expect(placesOf(used, 'records[0].series.title').map((slot) => slot.id)).toEqual(['item.title'])
    expect(placesOf(used, 'records[7].series.title').map((slot) => slot.id)).toEqual(['item.title'])
    expect(placesOf(used, 'records[1].season').map((slot) => slot.id)).toEqual(['item.subtitle'])
    expect(placesOf(used, 'totalRecords')).toEqual([])
    const value = usedOf(card(`${HEAD}form: value\nvalue: {formula: "{disk.used} / {disk.total}"}\n`))
    expect(placesOf(value, 'disk.total').map((slot) => slot.id)).toEqual(['value'])
  })
})

describe('karten9 AC-6: a change of form', () => {
  it('names what would go and keeps what the new form can take', () => {
    const value = card(`${HEAD}form: value\nvalue: totalRecords\n`)
    expect(lostByForm(value, 'stats')).toEqual([])
    expect(lostByForm(value, 'list')).toEqual([['value']])
    const stats = changeCard(value, (doc) => changeForm(doc, 'stats'))
    expect(readAt(stats, ['stats'])).toEqual(['totalRecords'])
    expect(readAt(stats, ['value'])).toBeUndefined()
    const list = card(`${HEAD}form: list\nrows: {select: records}\nitem: {title: t, value: v, status: [{op: ">", than: 1, then: warn}]}\nempty: None\n`)
    expect(lostByForm(list, 'posters')).toEqual([['item', 'value'], ['item', 'status']])
    expect(lostByForm(list, 'value')).toEqual([['rows'], ['item'], ['empty']])
    const posters = changeCard(list, (doc) => changeForm(doc, 'posters'))
    expect(readAt(posters, ['item'])).toEqual({ title: 't' })
    expect(readAt(posters, ['rows', 'select'])).toBe('records')
    expect(readAt(posters, ['empty'])).toBe('None')
    const back = changeCard(list, (doc) => changeForm(doc, 'value'))
    expect(readAt(back, ['rows'])).toBeUndefined()
    expect(readAt(back, ['form'])).toBe('value')
  })
})

describe('karten9 AC-3: reading the tree', () => {
  it('splits plain paths and refuses expressions', () => {
    expect(splitPath('records[0].series.title')).toEqual(['records', 0, 'series', 'title'])
    expect(splitPath('"disk size"')).toEqual(['disk size'])
    expect(splitPath('[0].entity_id')).toEqual([0, 'entity_id'])
    expect(splitPath('@')).toEqual([])
    expect(splitPath('length(records)')).toBeNull()
    expect(splitPath('records[?status == `x`]')).toBeNull()
  })

  it('finds a path in the tree, says no when it is missing, and cannot tell inside a part left out', () => {
    const tree = SONARR_QUEUE.tree
    expect(pathFinds(tree, 'records[0].series.title')).toBe(true)
    expect(pathFinds(tree, 'records[1].series.title')).toBe(false)
    expect(pathFinds(tree, 'records[500].title')).toBeNull()
    expect(pathFinds(IMMICH_STORAGE.tree, '"disk size"')).toBe(true)
  })

  it('knows the list a field lies in and the fields of its rows', () => {
    const tree = SONARR_QUEUE.tree
    expect(enclosingList(tree, nodeAt(tree, 'records[0].series.title')!)?.path).toBe('records')
    expect(enclosingList(tree, nodeAt(tree, 'totalRecords')!)).toBeNull()
    expect(rowFieldsOf(nodeAt(tree, 'records')!).map((field) => field.path)).toEqual(['title', 'series.title', 'sizeleft', 'status'])
    expect(rowFieldsOf(HA_STATES.tree).map((field) => field.path)).toEqual(['entity_id', 'state'])
  })
})

describe('karten9 AC-6: what the probe says to the Look step', () => {
  const trees = [{ requestId: 'queue', tree: SONARR_QUEUE.tree }]

  it('offers fields, lists and the fields of the rows, each once', () => {
    const hints = hintsOf(card(`${HEAD}form: list\nrows: {select: records}\nitem: {title: title}\n`), trees)
    expect(hints.lists).toEqual(['records'])
    expect(hints.fields).toContain('records[0].series.title')
    expect(hints.fields).not.toContain('records[1].title')
    expect(hints.rowFields).toEqual(['title', 'series.title', 'sizeleft', 'status'])
  })

  it('names a placed field the answer lacks, on a value and in the first row without it', () => {
    const list = card(`${HEAD}form: list\nrows: {select: records}\nitem: {title: title, subtitle: series.title}\n`)
    expect(missingOf(list, trees, hintsOf(list, trees)).map((one) => [one.slot.id, one.path, one.row])).toEqual([['item.subtitle', 'series.title', 2]])
    const value = card(`${HEAD}form: value\nvalue: totalRecordz\n`)
    expect(missingOf(value, trees, hintsOf(value, trees)).map((one) => [one.slot.id, one.path, one.row])).toEqual([['value', 'totalRecordz', null]])
    expect(findsInAnswers(value, trees, 'queue.totalRecords')).toBe(true)
    expect(findsInAnswers(value, trees, 'length(records)')).toBeNull()
  })
})
