/**
 * The sheet that asks before an action runs, and fills in the blanks a card
 * left for it.
 *
 * ⚠️ What matters most is what it must not do: send a pick nobody made, or send
 * the press without the values that were picked. Either one reaches the server
 * as a refusal at best and as a title in the wrong folder at worst.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { ActionSheet, type PendingAction } from './ActionSheet'
import type { Action, Ask } from '../lib/types'
import { startingValue, unanswered } from '../lib/unanswered'

const FOLDERS: Ask = {
  name: 'root_folder_path', label: 'Target folder', kind: 'choice',
  options: [{ value: '/media/films-4k', label: '/media/films-4k' }, { value: '/media/kids-4k', label: '/media/kids-4k' }],
}
const PROFILE: Ask = { name: 'quality_profile_id', label: 'Quality profile', kind: 'choice', options: [{ value: '7', label: 'Ultra-HD' }] }

/** The sheet with its state kept the way the board keeps it. */
function Harness({ action, onRun }: { action: Action; onRun: (widgetId: number, action: Action) => void }) {
  const [pending, setPending] = useState<PendingAction | null>({
    widgetId: 3,
    action,
    values: Object.fromEntries(unanswered(action).map((blank) => [blank.name, startingValue(blank)])),
  })
  return <ActionSheet pending={pending} onChange={setPending} onCancel={() => setPending(null)} onRun={onRun} />
}

const confirmButton = () => screen.getByRole('button', { name: /confirm|bestätigen|ok/i })

describe('ActionSheet', () => {
  it('will not run while a list has nothing picked', async () => {
    const onRun = vi.fn()
    render(<Harness action={{ id: 'approve', label: 'Approve', params: { id: 13 }, asks: [FOLDERS] }} onRun={onRun} />)
    expect(confirmButton()).toBeDisabled()
    await userEvent.click(confirmButton())
    expect(onRun).not.toHaveBeenCalled()
  })

  it('does not start a list of several on its first entry', () => {
    render(<Harness action={{ id: 'approve', label: 'Approve', params: { id: 13 }, asks: [FOLDERS] }} onRun={vi.fn()} />)
    expect((screen.getByLabelText(/Target folder|Zielordner/) as HTMLSelectElement).value).toBe('')
  })

  it('starts a list of exactly one on that one', () => {
    render(<Harness action={{ id: 'approve', label: 'Approve', params: { id: 13 }, asks: [PROFILE] }} onRun={vi.fn()} />)
    expect((screen.getByLabelText(/Quality profile|Qualitätsprofil/) as HTMLSelectElement).value).toBe('7')
    expect(confirmButton()).toBeEnabled()
  })

  it('sends what was picked together with what the card offered', async () => {
    const onRun = vi.fn()
    render(<Harness action={{ id: 'approve', label: 'Approve', params: { id: 13 }, asks: [FOLDERS, PROFILE] }} onRun={onRun} />)
    await userEvent.selectOptions(screen.getByLabelText(/Target folder|Zielordner/), '/media/kids-4k')
    await userEvent.click(confirmButton())
    expect(onRun).toHaveBeenCalledTimes(1)
    const [widgetId, sent] = onRun.mock.calls[0] as [number, Action]
    expect(widgetId).toBe(3)
    // ⚠️ The id stays. Without it the server cannot match the press to the
    // row it was offered on and refuses it.
    expect(sent.params).toEqual({ id: 13, root_folder_path: '/media/kids-4k', quality_profile_id: '7' })
  })

  it('asks only for a plain confirmation when nothing is blank', async () => {
    const onRun = vi.fn()
    render(<Harness action={{ id: 'reject', label: 'Turn down', confirm: true, danger: true, params: { id: 13 } }} onRun={onRun} />)
    expect(screen.queryByRole('combobox')).toBeNull()
    await userEvent.click(confirmButton())
    expect((onRun.mock.calls[0] as [number, Action])[1].params).toEqual({ id: 13 })
  })
})
