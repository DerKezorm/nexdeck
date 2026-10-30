/**
 * The Workshop's drawing page wears a skin the way nexdeck does: the sheet and the marks on <html>, and no ground of
 * its own on <html>, which would let <body> cover the desk of the skin (its tile came out as a plain colour).
 */
import { act } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'

import type { CompiledSkin } from '../lib/skin/wear'

type Show = (spec: unknown) => Promise<void>
let show: Show

const SKIN: CompiledSkin = {
  key: 'bricks',
  css: ":root[data-skin='bricks'] [data-desk-tile] { background-image: none }",
  native: null,
  options: [],
  tokens: {},
  fonts: [],
} as unknown as CompiledSkin

beforeAll(async () => {
  // jsdom has neither; the board of the stage asks for its size, and the page waits for the fonts.
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  Object.defineProperty(document, 'fonts', { value: { ready: Promise.resolve() }, configurable: true })
  document.body.innerHTML = '<div id="root"></div>'
  await import('./main')
  show = (window as unknown as { nexdeckPreview: { show: Show } }).nexdeckPreview.show
})

describe('the drawing page', () => {
  it('wears a skin with no ground on <html>, and draws a card on nexdeck’s own ground', async () => {
    await act(async () => void show({ skin: SKIN, name: 'Bricks', theme: 'dark' }).catch(() => undefined))
    const html = document.documentElement
    expect(html.dataset.skin).toBe('bricks')
    expect(html.dataset.theme).toBe('dark')
    expect(html.style.background).toBe('')
    expect(document.getElementById('stage')?.style.background).toBe('')
    await act(async () => void show({ data: { status: 'ok', items: [] }, form: 'list', name: 'A card', theme: 'light' }).catch(() => undefined))
    expect(html.style.background).toBe('var(--nd-bg)')
  })
})
