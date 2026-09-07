/**
 * Taking hold of a card while editing.
 *
 * ⚠️ The drag machinery leaves buttons and links alone, so that a press on
 * one is a press and not a drag. Outside edit mode that is right. Inside it,
 * it left a card whose body is a link or a strip of bars with nothing to take
 * hold of but the two millimetres of padding at its edge, and the card was
 * near enough immovable with a mouse.
 *
 * Two halves, and either alone does nothing: the grid must stop excusing the
 * body from a drag, and the body must stop taking pointer events, or a press
 * on a link inside it would both drag the card and follow the link.
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'

import { render } from '@testing-library/react'
import { vi } from 'vitest'

import type { Breakpoint, LayoutItem, WidgetView } from '../lib/types'

const captured: Record<string, unknown>[] = []

vi.mock('react-grid-layout', () => ({
  Responsive: (props: Record<string, unknown>) => {
    captured.push(props)
    return <div data-testid="grid">{props.children as React.ReactNode}</div>
  },
  WidthProvider: (Component: unknown) => Component,
}))

const { BoardGrid } = await import('./BoardGrid')

function widget(id: number): WidgetView {
  return {
    id, kind: 'core.clock', title: 'Clock', icon: '', link: '', renderer: 'clock',
    options: {}, integration_id: null, refresh_seconds: null,
    default_size: [2, 2], min_size: [2, 2],
  } as unknown as WidgetView
}

function board(editing: boolean) {
  const layouts = { lg: [], md: [], sm: [] } as Record<Breakpoint, LayoutItem[]>
  captured.length = 0
  render(
    <BoardGrid
      {...({ widgets: [widget(1)], layouts, data: {}, editing, canAct: true, autoCompact: false } as unknown as Parameters<typeof BoardGrid>[0])}
    />,
  )
  const props = captured[0]
  expect(props, 'the grid was never rendered, so this test proves nothing').toBeTruthy()
  return String(props.draggableCancel ?? '')
}

describe('what a drag is allowed to start on', () => {
  it('leaves only the card buttons out while editing', () => {
    // The settings and delete buttons of the card, and nothing else. Written
    // out rather than matched loosely: this is the whole rule.
    expect(board(true)).toBe('.card-controls')
  })

  it('still leaves buttons and links alone when not editing', () => {
    const cancel = board(false)
    expect(cancel).toContain('button')
    expect(cancel).toContain('a,')
  })
})

describe('the other half of it', () => {
  it('takes the pointer events off everything in the card but its buttons', () => {
    // ⚠️ Read out of the stylesheet, not asserted about a class name. Without
    // this rule the grid would start a drag and the link under the pointer
    // would open at the same time.
    const css = readFileSync(path.resolve(__dirname, '../styles/app.css'), 'utf8')
    const rule = css.match(/\.card\.is-editing\s*>\s*\*:not\(\.card-controls\)\s*\{([^}]*)\}/)
    expect(rule, 'the rule that makes the card body inert while editing is gone').toBeTruthy()
    expect(rule![1]).toContain('pointer-events: none')
  })
})
