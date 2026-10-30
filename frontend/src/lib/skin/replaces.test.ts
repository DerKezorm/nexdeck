/**
 * What the page of the look says a skin replaces is what `wear` replaces: for every set of tokens a skin may bring,
 * the settings it names are exactly the settings `wear` changes.
 */
import { describe, expect, it } from 'vitest'

import type { Appearance } from '../appearance'
import { replaces, wear, type CompiledSkin, type Replaced } from './wear'

const LOOK: Appearance = { preset: 'cyan', accent: '#111111', css: '', colour: '#22d3ee', theme: null, card_style: 'glass', radius: 16, gap: 12, font: 'inter' }
const TOKENS = {
  dark: { bg: '#000000' },
  accent: '#222222',
  card_style: 'flat',
  radius: 4,
  gap: 20,
  font: 'pixel',
} as const

function skin(tokens: Partial<CompiledSkin['tokens']>): CompiledSkin {
  return { key: 'k', css: '', native: null, options: [], tokens, fonts: [], sounds: {} } as unknown as CompiledSkin
}

function changed(look: Appearance): Replaced[] {
  const fields: Replaced[] = ['theme', 'accent', 'card_style', 'radius', 'gap', 'font']
  return fields.filter((field) => JSON.stringify(look[field]) !== JSON.stringify(LOOK[field]))
}

describe('what a skin replaces', () => {
  const names = Object.keys(TOKENS) as (keyof typeof TOKENS)[]
  // Every one of the 64 sets of tokens.
  const sets = Array.from({ length: 2 ** names.length }, (_, mask) => names.filter((_, index) => mask & (2 ** index)))

  it.each(sets.map((set) => [set.join(', ') || 'none', set] as const))('is what wear changes, with tokens: %s', (_label, set) => {
    const tokens = Object.fromEntries(set.map((name) => [name, TOKENS[name]]))
    const compiled = skin(tokens)
    expect(replaces(compiled).sort()).toEqual(changed(wear(LOOK, { key: 'k' }, compiled)).sort())
  })

  it('is nothing without a skin', () => {
    expect(replaces(null)).toEqual([])
  })
})
