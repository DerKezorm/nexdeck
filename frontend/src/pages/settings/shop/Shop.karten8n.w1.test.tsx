/** W1 (Etappe 8): bigger tiles in the Card shop. */
import { screen } from '@testing-library/react'
import i18next from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { entry, renderWith, reset, STATE_ON, stub } from '../../../test/shopWorld'
import { ShopTab } from './ShopTab'

beforeEach(() => {
  localStorage.clear()
  reset([entry()], STATE_ON)
  stub()
})
afterEach(async () => {
  vi.unstubAllGlobals()
  await i18next.changeLanguage('en')
})

describe('W1: bigger tiles', () => {
  it('karten8n_w1: one column by default, two and three by the width of the list (not of the window), never four', async () => {
    renderWith(<ShopTab />)
    const list = await screen.findByRole('list', { name: 'Entries of the Card shop' })
    const classes = list.className.split(/\s+/)
    expect(classes).toEqual(expect.arrayContaining(['grid-cols-1', '@[620px]:grid-cols-2', '@[920px]:grid-cols-3']))
    expect(classes.filter((one) => /grid-cols-4$/.test(one))).toEqual([])
    expect(list.parentElement!.className).toContain('@container')
  })
})
