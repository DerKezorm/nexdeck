/**
 * Few columns, each with a name of its own (umbau spalten): the tiles say the kind of a service only when it adds
 * something, a name for people stands only for the field it was meant for, and the table and the choices show the
 * important fields first.
 */
import { screen, within } from '@testing-library/react'
import i18next from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { openNew, prepare } from '../../../test/cardEditor'
import { stubGuided } from '../../../test/guidedWorld'
import { sameWords } from './ServiceStep'

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
