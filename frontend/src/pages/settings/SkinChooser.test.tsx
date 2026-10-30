/**
 * An account chooses the default skin, a skin of its own, or no skin at all: nexdeck as it is, whatever the
 * installation wears, 1984 included.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { Appearance } from '../../lib/appearance'
import { chosenSkin, wear, type SkinChoice } from '../../lib/skin/wear'

vi.mock('../../api/client', async (original) => ({
  ...(await original<typeof import('../../api/client')>()),
  get: vi.fn(async () => ({ skins: [{ key: 'bricks', name: 'Bricks', description: '', author: '', origin: 'own', options: [], native: null, wearable: true, swatches: [] }], default: {} })),
}))

import { SkinChooser } from './SkinChooser'

function show(value: SkinChoice, onChange: (next: SkinChoice) => void) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <SkinChooser forAccount value={value} onChange={onChange} />
    </QueryClientProvider>,
  )
}

describe('no skin for one account', () => {
  it('is a choice of its own beside the default, and marked when chosen', async () => {
    const changed = vi.fn()
    show({}, changed)
    const list = await screen.findByRole('list', { name: 'Skin' })
    await within(list).findByRole('button', { name: /Bricks/ })
    expect(within(list).getByRole('button', { name: /The installation's/ })).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(within(list).getByRole('button', { name: 'nexdeck, no skin' }))
    expect(changed).toHaveBeenLastCalledWith({ plain: true })
  })

  it('shows as chosen and is not the default', async () => {
    show({ plain: true }, () => undefined)
    const list = await screen.findByRole('list', { name: 'Skin' })
    expect(within(list).getByRole('button', { name: /nexdeck, no skin/ })).toHaveAttribute('aria-pressed', 'true')
    expect(within(list).getByRole('button', { name: /The installation's/ })).toHaveAttribute('aria-pressed', 'false')
  })

  it('wears nothing of the installation’s skin, not even 1984', () => {
    expect(chosenSkin({ plain: true }, { key: 'bricks' })).toEqual({})
    const look = { preset: 'cyan', accent: '', css: '', colour: '', card_style: 'window' } as Appearance
    expect(wear(look, chosenSkin({ plain: true }, { key: '1984' }), null).card_style).toBe('glass')
    expect(chosenSkin({}, { key: 'bricks' }).key).toBe('bricks')
  })
})
