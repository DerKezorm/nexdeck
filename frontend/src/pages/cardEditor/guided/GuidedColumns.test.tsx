/**
 * Few columns, each with a name of its own (umbau spalten): the tiles say the kind of a service only when it adds
 * something, a name for people stands only for the field it was meant for, and the table and the choices show the
 * important fields first.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import de from '../../../i18n/editor.de.json'
import { editor, openNew, prepare } from '../../../test/cardEditor'
import en from '../../../i18n/editor.en.json'
import es from '../../../i18n/editor.es.json'
import fr from '../../../i18n/editor.fr.json'
import it_ from '../../../i18n/editor.it.json'
import { SUGGESTIONS } from '../../../lib/cardSuggestions'
import { ANSWERS, stubGuided } from '../../../test/guidedWorld'
import { answerOf, HA_FULL, HA_HOME, PLEX_RECENT } from '../../../test/probeAnswers'
import { columnNames, columnName } from './columns'
import { plainColumns, tableOf } from './guided'

/** The German words of the editor, as the page loads them when the language is German. */
const german = async () => {
  i18next.addResourceBundle('de', 'translation', de, true, true)
  await i18next.changeLanguage('de')
}
const click = async (name: string | RegExp) => userEvent.click(await screen.findByRole('button', { name }))

beforeEach(() => {
  prepare()
  stubGuided()
})

afterEach(async () => {
  vi.unstubAllGlobals()
  await i18next.changeLanguage('en')
})

describe('umbau spalten 2: a name for people belongs to its own field, and no name stands twice', () => {
  it('"ID" is the name of entity_id and of nothing else called ...id; context.id keeps its field name', async () => {
    expect([columnName(i18next.t, 'entity_id'), columnName(i18next.t, 'context.id'), columnName(i18next.t, 'context.parent_id'), columnName(i18next.t, 'attributes.friendly_name')]).toEqual(['ID', 'context.id', 'context.parent_id', 'Name'])
    await german()
    expect([columnName(i18next.t, 'entity_id'), columnName(i18next.t, 'context.id'), columnName(i18next.t, 'last_changed')]).toEqual(['Kennung', 'context.id', 'Geändert'])
  })

  it('two fields that would carry the same name both show their field names', async () => {
    await german()
    // Whatever the words, one table never names two columns alike.
    const names = columnNames(((key: string, options?: { defaultValue?: string }) => (/\.(id|entity_id)$/.test(key) ? 'Kennung' : (options?.defaultValue ?? key))) as never, ['id', 'entity_id', 'title'])
    expect(names).toEqual({ id: 'id', entity_id: 'entity_id', title: 'Title' })
    expect(columnNames(i18next.t, ['state', 'last_changed'])).toEqual({ state: 'Zustand', last_changed: 'Geändert' })
  })

  it('a real answer of Home Assistant gets 21 columns with 21 different names, in German too', async () => {
    await i18next.changeLanguage('de')
    ANSWERS['/api/states'] = HA_FULL
    try {
      await openNew()
      await click(/^Home/)
      await click(/^Geräte und Sensoren/)
      await waitFor(() => expect(editor().shapedPath).toBe('/api/states'))
      await click('Alle Felder zeigen (21)')
      const heads = within(screen.getByTestId('card-answer-table')).getAllByRole('columnheader')
      const names = heads.map((one) => one.firstChild?.textContent ?? '')
      expect(names).toHaveLength(21)
      expect(new Set(names.map((one) => one.toLowerCase())).size).toBe(21)
      expect(names.filter((one) => one === 'Kennung')).toHaveLength(1)
      expect(names).toContain('context.id')
    } finally {
      ANSWERS['/api/states'] = HA_HOME
    }
  })
})


function rowsOf(table: ReturnType<typeof tableOf>) {
  if (table.kind !== 'rows') throw new Error('rows expected')
  return table
}
const WORDS = { en, de, es, fr, it: it_ } as Record<string, unknown>
const wordAt = (data: unknown, key: string) => key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], data)

describe('umbau spalten 1: the important columns of a suggestion', () => {
  it('every suggestion with lists or fields names its columns, and the places its start uses are among them', () => {
    for (const [kind, list] of Object.entries(SUGGESTIONS)) {
      for (const one of list) {
        const label = `${kind}/${one.id}`
        expect([label, Boolean(one.rows || one.fields), Boolean(one.columns?.length)]).toEqual([label, true, true])
        expect([label, new Set(one.columns).size]).toEqual([label, one.columns!.length])
        expect([label, one.columns!.length <= 6]).toEqual([label, true])
        const preset = one.preset
        const used = !preset ? [] : preset.form === 'value' ? preset.count.map((c) => c.field) : preset.form === 'list' ? [preset.title, preset.subtitle, preset.value, preset.bad?.field] : [preset.image, preset.title, preset.subtitle]
        for (const place of used) if (place && !place.includes('{')) expect([label, place, one.columns!.includes(place)]).toEqual([label, place, true])
      }
    }
  })

  it('every column of the catalogue has a name for people in all five languages, and no two of one suggestion share one', () => {
    for (const [language, words] of Object.entries(WORDS)) {
      for (const [kind, list] of Object.entries(SUGGESTIONS)) {
        for (const one of list) {
          const names = one.columns!.map((path) => wordAt(words, `editor.guided.column.${path.toLowerCase().replace(/[^a-z0-9_]+/g, '_')}`))
          expect([language, kind, one.id, names.every((name) => typeof name === 'string')]).toEqual([language, kind, one.id, true])
          expect([language, kind, one.id, new Set((names as string[]).map((name) => name.toLowerCase())).size]).toEqual([language, kind, one.id, names.length])
        }
      }
    }
  })

  it('Home Assistant: four columns in the order of the suggestion, the other 17 behind them', () => {
    const table = rowsOf(tableOf(HA_FULL.tree, SUGGESTIONS.homeassistant[0]))
    expect(table.main).toEqual(['attributes.friendly_name', 'entity_id', 'state', 'last_changed'])
    expect(table.columns.slice(0, 4)).toEqual(table.main)
    expect(table.columns).toHaveLength(21)
    expect(table.columns).toContain('context.parent_id')
  })

  it('a suggestion that names a column the answer lacks leaves it out; one with none of them falls back to the plain rule', () => {
    const table = rowsOf(tableOf(answerOf([{ entity_id: 'light.a', state: 'on' }]), SUGGESTIONS.homeassistant[0]))
    expect(table.main).toEqual(['entity_id', 'state'])
    const other = rowsOf(tableOf(answerOf([{ foo: 1, bar: 'x' }]), SUGGESTIONS.homeassistant[0]))
    expect(other.main).toEqual(['foo', 'bar'])
  })

  it('without a suggestion: at most six, the top level before what lies deeper, long identifiers and empty fields last', () => {
    const table = rowsOf(tableOf(HA_FULL.tree, null))
    expect(table.main).toHaveLength(6)
    expect(table.main).toEqual(['entity_id', 'state', 'last_changed', 'last_reported', 'last_updated', 'attributes.friendly_name'])
    const sample = (path: string) => (path === 'uuid' ? ['0f8fad5b-d9cb-469f-a165-70867728950e'] : path === 'empty' ? [null, null] : path === 'link' ? ['https://example.com/a'] : ['x', 4])
    expect(plainColumns(['uuid', 'a', 'empty', 'link', 'b', 'c', 'd', 'e'], sample)).toEqual(['a', 'b', 'c', 'd', 'e', 'uuid'])
    // Nothing is thrown away: the rest is in `columns`, behind the six.
    expect(table.columns).toHaveLength(21)
    expect(table.columns.slice(0, 6)).toEqual(table.main)
    // A table that has six fields or fewer has nothing to hide.
    expect(rowsOf(tableOf(answerOf([{ a: 1, b: 2 }]), null)).main).toEqual(['a', 'b'])
  })

  it('a Field | Value table names its important fields too', () => {
    const answer = answerOf({ diskSize: '1 TB', diskUse: '300 GB', diskAvailable: '700 GB', diskUsagePercentage: 30, diskSizeRaw: 1, diskUseRaw: 2, extra: 'x' })
    const table = tableOf(answer, SUGGESTIONS.immich[0])
    expect(table.kind === 'fields' && table.main).toEqual(['diskSize', 'diskUse', 'diskAvailable', 'diskUsagePercentage'])
    expect(table.kind === 'fields' && table.fields.map((one) => one.path)).toEqual(['diskSize', 'diskUse', 'diskAvailable', 'diskUsagePercentage', 'diskSizeRaw', 'diskUseRaw', 'extra'])
  })

  it('Plex: the title, the year and what a reader wants of a new entry, not the key and the guid', () => {
    const table = rowsOf(tableOf(PLEX_RECENT.tree, SUGGESTIONS.plex[0]))
    expect(table.main.slice(0, 3)).toEqual(['title', 'year', 'type'])
    expect(table.main).not.toContain('ratingKey')
  })
})

describe('umbau spalten 1 on screen', () => {
  const open = async () => {
    ANSWERS['/api/states'] = HA_FULL
    await openNew()
    await click(/^Home/)
    await click(/^Devices and sensors/)
    await waitFor(() => expect(editor().shapedPath).toBe('/api/states'))
  }
  afterEach(() => {
    ANSWERS['/api/states'] = HA_HOME
  })

  it('the table shows four columns and "Show all fields (21)" opens the rest, and shuts them again', async () => {
    await open()
    const heads = () => within(screen.getByTestId('card-answer-table')).getAllByRole('columnheader').map((one) => one.firstChild?.textContent)
    expect(heads()).toEqual(['Name', 'ID', 'State', 'Changed'])
    await click('Show all fields (21)')
    expect(heads()).toHaveLength(21)
    expect(heads()).toContain('context.id')
    await click('Show the important fields only')
    expect(heads()).toEqual(['Name', 'ID', 'State', 'Changed'])
  })

  it('the choices of a condition list the four first and the rest in the group "More fields"', async () => {
    await open()
    await click('Next')
    const column = screen.getAllByRole('combobox', { name: 'Column' })[0] as HTMLSelectElement
    const direct = Array.from(column.children).map((one) => ((one as HTMLElement).tagName === 'OPTGROUP' ? `group:${(one as HTMLOptGroupElement).label}` : (one as HTMLOptionElement).text))
    expect(direct).toEqual(['Name (attributes.friendly_name)', 'ID (entity_id)', 'state', 'Changed (last_changed)', 'group:More fields'])
    const more = Array.from(column.querySelectorAll('optgroup option')).map((one) => (one as HTMLOptionElement).text)
    expect(more).toHaveLength(17)
    expect(more).toContain('context.id')
    expect(more).not.toContain('ID (context.id)')
  })

  it('the places of a list choose from the same: the important ones first, "More fields" after them', async () => {
    await open()
    await click('Next')
    await click(/^A list/)
    const main = screen.getByRole('combobox', { name: 'Main text' }) as HTMLSelectElement
    expect(Array.from(main.children).map((one) => (one as HTMLElement).tagName)).toEqual(['OPTION', 'OPTION', 'OPTION', 'OPTION', 'OPTGROUP'])
    expect(main.querySelectorAll('optgroup option')).toHaveLength(17)
  })
})
