/**
 * A note served by a service (nexlore's daily note) is drawn like the card's
 * own note, but brings its way back to the service and its own buttons. The
 * card's own note has neither, and its boxes tick only for the card's own
 * note, never for one a service sent.
 */
import { fireEvent, render, screen } from '@testing-library/react'

import '../i18n/index'
import type { Action, WidgetData, WidgetView } from '../lib/types'
import { renderWidget } from './renderers'

const DAILY: WidgetView = {
  id: 1,
  kind: 'nexlore.daily',
  title: 'Daily note',
  icon: '',
  link: '',
  renderer: 'text',
  options: { space: 'Home' },
  integration_id: 1,
  refresh_seconds: 300,
}

const ADD: Action = { id: 'daily_add', label: 'Add', icon: 'plus' }

describe('a note served by a service', () => {
  it('links to the note and offers its buttons', () => {
    const onAction = vi.fn()
    const data: WidgetData = {
      status: 'ok',
      actions: [ADD],
      meta: { markdown: '# 2026-10-02\n\n- [ ] Water the beans', url: 'http://nexlore:8470/note/Home/Daily/2026-10-02.md' },
    }
    render(<>{renderWidget({ widget: DAILY, data, canAct: true, canWrite: true, onAction })}</>)
    expect(screen.getByRole('link')).toHaveAttribute('href', 'http://nexlore:8470/note/Home/Daily/2026-10-02.md')
    fireEvent.click(screen.getByRole('button', { name: /add/i }))
    expect(onAction).toHaveBeenCalledWith(expect.objectContaining({ id: 'daily_add' }))
  })

  it('leaves the card own note without a footer', () => {
    const own: WidgetView = { ...DAILY, kind: 'core.markdown', integration_id: null, options: { content: 'Hello' } }
    render(<>{renderWidget({ widget: own, data: { status: 'ok', meta: {} } })}</>)
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.queryByRole('button', { name: /add/i })).toBeNull()
  })
})
