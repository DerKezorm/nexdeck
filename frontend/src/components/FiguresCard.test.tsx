/**
 * Key figures: number cards of the page drawn as tiles, each with its value,
 * unit and colour taken from its own card.
 */
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { DEMO_VIEWS } from '../demo/board'
import { figuresLayout, isNumberCard, tileMetric, toneOf } from '../lib/figures'
import { PageCardsContext, type PageCards } from '../lib/groups'
import type { WidgetData, WidgetView } from '../lib/types'
import { useLive } from '../stores/live'
import { FiguresCard } from './FiguresCard'

const card = (id: number, kind: string, title: string, options: Record<string, unknown> = {}, renderer = 'value') =>
  ({ ...DEMO_VIEWS[0], id, kind, title, renderer, options, link: '', service_link: '', integration_name: 'NAS' }) as WidgetView
const cpu = card(1, 'synology.system', 'CPU', {}, 'stats')
const queue = card(2, 'sabnzbd.speed', 'Downloads')
const blocked = card(3, 'pihole.stats', 'Blocked', { show_findings: true })
const figures = card(9, 'core.figures', 'Wall', { cards: [1, 2, 3] }, 'figures')

function show(widget: WidgetView, page: Partial<PageCards> = {}) {
  return render(
    <PageCardsContext.Provider value={{ widgets: [cpu, queue, blocked, widget], ...page }}>
      <FiguresCard widget={widget} data={{ status: 'unknown', meta: widget.options } as WidgetData} />
    </PageCardsContext.Provider>,
  )
}

beforeEach(() => {
  useLive.setState({
    data: {
      1: { status: 'ok', primary: { label: 'CPU', value: 23, unit: '%' }, meta: { level: 'warn' } } as WidgetData,
      2: { status: 'ok', primary: { label: 'Speed', value: 38.4, unit: 'MB/s' } } as WidgetData,
      3: { status: 'bad', primary: { label: 'Blocked', value: 18.2, unit: '%' }, meta: { status_reason: 'Blocking is off' } } as WidgetData,
    },
    series: {},
  })
})
afterEach(() => useLive.setState({ data: {}, series: {} }))

describe('the layout of the tiles', () => {
  it('puts tiles in a row on a wide card and in a column on a tall one', () => {
    expect(figuresLayout(3, 900, 160, 'auto')).toEqual({ across: 3, down: 1 })
    expect(figuresLayout(3, 200, 600, 'auto')).toEqual({ across: 1, down: 3 })
    expect(figuresLayout(6, 900, 400, 'auto')).toEqual({ across: 3, down: 2 })
    // Two tiles on a card a little wider than tall: one above the other, each wide enough for its number.
    expect(figuresLayout(2, 400, 300, 'auto')).toEqual({ across: 1, down: 2 })
  })

  it('keeps to the columns chosen, never more than there are tiles', () => {
    expect(figuresLayout(6, 900, 160, '2')).toEqual({ across: 2, down: 3 })
    expect(figuresLayout(2, 900, 160, '4')).toEqual({ across: 2, down: 1 })
  })
})

describe('a tile', () => {
  it('takes its colour from its card, and from the lines drawn on its number', () => {
    // The yellow line of the CPU card colours its tile though the card itself is fine.
    expect(toneOf(cpu, useLive.getState().data[1])).toBe('warn')
    // A failed fetch is red, whatever the lines say.
    expect(toneOf(cpu, { status: 'ok', error: 'unreachable', meta: { level: 'ok' } } as WidgetData)).toBe('bad')
    expect(toneOf(cpu, { status: 'ok', error: 'unreachable', meta: { level: 'warn' } } as WidgetData)).toBe('bad')
    // A warning the service reports counts only where the card's findings are on, as on the card.
    expect(toneOf(queue, { status: 'bad' } as WidgetData)).toBe('ok')
    expect(toneOf(blocked, { status: 'bad' } as WidgetData)).toBe('bad')
  })

  it('draws the history of the metric its number is', () => {
    expect(tileMetric({ status: 'ok', primary: { label: 'x', value: 2, metric: 'memory' }, metrics: { cpu: 1, memory: 2 } } as WidgetData)).toBe('memory')
    expect(tileMetric({ status: 'ok', primary: { label: 'x', value: 2 }, metrics: { cpu: 1, memory: 2 } } as WidgetData)).toBe('cpu')
  })

  it('is made of a card that measures a number', () => {
    expect(isNumberCard({ renderer: 'stats', metrics: ['cpu'] })).toBe(true)
    expect(isNumberCard({ renderer: 'value', metrics: [] })).toBe(false)
    expect(isNumberCard({ renderer: 'list', metrics: ['down'] })).toBe(false)
    expect(isNumberCard({ renderer: 'value', client_only: true })).toBe(false)
  })
})

describe('the key figures card', () => {
  it('shows each card as a tile with its value, unit and colour', () => {
    show(figures)
    const tiles = screen.getAllByTitle(/CPU|Downloads|Blocked/)
    expect(tiles.map((tile) => tile.getAttribute('data-tone'))).toEqual(['warn', 'ok', 'bad'])
    // Rounded as the card itself rounds it: whole numbers from ten on.
    expect(screen.getByTitle('Downloads')).toHaveTextContent('38MB/s')
    // Red says why; a tile that is fine names its label or its connection.
    expect(screen.getByText('Blocking is off')).toBeInTheDocument()
    expect(screen.getByText('Speed')).toBeInTheDocument()
    expect(screen.getByTestId('figures')).toHaveAttribute('data-look', 'fill')
  })

  it('shows yellow and red the way the card is set to', () => {
    show({ ...figures, options: { cards: [1, 2, 3], tone: 'border' } })
    expect(screen.getByTestId('figures')).toHaveAttribute('data-look', 'border')
  })

  it('says how to fill it while it is empty', () => {
    show({ ...figures, options: { cards: [] } })
    expect(screen.getByText(/pick cards that show a number/)).toBeInTheDocument()
  })

  it('takes cards dropped onto it and adds a new one while the board is arranged', () => {
    const onAddInto = vi.fn()
    show(figures, { editing: true, holding: { rowHeight: 68, gap: 12, over: null, dragging: null, onAddInto } })
    expect(screen.getByTestId('figures')).toHaveAttribute('data-drop', 'group:9')
    fireEvent.click(screen.getByRole('button', { name: 'Tile' }))
    expect(onAddInto).toHaveBeenCalledWith(9)
  })

  it('leads a tile to its card link, and nowhere while arranging', () => {
    const linked = { ...queue, link: 'https://sab.example.com' } as WidgetView
    render(
      <PageCardsContext.Provider value={{ widgets: [linked, figures] }}>
        <FiguresCard widget={{ ...figures, options: { cards: [2] } }} data={undefined} />
      </PageCardsContext.Provider>,
    )
    expect(screen.getByTitle('Downloads').closest('a')).toHaveAttribute('href', 'https://sab.example.com')
  })
})
