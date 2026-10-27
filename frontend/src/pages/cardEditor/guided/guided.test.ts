/**
 * What the guided way reads from a card and an answer, and what it writes (umbau U1, U5 to U8), without a screen.
 */
import { describe, expect, it } from 'vitest'

import { changeCard, parseCard, readAt, type CardDoc } from '../../../lib/cardDocument'
import { SUGGESTIONS } from '../../../lib/cardSuggestions'
import { answerOf, HA_HOME, PLEX_RECENT, PROXMOX_GUESTS } from '../../../test/probeAnswers'
import { NEW_CARD } from '../templates'
import {
  compare,
  hiddenIn,
  numberOf,
  refusalOf,
  rowMatches,
  shapeFor,
  suggestedForm,
  tableOf,
  thresholdsOf,
  writeLocal,
  writeNumber,
  writeShape,
  writeThresholds,
  type AnswerTable,
} from './guided'

function card(text: string): CardDoc {
  const parsed = parseCard(text)
  if (!parsed.ok) throw new Error('not a card')
  return parsed.card
}

const HEAD = `nexdeck-card: 1
slug: lights
name: Lights
version: "1.0.0"
requires: [homeassistant]
requests:
  - id: states
    path: /api/states
`

const rows = (table: AnswerTable) => {
  if (table.kind !== 'rows') throw new Error('not rows')
  return table
}

describe('umbau U5: the answer as a table', () => {
  it('shows the entries of a list as rows, a field one level down as a column, and how many there are', () => {
    const table = rows(tableOf(HA_HOME.tree, SUGGESTIONS.homeassistant[0]))
    expect(table.list).toBe('@')
    // The suggestion's own order: the name first, what the id says, the state, when it changed.
    expect(table.columns).toEqual(['attributes.friendly_name', 'entity_id', 'state', 'last_changed'])
    expect(table.main).toEqual(table.columns)
    expect(table.rows).toHaveLength(8)
    expect(table.rows[0]).toMatchObject({ entity_id: 'light.kitchen', state: 'on', 'attributes.friendly_name': 'Light kitchen' })
    expect(table.total).toBe(23)
  })

  it('takes the list the suggestion names, else the largest list of entries, and counts the entries the probe left out', () => {
    expect(rows(tableOf(PROXMOX_GUESTS.tree, SUGGESTIONS.proxmox[0])).list).toBe('data')
    expect(rows(tableOf(PLEX_RECENT.tree, null)).list).toBe('MediaContainer.Metadata')
    const cut = answerOf({ records: [{ a: 1 }, { a: 2 }], other: [{ b: 1 }] })
    cut.children![0].more = 1234
    const table = rows(tableOf(cut, null))
    expect(table.list).toBe('records')
    expect(table.total).toBe(1236)
    // Two levels down is too deep for a column; a list inside a row is no column.
    expect(rows(tableOf(answerOf([{ a: { b: { c: 1 } }, d: [1, 2], e: 'x' }]), null)).columns).toEqual(['e'])
  })

  it('shows any other answer as Field | Value', () => {
    const table = tableOf(answerOf({ diskSize: '1 TB', diskUsagePercentage: 42.5, nested: { version: '1.2' } }), null)
    expect(table).toEqual({
      kind: 'fields',
      fields: [
        { path: 'diskSize', value: '1 TB' },
        { path: 'diskUsagePercentage', value: 42.5 },
        { path: 'nested.version', value: '1.2' },
      ],
      main: ['diskSize', 'diskUsagePercentage', 'nested.version'],
    })
    // A suggestion that reads single values says so even when the answer holds a list.
    expect(tableOf(answerOf({ num_dns_queries: 10, top_queried_domains: [{ 'example.com': 4 }] }), SUGGESTIONS.adguard[0]).kind).toBe('fields')
  })
})

describe('umbau U6: comparing as the server does, to mark the rows shown', () => {
  it('starts with, ends with, contains, is, is not, greater and less than', () => {
    expect(compare('starts_with', 'light.kitchen', 'light.')).toBe(true)
    expect(compare('starts_with', 'switch.light.tv', 'light.')).toBe(false)
    expect(compare('ends_with', 'bath_light', 'bath')).toBe(false)
    expect(compare('ends_with', 'sensor.temperature_bath', '_bath')).toBe(true)
    expect(compare('contains', 'living_room', 'ing')).toBe(true)
    expect(compare('==', 'on', 'on')).toBe(true)
    expect(compare('!=', 'running', 'running')).toBe(false)
    expect(compare('>', '21', 20)).toBe(true)
    expect(compare('<', 21, 20)).toBe(false)
    expect(compare('>', 'abc', 'abd')).toBe(false)
    expect(compare('==', true, 'true')).toBe(true)
    // A row without the field is "not equal" to anything and fails every other test.
    expect(compare('!=', null, 'on')).toBe(true)
    expect(compare('starts_with', null, 'on')).toBe(false)
  })

  it('a row matches when it meets every condition', () => {
    const lights = [
      { field: 'entity_id', op: 'starts_with', value: 'light.' },
      { field: 'state', op: '==', value: 'on' },
    ]
    const table = rows(tableOf(HA_HOME.tree, null))
    expect(table.rows.filter((row) => rowMatches(row, lights)).map((row) => row.entity_id)).toEqual(['light.kitchen', 'light.living_room'])
  })
})

describe('umbau U6: a number in the words of the sentences', () => {
  it('reads a count with its conditions, a field, and nothing it cannot say', () => {
    expect(numberOf('totalRecords')).toEqual({ kind: 'field', path: 'totalRecords' })
    expect(numberOf({ path: 'a.b', label: 'x' })).toEqual({ kind: 'field', path: 'a.b' })
    expect(numberOf({ total: { fn: 'count', rows: { select: '@', filter: [{ field: 'state', op: '==', value: 'on' }] } } })).toEqual({
      kind: 'count',
      list: '@',
      conditions: [{ field: 'state', op: '==', value: 'on' }],
    })
    expect(numberOf("length([?state == 'on'])")).toBeNull()
    expect(numberOf({ formula: '{a} * 2' })).toBeNull()
    expect(numberOf({ total: { fn: 'sum', field: 'size', rows: { select: '@' } } })).toBeNull()
    expect(numberOf({ total: { fn: 'count', rows: { select: '@', filter: [{ field: 'n', op: '>=', value: 1 }] } } })).toBeNull()
  })

  it('writes a count, keeping its label, and its colour sentences as rules', () => {
    let one = card(`${HEAD}form: value\nvalue: {path: x, label: Lights on}\n`)
    const lights = { kind: 'count' as const, list: '@', conditions: [{ field: 'entity_id', op: 'starts_with', value: 'light.' }] }
    one = changeCard(one, (doc) => writeNumber(doc, ['value'], lights))
    expect(readAt(one, ['value'])).toEqual({ label: 'Lights on', total: { fn: 'count', rows: { select: '@', filter: [{ field: 'entity_id', op: 'starts_with', value: 'light.' }] } } })
    expect(numberOf(readAt(one, ['value']))).toEqual(lights)
    one = changeCard(one, (doc) => writeThresholds(doc, ['value'], 8, null))
    expect(readAt(one, ['value', 'rules'])).toEqual([{ op: '>=', than: 8, then: 'warn' }])
    expect(thresholdsOf(readAt(one, ['value', 'rules']))).toEqual({ warn: 8, bad: null })
    one = changeCard(one, (doc) => writeThresholds(doc, ['value'], null, null))
    expect(readAt(one, ['value', 'rules'])).toBeUndefined()
    expect(thresholdsOf([{ op: '<', than: 3, then: 'bad' }])).toBeNull()
  })
})

describe('umbau U1: whether the guided way can show all of a card', () => {
  it('can for a new card and for every display it makes itself', () => {
    expect(refusalOf(card(NEW_CARD))).toBeNull()
    for (const [answer, suggestion] of [
      [HA_HOME, SUGGESTIONS.homeassistant[0]],
      [PROXMOX_GUESTS, SUGGESTIONS.proxmox[0]],
      [PLEX_RECENT, SUGGESTIONS.plex[0]],
      [PROXMOX_GUESTS, null],
    ] as const) {
      const table = tableOf(answer.tree, suggestion)
      for (const form of ['value', 'stats', 'list', 'posters'] as const) {
        if (table.kind === 'fields' && (form === 'list' || form === 'posters')) continue
        const made = changeCard(card(`${HEAD}form: value\nvalue: x\n`), (doc) => writeShape(doc, shapeFor(form, table, suggestion)))
        expect([form, refusalOf(made)]).toEqual([form, null])
      }
    }
  })

  it('cannot for an expression, two kinds, two requests, rules of the card or parts it does not know, and says which', () => {
    expect(refusalOf(card(`${HEAD}form: value\nvalue: "length([?state == 'on'])"\n`))).toBe('expression')
    expect(refusalOf(card(HEAD.replace('[homeassistant]', '[jellyfin, emby]') + 'form: value\nvalue: x\n'))).toBe('kinds')
    expect(refusalOf(card(`${HEAD}  - id: more\n    path: /api/config\nform: value\nvalue: x\n`))).toBe('requests')
    expect(refusalOf(card(`${HEAD}form: value\nvalue: x\nrules:\n  - {value: x, op: '>', than: 1, then: warn}\n`))).toBe('rules')
    expect(refusalOf(card(`${HEAD}form: value\nvalue: x\nextras: []\n`))).toBe('parts')
    expect(refusalOf(card(`${HEAD}form: list\nrows: {select: data, limit: 5}\nitem: {title: name}\n`))).toBe('expression')
    expect(refusalOf(card(`${HEAD}form: list\nrows: {select: data}\nitem: {title: {template: "{a} {b}"}}\n`))).toBe('expression')
  })
})

describe('umbau U6: what the card starts as, by what the answer holds', () => {
  it('pictures make a wall of pictures, entries a list, anything else a number; a suggestion has its own start', () => {
    expect(suggestedForm(tableOf(PLEX_RECENT.tree, null))).toBe('posters')
    expect(suggestedForm(tableOf(PROXMOX_GUESTS.tree, null))).toBe('list')
    expect(suggestedForm(tableOf(answerOf({ a: 1 }), null))).toBe('value')
    expect(suggestedForm(tableOf(HA_HOME.tree, null), SUGGESTIONS.homeassistant[0])).toBe('value')

    expect(shapeFor('posters', tableOf(PLEX_RECENT.tree, null))).toEqual({ form: 'posters', list: 'MediaContainer.Metadata', image: 'thumb', title: 'title', subtitle: 'year' })
    expect(shapeFor('list', tableOf(PROXMOX_GUESTS.tree, SUGGESTIONS.proxmox[0]), SUGGESTIONS.proxmox[0])).toEqual({
      form: 'list',
      list: 'data',
      title: 'name',
      subtitle: 'type',
      value: 'mem',
      bad: { field: 'status', op: '!=', value: 'running' },
    })
    expect(shapeFor('value', tableOf(HA_HOME.tree, null), SUGGESTIONS.homeassistant[0])).toEqual({
      form: 'value',
      number: { kind: 'count', list: '@', conditions: [{ field: 'entity_id', op: 'starts_with', value: 'light.' }, { field: 'state', op: '==', value: 'on' }] },
    })
  })
})

describe('umbau U8: a text in the language on screen', () => {
  const spot = { id: 'name', path: ['name'], label: { key: 'editor.texts.name' }, required: true }
  it('in English is a plain text; elsewhere English follows along until it is different', () => {
    let one = card(`${HEAD}form: value\nvalue: x\n`)
    one = changeCard(one, (doc) => writeLocal(doc, spot, 'en', 'Lights on'))
    expect(readAt(one, ['name'])).toBe('Lights on')
    one = changeCard(one, (doc) => writeLocal(doc, spot, 'de', 'Lichter'))
    expect(readAt(one, ['name'])).toEqual({ en: 'Lights on', de: 'Lichter' })
    let fresh = card(`${HEAD.replace('name: Lights', 'name: ""')}form: value\nvalue: x\n`)
    fresh = changeCard(fresh, (doc) => writeLocal(doc, spot, 'de', 'L'))
    fresh = changeCard(fresh, (doc) => writeLocal(doc, spot, 'de', 'Licht'))
    expect(readAt(fresh, ['name'])).toEqual({ en: 'Licht', de: 'Licht' })
  })
})

describe('review 3: a list that the answer leaves out is an empty list', () => {
  const nobody = answerOf({ MediaContainer: { size: 0 } })
  const playing = SUGGESTIONS.plex.find((one) => one.id === 'playing')!

  it('the list a suggestion or a card names is empty when the answer has none, also as []', () => {
    const table = tableOf(nobody, playing)
    expect(table).toEqual({ kind: 'rows', list: 'MediaContainer.Metadata', columns: [], main: [], rows: [], total: 0 })
    expect(tableOf(nobody, null, 'MediaContainer.Metadata')).toMatchObject({ kind: 'rows', total: 0 })
    expect(tableOf(answerOf([]), SUGGESTIONS.homeassistant.find((one) => one.id === 'calendars'))).toMatchObject({ kind: 'rows', list: '@', total: 0 })
    expect(suggestedForm(table, playing)).toBe('list')
    expect(shapeFor('list', table, playing)).toMatchObject({ form: 'list', list: 'MediaContainer.Metadata', title: 'title', subtitle: 'User.title' })
  })

  it('an answer read as single values stays single values, and a list of plain values is not a list of entries', () => {
    expect(tableOf(nobody, null).kind).toBe('fields')
    expect(tableOf(nobody, SUGGESTIONS.homeassistant.find((one) => one.id === 'config')).kind).toBe('fields')
    expect(tableOf(answerOf({ names: ['a', 'b'] }), null, 'names').kind).toBe('fields')
  })
})

describe('review 5: the marking compares text as the server does', () => {
  it('begins with, ends with and contains look at the text of a number or a yes or no', () => {
    expect([compare('starts_with', 21.5, '21'), compare('ends_with', 21.5, '.5'), compare('contains', 2.15, '15'), compare('starts_with', 7, '007')]).toEqual([true, true, true, false])
    expect([compare('starts_with', true, 'tr'), compare('ends_with', false, 'lse'), compare('contains', true, 'ru'), compare('starts_with', 'yes', 'tr')]).toEqual([true, true, true, false])
    // the other comparisons keep reading a yes or no, and a number against a number
    expect([compare('==', true, 'TRUE'), compare('>', true, 1), compare('>', '12', 7)]).toEqual([true, false, true])
  })
})

describe('review 11: a card with colour rules that differ per number is not the guided way\'s to show', () => {
  const stats = (second: string) => `nexdeck-card: 1
slug: numbers
name: Numbers
version: "1.0.0"
requires: [homeassistant]
requests:
  - id: states
    path: /api/states
form: stats
stats:
  - {path: a, rules: [{op: ">=", than: 5, then: warn}]}
  - {path: b, rules: ${second}}
`
  it('the same rules on every number are fine, different ones are not', () => {
    expect(refusalOf(card(stats('[{op: ">=", than: 5, then: warn}]')))).toBeNull()
    expect(refusalOf(card(stats('[{op: ">=", than: 7, then: warn}]')))).toBe('expression')
    expect(refusalOf(card(stats('[]')))).toBe('expression')
  })
})

describe('review 14: Immich photos and videos are numbers, not the list of users', () => {
  const statistics = answerOf({ photos: 1530, videos: 120, usage: 91234567, usageByUser: [{ userId: 'u1', userName: 'kim', photos: 1000, videos: 100 }, { userId: 'u2', userName: 'lee', photos: 530, videos: 20 }] })
  const suggestion = SUGGESTIONS.immich.find((one) => one.id === 'statistics')!

  it('the answer is read as single values, and the first numbers are photos and videos', () => {
    const table = tableOf(statistics, suggestion)
    expect(table.kind).toBe('fields')
    expect(shapeFor('value', table, suggestion)).toEqual({ form: 'value', number: { kind: 'field', path: 'photos' } })
    expect(shapeFor('stats', table, suggestion)).toEqual({ form: 'stats', numbers: [{ kind: 'field', path: 'photos' }, { kind: 'field', path: 'videos' }] })
    expect(suggestedForm(table, suggestion)).toBe('value')
  })
})

describe('review 1: what a choice would put aside', () => {
  const list = (extra: string) => card(`nexdeck-card: 1\nslug: l\nname: L\nversion: "1.0.0"\nrequires: [proxmox]\nrequests:\n  - id: g\n    path: /x\nform: list\nrows: {select: data}\nitem:\n  title: name\n${extra}`)
  it('names the kinds of parts the guided way cannot show, and nothing for a card it shows whole', () => {
    expect(hiddenIn(list(''))).toEqual([])
    expect(hiddenIn(list('  link: {template: "https://x.example.com/{name}"}\n'))).toEqual(['link'])
    expect(hiddenIn(list('  image: thumb\n'))).toEqual(['parts'])
    expect(hiddenIn(list('  status: [{value: a, op: ">", than: 1, then: warn}, {value: b, op: ">", than: 2, then: bad}]\n'))).toEqual(['rowRules'])
    expect(hiddenIn(card(HEAD + 'form: value\nvalue: {formula: "a * 2", label: Double}\n'))).toEqual(['formula'])
    expect(hiddenIn(card(HEAD + 'form: value\nvalue: "length(a)"\n'))).toEqual(['expression'])
    expect(hiddenIn(card(HEAD + 'form: value\nvalue: {path: a, rules: [{op: "<", than: 1, then: bad}]}\nrules: [{value: a, op: ">", than: 1, then: warn}]\n'))).toEqual(['colours', 'cardRules'])
  })
})
