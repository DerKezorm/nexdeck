import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { DEMO_VIEWS } from '../demo/board'
import { cardsOf, PageCardsContext, tucked, useFolded } from '../lib/groups'
import type { WidgetData, WidgetView } from '../lib/types'
import { useLive } from '../stores/live'
import { GroupCard, TabsCard } from './GroupCards'

const card = (id: number, kind: string, title: string, options: Record<string, unknown> = {}, renderer = 'value') =>
  ({ ...DEMO_VIEWS[0], id, kind, title, renderer, options }) as WidgetView
const clock = card(1, 'demo.value', 'Speed')
const notes = card(2, 'demo.value', 'Disk')
const tabs = card(3, 'core.tabs', 'Both', { cards: [1, 2, 99] }, 'tabs')
const group = card(4, 'core.group', 'Media', { cards: [2, 3, 1] }, 'group')

beforeEach(() => {
  useLive.setState({ data: { 1: { status: 'ok', primary: { label: 'Speed', value: 901 } } as WidgetData, 2: { status: 'ok', error: 'unreachable' } as WidgetData }, series: {} })
  useFolded.setState({ folded: [] })
})
afterEach(() => useLive.setState({ data: {}, series: {} }))

describe('which cards live inside a holder', () => {
  it('takes them off the grid, but never a card of another page or the holder itself', () => {
    expect([...tucked([clock, notes, tabs])].sort()).toEqual([1, 2])
    // A holder inside a holder is left out.
    expect(cardsOf(group, [clock, notes, tabs, group]).map((one) => one.id)).toEqual([2, 1])
  })
})

describe('the tabs card', () => {
  it('shows one card at a time, and each tab says how its card stands', () => {
    render(
      <PageCardsContext.Provider value={{ widgets: [clock, notes, tabs] }}>
        <TabsCard widget={tabs} data={undefined} />
      </PageCardsContext.Provider>,
    )
    const [speed, disk] = screen.getAllByRole('tab')
    expect(speed).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('901')).toBeInTheDocument()
    expect(disk.querySelector('.dot')).toHaveAttribute('data-status', 'bad')
    fireEvent.click(disk)
    expect(screen.getByText('unreachable')).toBeInTheDocument()
  })
})

describe('the group', () => {
  it('folds away in this browser and says how many it holds and how many are down', () => {
    render(
      <PageCardsContext.Provider value={{ widgets: [clock, notes, group] }}>
        <GroupCard widget={group} data={undefined} />
      </PageCardsContext.Provider>,
    )
    expect(screen.getByRole('region', { name: 'Speed' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Disk' })).toBeInTheDocument()
    const header = screen.getByRole('button', { expanded: true })
    expect(header.textContent).toMatch(/2/)
    fireEvent.click(header)
    expect(useFolded.getState().folded).toEqual([4])
    expect(screen.getByRole('button', { expanded: false })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Speed' })).toBeNull()
  })
})
