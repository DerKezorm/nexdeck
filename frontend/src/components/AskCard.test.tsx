/**
 * The one card with a field somebody types into.
 *
 * What the server does with the typed value is guarded in the backend; what
 * this card owes is that the value reaches the action at all, that it is put
 * under the name the adapter asked for, and that the field is dead whenever
 * pressing it would fail anyway.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { AskCard } from './AskCard'
import type { Action, WidgetData, WidgetView } from '../lib/types'

const widget = { id: 1, kind: 'metube.fetch', title: 'Fetch a video', renderer: 'ask', icon: '' } as unknown as WidgetView

const ASK = { name: 'url', label: 'Video address', kind: 'url' as const, placeholder: 'https://...', max_length: 2048 }

function data(extra: Partial<WidgetData> = {}): WidgetData {
  return {
    status: 'ok',
    actions: [{ id: 'add', label: 'Fetch', icon: 'download', params: { quality: 'best' }, ask: ASK }],
    items: [],
    ...extra,
  } as unknown as WidgetData
}

describe('AskCard', () => {
  it('hands the typed value over under the name the adapter asked for', async () => {
    const received: Action[] = []
    render(<AskCard widget={widget} data={data()} canAct onAction={(action) => received.push(action)} />)
    await userEvent.type(screen.getByLabelText('Video address'), 'https://videos.example.com/x')
    await userEvent.click(screen.getByRole('button', { name: /Fetch|Holen/ }))
    expect(received).toHaveLength(1)
    // ⚠️ The card's own parameters stay: the server refuses the action
    // outright if anything but the blank differs from what was offered.
    expect(received[0].params).toEqual({ quality: 'best', url: 'https://videos.example.com/x' })
  })

  it('empties the field afterwards, so the next address is not typed onto the last', async () => {
    render(<AskCard widget={widget} data={data()} canAct onAction={vi.fn()} />)
    const field = screen.getByLabelText('Video address') as HTMLInputElement
    await userEvent.type(field, 'https://videos.example.com/x')
    await userEvent.click(screen.getByRole('button', { name: /Fetch|Holen/ }))
    expect(field.value).toBe('')
  })

  it('sends nothing while the field is empty or holds only blanks', async () => {
    const onAction = vi.fn()
    render(<AskCard widget={widget} data={data()} canAct onAction={onAction} />)
    const button = screen.getByRole('button', { name: /Fetch|Holen/ })
    expect(button).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Video address'), '   ')
    expect(button).toBeDisabled()
    expect(onAction).not.toHaveBeenCalled()
  })

  it('is dead for somebody who may not act, and says so', async () => {
    const onAction = vi.fn()
    render(<AskCard widget={widget} data={data()} canAct={false} onAction={onAction} />)
    expect(screen.getByLabelText('Video address')).toBeDisabled()
    expect(screen.getByRole('button', { name: /Fetch|Holen/ })).toBeDisabled()
    expect(screen.getByText(/may not start|darfst du nichts starten/)).toBeTruthy()
  })

  it('is dead while the board is being rearranged', () => {
    render(<AskCard widget={widget} data={data()} canAct editing onAction={vi.fn()} />)
    expect(screen.getByLabelText('Video address')).toBeDisabled()
  })

  it('shows what the button has already set going', () => {
    const running = data({ items: [{ title: 'How a lock works', subtitle: '42%', status: 'warn' }] })
    render(<AskCard widget={widget} data={running} canAct onAction={vi.fn()} />)
    expect(screen.getByText('How a lock works')).toBeTruthy()
    expect(screen.getByText('42%')).toBeTruthy()
  })

  it('says so plainly when the card offers no field at all', () => {
    const empty = { status: 'ok', actions: [{ id: 'add', label: 'Fetch' }], items: [] } as unknown as WidgetData
    render(<AskCard widget={widget} data={empty} canAct onAction={vi.fn()} />)
    expect(screen.queryByRole('textbox')).toBeNull()
    expect(screen.getByText(/nothing to fill in|nichts zum Ausfüllen/)).toBeTruthy()
  })
})
