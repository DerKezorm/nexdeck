/**
 * A card switched off for the phone: gone from the stack, there on every
 * other screen, there while the phone arranges the board, and back while it
 * is red unless that is switched off too.
 */
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { vi } from 'vitest'

import { hiddenOnPhone } from '../lib/phone'
import type { WidgetData, WidgetView } from '../lib/types'

const captured: Record<string, unknown>[] = []

vi.mock('react-grid-layout', () => ({
  Responsive: (props: Record<string, unknown>) => {
    captured.push(props)
    return <div data-testid="grid">{props.children as React.ReactNode}</div>
  },
  WidthProvider: (Component: unknown) => Component,
}))

const { BoardGrid } = await import('./BoardGrid')
const { WidgetSettingsSheet } = await import('./WidgetSettingsSheet')

function card(id: number, options: Record<string, unknown> = {}): WidgetView {
  return {
    id, kind: 'core.clock', title: `Card ${id}`, icon: '', link: '', renderer: 'value',
    options, integration_id: null, refresh_seconds: null, default_size: [4, 2], min_size: [2, 1],
  } as unknown as WidgetView
}

const red: WidgetData = { status: 'bad', updated_at: 1 } as WidgetData
const fine: WidgetData = { status: 'ok', updated_at: 1 } as WidgetData

describe('which card the phone leaves out', () => {
  it('is one switched off for it, while it is not red', () => {
    expect(hiddenOnPhone(card(1), fine)).toBe(false)
    expect(hiddenOnPhone(card(1, { phone_hide: true }), fine)).toBe(true)
    expect(hiddenOnPhone(card(1, { phone_hide: true }), undefined)).toBe(true)
    // Red brings it back, as the switch below says from the start.
    expect(hiddenOnPhone(card(1, { phone_hide: true }), { error: 'Unreachable' } as WidgetData)).toBe(false)
    expect(hiddenOnPhone(card(1, { phone_hide: true, show_findings: true }), red)).toBe(false)
    expect(hiddenOnPhone(card(1, { phone_hide: true, phone_show_red: false }), { error: 'Unreachable' } as WidgetData)).toBe(true)
  })

  it('stays away while its frame is quiet, findings off', () => {
    // The service says bad, the card does not show it: nothing red on the phone either.
    expect(hiddenOnPhone(card(1, { phone_hide: true }), red)).toBe(true)
  })
})

function grid(extra: Record<string, unknown> = {}) {
  captured.length = 0
  const cards = [card(1), card(2, { phone_hide: true }), card(3, { phone_hide: true })]
  const view = render(
    <BoardGrid
      {...({
        widgets: cards, layouts: { lg: [{ i: '1', x: 0, y: 0, w: 4, h: 2 }, { i: '2', x: 4, y: 0, w: 4, h: 2 }, { i: '3', x: 8, y: 0, w: 4, h: 2 }], md: [], sm: [] },
        data: { 3: { error: 'Unreachable', updated_at: 1 } }, editing: false, canAct: true, autoCompact: false, columns: 12, ...extra,
      } as unknown as Parameters<typeof BoardGrid>[0])}
    />,
  )
  const narrow = () => act(() => (captured[captured.length - 1].onBreakpointChange as (next: string) => void)('sm'))
  const shown = () => [...view.container.querySelectorAll('[data-widget]')].map((one) => Number(one.getAttribute('data-widget')))
  return { view, narrow, shown }
}

describe('the board on a phone', () => {
  it('leaves the card out of the stack and keeps the red one', () => {
    const { narrow, shown } = grid({ phoneHides: true })
    expect(shown(), 'wide, every card is there').toEqual([1, 2, 3])
    narrow()
    expect(shown()).toEqual([1, 3])
  })

  it('shows every card while the board is arranged, the left out ones faded', () => {
    const { narrow, shown, view } = grid({ phoneHides: true, editing: true, onLayoutChange: vi.fn() })
    narrow()
    expect(shown()).toEqual([1, 2, 3])
    const wrapper = (id: number) => view.container.querySelector(`[data-widget="${id}"]`)!.parentElement!.parentElement as HTMLElement
    expect(wrapper(2).className).toContain('nd-phone-hidden')
    expect(wrapper(1).className).not.toContain('nd-phone-hidden')
  })

  it('leaves nothing out on a wall display', () => {
    const { narrow, shown } = grid()
    narrow()
    expect(shown()).toEqual([1, 2, 3])
  })
})

describe('the switches in the settings', () => {
  it('turn the card off for the phone and bring the red one back, on from the start', async () => {
    const sent: Record<string, unknown>[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (init?.method === 'PATCH') sent.push(JSON.parse(String(init.body)))
      const body = url.includes('/adapters')
        ? [{ kind: 'core', label: 'Core', needs_integration: false, fields: [], widgets: [{ kind: 'core.clock', label: 'Clock', options: [], client_only: true }] }]
        : url.includes('/integrations') ? [] : {}
      return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } })
    }))
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <WidgetSettingsSheet widget={card(4) as never} pages={[{ id: 1, name: 'one' }]} onClose={vi.fn()} onSaved={vi.fn()} onDeleted={vi.fn()} />
      </QueryClientProvider>,
    )
    expect(screen.queryByRole('switch', { name: 'Show it anyway when it is red' })).toBeNull()
    await userEvent.click(screen.getByRole('switch', { name: 'Hide on the phone' }))
    expect(screen.getByRole('switch', { name: 'Show it anyway when it is red' }).getAttribute('aria-checked')).toBe('true')
    await userEvent.click(screen.getByRole('switch', { name: 'Show it anyway when it is red' }))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(sent.length).toBe(1))
    expect(sent[0].options).toMatchObject({ phone_hide: true, phone_show_red: false })
    vi.unstubAllGlobals()
  })
})
