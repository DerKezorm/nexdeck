/**
 * What a card the administrator described shows of its buttons (KARTEN-8 AC-1, AC-2, AC-5): the ones the server
 * delivers, on the card and on each row, in the viewer's language, and none for somebody who may not act.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { DEMO_VIEWS } from '../demo/board'
import { localizeCustom } from '../lib/customCard'
import type { Action, WidgetData, WidgetView } from '../lib/types'
import { renderWidget } from './renderers'

const POWER: Action = { id: 'button:power', label: { en: 'Power', de: 'Strom' } as unknown as string, icon: 'power' }
const rowButton = (hash: string): Action => ({ id: 'button:pause', label: 'Pause torrent', params: { hash } })

function draw(renderer: string, data: Record<string, unknown>, extra: { canAct?: boolean; onAction?: (action: Action) => void } = {}) {
  const widget = { ...DEMO_VIEWS[0], id: 31, renderer, kind: 'custom.list' } as WidgetView
  const whole = { status: 'ok', meta: { custom: true }, ...data } as unknown as WidgetData
  return render(<>{renderWidget({ widget, data: whole, canAct: extra.canAct ?? true, onAction: extra.onAction ?? (() => undefined) })}</>)
}

const ROWS = [
  { id: 'a', title: 'Alpha', actions: [rowButton('hash-a')] },
  { id: 'b', title: 'Beta', actions: [rowButton('hash-b')] },
]

describe('the buttons of a custom card', () => {
  it('karten8 ac1 shows a button of the card with its own words', () => {
    draw('list', { items: ROWS, actions: [POWER] })
    expect(screen.getByRole('button', { name: 'Power' })).toHaveTextContent('Power')
  })

  it('karten8 ac1 writes the words of a button in the language of whoever looks', () => {
    const made = localizeCustom({ status: 'ok', meta: { custom: true }, actions: [POWER] } as unknown as WidgetData, 'de')
    expect(made?.actions?.[0]).toMatchObject({ label: 'Strom', verbatim: true })
    // Another language falls back to English, and applying it twice changes nothing.
    expect(localizeCustom(made, 'fr')?.actions?.[0].label).toBe('Strom')
    expect(localizeCustom({ status: 'ok', meta: { custom: true }, actions: [POWER] } as unknown as WidgetData, 'fr')?.actions?.[0].label).toBe('Power')
  })

  it('karten8 ac1 keeps the words of the blanks and their choices in the language of whoever looks', () => {
    const ask = { name: 'mode', label: { en: 'Mode', de: 'Modus' }, kind: 'choice', options: [{ value: 'a', label: { en: 'Slow', de: 'Langsam' } }] }
    const made = localizeCustom({ status: 'ok', meta: { custom: true }, actions: [{ id: 'x', label: 'X', asks: [ask] }] } as unknown as WidgetData, 'de')
    expect(made?.actions?.[0].asks?.[0]).toMatchObject({ label: 'Modus', options: [{ value: 'a', label: 'Langsam' }] })
  })

  it('karten8 ac2 gives every row its own button with the values of that row', async () => {
    const onAction = vi.fn()
    draw('list', { items: ROWS }, { onAction })
    const buttons = screen.getAllByRole('button', { name: 'Pause torrent' })
    expect(buttons).toHaveLength(2)
    await userEvent.click(buttons[1])
    expect((onAction.mock.calls[0] as [Action])[0].params).toEqual({ hash: 'hash-b' })
    // The button sits in its own row, and is not hidden behind a hover on a touchscreen.
    expect(within(screen.getByText('Beta').closest('li')!).getByRole('button', { name: 'Pause torrent' })).toBeInTheDocument()
    expect(buttons[0].closest('span')?.className).not.toContain('opacity-0')
  })

  it('karten8 ac2 puts the button of a picture on the picture', async () => {
    const onAction = vi.fn()
    draw('posters', { items: [{ id: 'a', title: 'Alpha', actions: [rowButton('hash-a')] }, { id: 'b', title: 'Beta' }], actions: [POWER] }, { onAction })
    expect(screen.getAllByRole('button', { name: 'Pause torrent' })).toHaveLength(1)
    await userEvent.click(screen.getByRole('button', { name: 'Pause torrent' }))
    expect((onAction.mock.calls[0] as [Action])[0].params).toEqual({ hash: 'hash-a' })
    expect(screen.getByRole('button', { name: 'Power' })).toBeInTheDocument()
  })

  it('karten8 ac5 shows no button to somebody who may not act', () => {
    draw('list', { items: ROWS, actions: [POWER] }, { canAct: false })
    expect(screen.queryByRole('button', { name: 'Power' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Pause torrent' })).toBeNull()
    draw('posters', { items: ROWS, actions: [POWER] }, { canAct: false })
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('karten8 ac1 names a button without a symbol by its words', () => {
    draw('value', { primary: { label: 'Speed', value: 4 }, actions: [{ id: 'button:go', label: 'Go now' }] })
    expect(screen.getByRole('button', { name: 'Go now' })).toHaveTextContent('Go now')
  })
})
