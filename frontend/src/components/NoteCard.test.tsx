/**
 * The Notes card is written from the card: a writer gets the pencil and
 * ticking boxes, a reader and a board being arranged get neither, the text
 * is saved when the typing pauses, and a change made elsewhere is offered
 * rather than overwritten.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { toggleTask } from '../lib/notes'
import type { WidgetView } from '../lib/types'
import { renderWidget } from './renderers'

const saves: { path: string; body: { content: string; based_on: string } }[] = []
let refuse: string | null = null

vi.mock('../api/client', () => {
  class ApiError extends Error {
    code: string
    detail: Record<string, unknown>
    constructor(code: string, message: string, detail: Record<string, unknown>) {
      super(message)
      this.code = code
      this.detail = detail
    }
  }
  return {
    ApiError,
    fileUrl: () => '',
    mediaUrl: () => '',
    put: vi.fn(async (path: string, body: { content: string; based_on: string }) => {
      saves.push({ path, body })
      if (refuse !== null) throw new ApiError('note_changed', 'changed', { current: refuse })
      return { content: body.content }
    }),
  }
})

const SOURCE = '- [ ] milk\n- [x] eggs\n\n```\n- [ ] not a box\n```\n- [ ] bread'

function note(options: { canWrite?: boolean; editing?: boolean } = {}) {
  const widget: WidgetView = { id: 7, kind: 'core.markdown', title: 'Shopping', icon: '', link: '', renderer: 'text', options: { content: SOURCE }, integration_id: null, refresh_seconds: 3600 }
  return render(<>{renderWidget({ widget, data: { status: 'ok', meta: { markdown: SOURCE } }, canWrite: options.canWrite ?? true, editing: options.editing })}</>)
}

describe('toggleTask', () => {
  it('flips the n-th box and skips fenced code', () => {
    expect(toggleTask(SOURCE, 0)).toBe(SOURCE.replace('- [ ] milk', '- [x] milk'))
    expect(toggleTask(SOURCE, 1)).toBe(SOURCE.replace('- [x] eggs', '- [ ] eggs'))
    expect(toggleTask(SOURCE, 2)).toBe(SOURCE.replace('- [ ] bread', '- [x] bread'))
    expect(toggleTask(SOURCE, 3)).toBeNull()
    expect(toggleTask('1. [ ] first', 0)).toBe('1. [x] first')
  })
})

describe('the Notes card', () => {
  beforeEach(() => {
    saves.length = 0
    refuse = null
  })

  it('ticks a box for a writer and saves from what it showed', async () => {
    const { container } = note()
    await waitFor(() => expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(3))
    const boxes = container.querySelectorAll('input[type="checkbox"]')
    expect(boxes[2]).not.toBeDisabled()
    fireEvent.click(boxes[2])
    await waitFor(() => expect(saves).toHaveLength(1))
    expect(saves[0]).toEqual({ path: '/widgets/7/note', body: { content: SOURCE.replace('- [ ] bread', '- [x] bread'), based_on: SOURCE } })
  })

  it('gives a reader neither the pencil nor boxes that tick', async () => {
    const { container } = note({ canWrite: false })
    await waitFor(() => expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(3))
    expect(container.querySelector('input[type="checkbox"]')).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Edit note' })).not.toBeInTheDocument()
  })

  it('leaves the text alone while the board is being arranged', () => {
    note({ editing: true })
    expect(screen.queryByRole('button', { name: 'Edit note' })).not.toBeInTheDocument()
  })

  it('saves when the typing pauses', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      note()
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
      await user.click(screen.getByRole('button', { name: 'Edit note' }))
      const field = screen.getByRole('textbox', { name: 'Note' })
      await user.type(field, '!')
      expect(saves).toHaveLength(0)
      await act(async () => {
        await vi.advanceTimersByTimeAsync(900)
      })
      expect(saves).toHaveLength(1)
      expect(saves[0].body).toEqual({ content: `${SOURCE}!`, based_on: SOURCE })
      expect(await screen.findByText('Saved')).toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })

  it('offers both texts when the note changed elsewhere', async () => {
    refuse = '- [ ] milk\n- [ ] coffee'
    note()
    await userEvent.click(screen.getByRole('button', { name: 'Edit note' }))
    const field = screen.getByRole('textbox', { name: 'Note' })
    await userEvent.type(field, '?')
    fireEvent.blur(field)
    expect(await screen.findByRole('alert')).toHaveTextContent('changed elsewhere')

    refuse = null
    await userEvent.click(screen.getByRole('button', { name: 'Keep mine' }))
    await waitFor(() => expect(saves.at(-1)?.body).toEqual({ content: `${SOURCE}?`, based_on: '- [ ] milk\n- [ ] coffee' }))
  })

  it('takes the other text when asked', async () => {
    refuse = '- [ ] coffee'
    note()
    await userEvent.click(screen.getByRole('button', { name: 'Edit note' }))
    const field = screen.getByRole('textbox', { name: 'Note' })
    await userEvent.type(field, '?')
    fireEvent.blur(field)
    await userEvent.click(await screen.findByRole('button', { name: 'Take the other' }))
    expect(screen.getByRole('textbox', { name: 'Note' })).toHaveValue('- [ ] coffee')
  })
})
