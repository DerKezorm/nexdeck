/**
 * Buttons of a custom card (KARTEN-8) as the sheet and the card meet them:
 * a blank that takes a number, the second question of a dangerous button, and
 * a press that cannot go out twice.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { ActionSheet, type PendingAction } from './ActionSheet'
import type { Action, Ask } from '../lib/types'
import { startingValue, unanswered } from '../lib/unanswered'

/** The sheet with its state kept the way the board keeps it. */
function Harness({ action, onRun }: { action: Action; onRun: (widgetId: number, action: Action) => void | Promise<unknown> }) {
  const [pending, setPending] = useState<PendingAction | null>({
    widgetId: 3,
    action,
    values: Object.fromEntries(unanswered(action).map((blank) => [blank.name, startingValue(blank)])),
  })
  return <ActionSheet pending={pending} onChange={setPending} onCancel={() => setPending(null)} onRun={onRun} />
}

const confirmButton = () => screen.getByRole('button', { name: /confirm|bestätigen|ok/i })

const KIB: Ask = { name: 'kib', label: 'KiB per second?', kind: 'number', min: 0, max: 100000, step: 1 }
const limit = (ask: Ask = KIB): Action => ({ id: 'button:limit', label: 'Limit speed', confirm: true, asks: [ask] })

describe('a blank that takes a number', () => {
  it('karten8 ac4 shows a number field with its range and sends the number it was given', async () => {
    const onRun = vi.fn()
    render(<Harness action={limit()} onRun={onRun} />)
    const field = screen.getByLabelText('KiB per second?') as HTMLInputElement
    expect(field.type).toBe('number')
    expect([field.min, field.max, field.step]).toEqual(['0', '100000', '1'])
    expect(confirmButton()).toBeDisabled()
    await userEvent.type(field, '512')
    await userEvent.click(confirmButton())
    const [widgetId, sent] = onRun.mock.calls[0] as [number, Action]
    expect(widgetId).toBe(3)
    // A number, not the text that was typed.
    expect(sent.params).toEqual({ kib: 512 })
  })

  it('karten8 ec9 will not send a value outside the range and says why', async () => {
    const onRun = vi.fn()
    render(<Harness action={limit()} onRun={onRun} />)
    await userEvent.type(screen.getByLabelText('KiB per second?'), '100001')
    expect(screen.getByRole('alert')).toHaveTextContent(/0.*100000/)
    expect(confirmButton()).toBeDisabled()
    await userEvent.click(confirmButton())
    expect(onRun).not.toHaveBeenCalled()
  })

  it('karten8 ec9 will not send a fraction where the step is whole', async () => {
    const onRun = vi.fn()
    render(<Harness action={limit()} onRun={onRun} />)
    await userEvent.type(screen.getByLabelText('KiB per second?'), '2.5')
    expect(screen.getByRole('alert')).toBeInTheDocument()
    await userEvent.click(confirmButton())
    expect(onRun).not.toHaveBeenCalled()
  })

  it('karten8 ec9 takes a fraction when the step is not whole, and holds the low end', async () => {
    const onRun = vi.fn()
    render(<Harness action={limit({ name: 'kib', label: 'Share', kind: 'number', min: 0.5, step: 0.5 })} onRun={onRun} />)
    const field = screen.getByLabelText('Share')
    await userEvent.type(field, '0.25')
    expect(screen.getByRole('alert')).toHaveTextContent(/0.5/)
    await userEvent.clear(field)
    await userEvent.type(field, '1.5')
    expect(screen.queryByRole('alert')).toBeNull()
    await userEvent.click(confirmButton())
    expect((onRun.mock.calls[0] as [number, Action])[1].params).toEqual({ kib: 1.5 })
  })
})
