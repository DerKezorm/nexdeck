/**
 * The buttons of a card and of its rows (KARTEN-8): they come from the
 * server the same way for built-in and custom cards, and one press goes out
 * once even when the finger lands twice.
 */
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { DEMO_VIEWS } from '../demo/board'
import type { Action, WidgetData, WidgetView } from '../lib/types'
import { renderWidget } from './renderers'

/** A request that is answered when the test says so. */
function slow() {
  let answer!: () => void
  const promise = new Promise<void>((resolve) => {
    answer = resolve
  })
  return { promise, answer }
}

const ACTIONS = [{ id: 'button:pause', label: 'Pause', icon: 'pause' }]
const draw = (renderer: string, data: Record<string, unknown>, onAction: (action: Action) => void | Promise<unknown>) => {
  const widget = { ...DEMO_VIEWS[0], id: 21, renderer } as WidgetView
  return render(<>{renderWidget({ widget, data: { status: 'ok', ...data } as unknown as WidgetData, canAct: true, onAction })}</>)
}

describe('a button pressed twice', () => {
  it('karten8 ec2 goes out once on the card and opens again when the answer is in', async () => {
    const request = slow()
    const onAction = vi.fn(() => request.promise)
    draw('value', { primary: { label: 'Speed', value: 4 }, actions: ACTIONS }, onAction)
    const button = screen.getByRole('button', { name: 'Pause' })
    await userEvent.dblClick(button)
    expect(onAction).toHaveBeenCalledTimes(1)
    expect(button).toBeDisabled()
    await act(async () => request.answer())
    expect(button).toBeEnabled()
    await userEvent.click(button)
    expect(onAction).toHaveBeenCalledTimes(2)
  })

  it('karten8 ec2 goes out once on a row and leaves the other rows alone', async () => {
    const request = slow()
    const onAction = vi.fn(() => request.promise)
    const rows = [
      { id: 'a', title: 'First', actions: ACTIONS },
      { id: 'b', title: 'Second', actions: ACTIONS },
    ]
    draw('list', { items: rows, meta: { actions_visible: true } }, onAction)
    const [first, second] = screen.getAllByRole('button', { name: 'Pause' })
    await userEvent.dblClick(first)
    expect(onAction).toHaveBeenCalledTimes(1)
    expect(first).toBeDisabled()
    // Another row is another press.
    await userEvent.click(second)
    expect(onAction).toHaveBeenCalledTimes(2)
    await act(async () => request.answer())
    expect(first).toBeEnabled()
  })

  it('karten8 ec2 opens the button again when the request failed', async () => {
    const onAction = vi.fn(() => Promise.reject(new Error('no')))
    draw('value', { primary: { label: 'Speed', value: 4 }, actions: ACTIONS }, onAction)
    const button = screen.getByRole('button', { name: 'Pause' })
    await userEvent.click(button)
    expect(button).toBeEnabled()
  })

  it('karten8 ec2 leaves a button that only opens the question alone', async () => {
    // The sheet has its own lock; the button on the card must not stay shut behind it.
    const onAction = vi.fn(() => undefined)
    draw('value', { primary: { label: 'Speed', value: 4 }, actions: ACTIONS }, onAction)
    const button = screen.getByRole('button', { name: 'Pause' })
    await userEvent.click(button)
    await userEvent.click(button)
    expect(onAction).toHaveBeenCalledTimes(2)
  })
})
