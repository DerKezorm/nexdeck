/**
 * The calm card style keeps every card still: no tipping towards the
 * pointer, whatever the account says, and it is back in the other styles.
 */
import { render, screen } from '@testing-library/react'
import { beforeEach, vi } from 'vitest'

import { DEMO_DATA, DEMO_VIEWS } from '../demo/board'
import { applyAppearance, useLook } from '../lib/appearance'
import { useAuth } from '../stores/auth'
import { WidgetCard } from './WidgetCard'

const followed: (() => boolean)[] = []
vi.mock('../lib/cardLook', async (original) => ({
  ...(await original<typeof import('../lib/cardLook')>()),
  followPointer: (_card: HTMLElement, tilts: () => boolean) => {
    followed.push(tilts)
    return () => undefined
  },
}))

beforeEach(() => {
  followed.length = 0
  useLook.setState({ cards: 'glass', board: null })
  useAuth.setState({ user: { tilt: true } as never })
})

const view = DEMO_VIEWS.find((one) => one.renderer === 'value')!

it('does not tip in the calm style, and does in glass', () => {
  const { unmount } = render(<WidgetCard widget={view} data={DEMO_DATA[view.id]} />)
  expect(followed.at(-1)!()).toBe(true)
  unmount()
  useLook.setState({ cards: 'calm' })
  render(<WidgetCard widget={view} data={DEMO_DATA[view.id]} />)
  expect(followed.at(-1)!()).toBe(false)
})

it('draws its title small and soft in the calm style', () => {
  const { unmount } = render(<WidgetCard widget={view} data={DEMO_DATA[view.id]} />)
  expect(screen.getByRole('heading', { name: view.title })).not.toHaveClass('uppercase')
  unmount()
  useLook.setState({ cards: 'calm' })
  render(<WidgetCard widget={view} data={DEMO_DATA[view.id]} />)
  expect(screen.getByRole('heading', { name: view.title })).toHaveClass('uppercase', 'text-faint')
})

it('marks the page for the calm style, so the sheet can draw it', () => {
  applyAppearance({ preset: 'cyan', accent: '', css: '', colour: '#22d3ee', card_style: 'calm' })
  expect(document.documentElement.dataset.cards).toBe('calm')
  applyAppearance({ preset: 'cyan', accent: '', css: '', colour: '#22d3ee' })
  expect(document.documentElement.dataset.cards).toBeUndefined()
})
