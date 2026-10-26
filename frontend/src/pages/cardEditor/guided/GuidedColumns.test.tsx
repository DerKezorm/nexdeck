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
import { ANSWERS, stubGuided } from '../../../test/guidedWorld'
import { HA_FULL, HA_HOME } from '../../../test/probeAnswers'
import { columnNames, columnName } from './columns'
import { sameWords } from './ServiceStep'

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

describe('umbau spalten 3: the kind under a tile only when it differs from the name', () => {
  it('shows the kind under "Home" and "pve", and nothing under a tile named like its kind', async () => {
    await openNew()
    const tiles = within(screen.getByRole('region', { name: 'Where does the data come from?' }))
    const found = await tiles.findAllByRole('button', { pressed: false })
    const plex = found.find((one) => one.textContent?.startsWith('Plex'))!
    expect(plex.textContent).toBe('Plex')
    expect(plex.querySelector('small')).toBeNull()
    const home = found.find((one) => one.textContent?.startsWith('Home'))!
    expect(home.querySelector('small')?.textContent).toBe('Home Assistant')
  })

  it('compares the words, not the spelling', () => {
    expect([sameWords('Emby', 'Emby'), sameWords('Emby', ' emby '), sameWords('Home Assistant', 'Home')]).toEqual([true, true, false])
  })
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
