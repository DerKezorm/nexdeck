/**
 * The card style of Appearance on a home page: the surfaces bend their edge
 * in liquid glass and tip towards the pointer as the board's cards do, not
 * while the page is arranged and not when the account asked for no tilt;
 * the style sheet and ``Felt`` name the same surfaces.
 */
import { cleanup, render } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, beforeEach, vi } from 'vitest'

import { useLook } from '../../lib/appearance'
import { useAuth } from '../../stores/auth'
import { Felt, SURFACES } from './Felt'

const followed: { card: HTMLElement; tilts: () => boolean }[] = []
const bent: HTMLElement[] = []
vi.mock('../../lib/cardLook', async (original) => ({
  ...(await original<typeof import('../../lib/cardLook')>()),
  followPointer: (card: HTMLElement, tilts: () => boolean) => {
    followed.push({ card, tilts })
    return () => undefined
  },
}))
vi.mock('../../lib/refraction', () => ({
  canRefract: () => true,
  refract: (element: HTMLElement) => {
    bent.push(element)
    return () => undefined
  },
}))

beforeEach(() => {
  followed.length = 0
  bent.length = 0
  useLook.setState({ cards: 'glass', board: null, refraction: true })
  useAuth.setState({ user: { tilt: true } as never })
})
afterEach(() => cleanup())

const pill = () => <div className="sensor-pill" data-surface>Kitchen window</div>

it('lets a surface of the page follow the pointer and tip, as a card does', () => {
  render(<Felt arranging={false} look="contact:pill:surface">{pill()}</Felt>)
  expect(followed).toHaveLength(1)
  expect(followed[0].card).toHaveAttribute('data-surface')
  expect(followed[0].tilts()).toBe(true)
  // No bent edge in plain glass.
  expect(bent).toEqual([])
})

it('keeps still in the calm card style', () => {
  useLook.setState({ cards: 'calm' })
  render(<Felt arranging={false} look="contact:pill:surface">{pill()}</Felt>)
  expect(followed[0].tilts()).toBe(false)
})

it('does not tip while the page is arranged, nor when the account asked for no tilt', () => {
  const { rerender } = render(<Felt arranging look="contact:pill:surface">{pill()}</Felt>)
  expect(followed[0].tilts()).toBe(false)
  rerender(<Felt arranging={false} look="contact:pill:surface">{pill()}</Felt>)
  expect(followed[0].tilts()).toBe(true)
  cleanup()
  useAuth.setState({ user: { tilt: false } as never })
  render(<Felt arranging={false} look="contact:pill:surface">{pill()}</Felt>)
  expect(followed.at(-1)!.tilts()).toBe(false)
})

it('bends the edge of a surface in liquid glass, the board\'s style before the installation\'s, and not when refraction is off', () => {
  useLook.setState({ cards: 'flat', board: 'liquid', refraction: true })
  render(<Felt arranging={false} look="contact:pill:surface">{pill()}</Felt>)
  expect(bent).toHaveLength(1)
  cleanup()
  bent.length = 0
  useLook.setState({ cards: 'liquid', board: null, refraction: false })
  render(<Felt arranging={false} look="contact:pill:surface">{pill()}</Felt>)
  expect(bent).toHaveLength(0)
})

it('leaves a drawing alone: a door is a picture, not a card', () => {
  useLook.setState({ cards: 'liquid', board: null, refraction: true })
  render(<Felt arranging={false} look="contact:door:surface"><div className="sensor-draw">door</div></Felt>)
  expect(followed).toHaveLength(0)
  expect(bent).toHaveLength(0)
})

it('names in the style sheet the same surfaces as Felt, for every card style', () => {
  const css = readFileSync(join(process.cwd(), 'src/styles/app.css'), 'utf8')
  const wanted = SURFACES.split(',').map((one) => one.trim()).sort()
  for (const style of ['flat', 'outline', 'neon', 'liquid', 'calm']) {
    const found = css.match(new RegExp(`:root\\[data-cards='${style}'\\] \\[data-home-page\\] :is\\(([^)]*)\\)`))
    expect(found, style).not.toBeNull()
    expect(found![1].split(',').map((one) => one.trim()).sort(), style).toEqual(wanted)
  }
})
