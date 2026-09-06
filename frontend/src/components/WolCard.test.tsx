/**
 * The two looks of the Wake-on-LAN card, and the button that has to work in both.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { WolCard } from './WolCard'
import type { WidgetData, WidgetView } from '../lib/types'

const widget = { id: 1, kind: 'wol.wake', title: 'Workstation', renderer: 'wol', icon: '' } as unknown as WidgetView

function data(meta: Record<string, unknown>, awake: boolean | null = false): WidgetData {
  return {
    status: awake ? 'ok' : 'warn',
    primary: { label: '', value: 'workstation.example.com' },
    secondary: [{ label: 'MAC', value: '00:1A:2B:3C:4D:5E' }],
    actions: [{ id: 'wake', label: 'Wake', icon: 'power' }],
    meta: { awake, ...meta },
  } as unknown as WidgetData
}

describe('WolCard', () => {
  it('shows the state, the address and the MAC in the detailed view', () => {
    render(<WolCard widget={widget} data={data({ view: 'detail' })} canAct onAction={vi.fn()} />)
    expect(screen.getByText(/Asleep|Schläft/)).toBeTruthy()
    expect(screen.getByText('workstation.example.com')).toBeTruthy()
    expect(screen.getByText('00:1A:2B:3C:4D:5E')).toBeTruthy()
  })

  it('is one big button in the icon view, and says which machine', () => {
    render(<WolCard widget={widget} data={data({ view: 'icon' })} canAct onAction={vi.fn()} />)
    // The tile has no visible name, so the button has to carry it for anyone
    // who cannot see the card.
    expect(screen.getByRole('button', { name: /Workstation/ })).toBeTruthy()
    expect(screen.queryByText('00:1A:2B:3C:4D:5E')).toBeNull()
  })

  it('wakes the machine from either view', async () => {
    for (const view of ['detail', 'icon']) {
      const onAction = vi.fn()
      const { unmount } = render(<WolCard widget={widget} data={data({ view })} canAct onAction={onAction} />)
      await userEvent.click(screen.getByRole('button'))
      expect(onAction, view).toHaveBeenCalledWith(expect.objectContaining({ id: 'wake' }))
      unmount()
    }
  })

  it('offers no button to somebody who may only look', () => {
    render(<WolCard widget={widget} data={data({ view: 'detail' })} canAct={false} onAction={vi.fn()} />)
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('says unknown in the icon view too, not asleep', () => {
    // The small tile is the one that gets glanced at, so a claim it cannot
    // back up is worse there than anywhere.
    render(<WolCard widget={widget} data={data({ view: 'icon' }, null)} canAct onAction={vi.fn()} />)
    expect(screen.getByText(/Unknown|Unbekannt/)).toBeTruthy()
    expect(screen.queryByText(/Asleep|Schläft/)).toBeNull()
  })

  it('says awake in the icon view when the machine answers', () => {
    render(<WolCard widget={widget} data={data({ view: 'icon' }, true)} canAct onAction={vi.fn()} />)
    expect(screen.getByText(/Awake|Wach/)).toBeTruthy()
  })

  it('says unknown rather than asleep when nothing is being checked', () => {
    // Without an address the card cannot know, and "asleep" would be a claim.
    render(<WolCard widget={widget} data={data({ view: 'detail' }, null)} canAct onAction={vi.fn()} />)
    expect(screen.getByText(/Unknown|Unbekannt/)).toBeTruthy()
  })

  it('draws the detailed view when nothing says otherwise', () => {
    render(<WolCard widget={widget} data={data({})} canAct onAction={vi.fn()} />)
    expect(screen.getByText('00:1A:2B:3C:4D:5E')).toBeTruthy()
  })

  it('says awake when the machine answers', () => {
    render(<WolCard widget={widget} data={data({ view: 'detail' }, true)} canAct onAction={vi.fn()} />)
    expect(screen.getByText(/Awake|Wach/)).toBeTruthy()
  })
})
