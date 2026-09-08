/**
 * The three drawings added in this block: bars, the ring, and a chart that
 * draws every line rather than the first.
 *
 * ⚠️ These assert on what is in the DOM, not on how it looks. jsdom has no
 * layout, so a bar's width is a style string here and nothing more; that a
 * bar of 40 out of 40 is drawn full and one of 3 is drawn short is the sort
 * of thing only the browser test can hold, and it does.
 */
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import type { WidgetData, WidgetView } from '../lib/types'
import { renderWidget } from './renderers'

const VIEW: WidgetView = {
  id: 1,
  kind: 'prowlarr.indexers',
  title: 'Indexers',
  icon: '',
  link: '',
  renderer: 'list',
  options: {},
  integration_id: 1,
  refresh_seconds: 60,
}

function draw(data: WidgetData, series?: Record<string, number[]>, renderer?: string) {
  return render(<>{renderWidget({ widget: { ...VIEW, renderer: renderer ?? VIEW.renderer }, data, series })}</>)
}

// ---------------------------------------------------------------------------
// Bars
// ---------------------------------------------------------------------------

describe('bars', () => {
  const BARS: WidgetData = {
    status: 'ok',
    items: [
      { title: 'NZBgeek', value: 40 },
      { title: 'DrunkenSlug', value: 12 },
      { title: 'Tabula Rasa', value: 3 },
    ],
    meta: { renderer: 'bars' },
  }

  it('draws one bar per row, measured against the largest of them', () => {
    const { container } = draw(BARS)
    const filled = [...container.querySelectorAll('.bar > i')].map((one) => (one as HTMLElement).style.width)
    // ⚠️ Against the largest row, never against the sum. These are a ranking,
    // and dividing by the sum would shrink every bar the moment a row appears.
    expect(filled).toEqual(['100%', '30%', '7.5%'])
  })

  it('keeps the names and the numbers readable, not just the bars', () => {
    draw(BARS)
    expect(screen.getByText('NZBgeek')).toBeInTheDocument()
    expect(screen.getByText('40')).toBeInTheDocument()
    expect(screen.getByText('Tabula Rasa')).toBeInTheDocument()
  })

  it('leaves a row without a number in place, with no bar', () => {
    // The server refuses this drawing for a card whose rows carry no numbers
    // at all. One gap among numbers is a gap, and the row keeps its place.
    const { container } = draw({ ...BARS, items: [{ title: 'NZBgeek', value: 40 }, { title: 'Newznab', value: '' }] })
    expect(screen.getByText('Newznab')).toBeInTheDocument()
    const filled = [...container.querySelectorAll('.bar > i')].map((one) => (one as HTMLElement).style.width)
    expect(filled).toEqual(['100%', '0px'])
  })

  it('says so when there is nothing to draw', () => {
    draw({ status: 'ok', items: [], meta: { renderer: 'bars' } })
    expect(screen.getByText('Nothing to show')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// The ring
// ---------------------------------------------------------------------------

describe('the ring', () => {
  const RING: WidgetData = {
    status: 'ok',
    primary: { label: 'Blocked today', value: 18, unit: '%' },
    meta: {
      renderer: 'ring',
      ring: [
        { label: 'Blocked', value: 180 },
        { label: 'Allowed', value: 820 },
      ],
    },
  }

  it('cuts the ring into the slices it was given', () => {
    const { container } = draw(RING, undefined, 'ring')
    const arcs = [...container.querySelectorAll('circle')]
    expect(arcs).toHaveLength(2)
    const round = 2 * Math.PI * 42
    const [first] = arcs
    // 180 of 1000 is 18 percent of the way round.
    expect(first.getAttribute('stroke-dasharray')).toBe(
      `${((180 / 1000) * round).toFixed(2)} ${(round - (180 / 1000) * round).toFixed(2)}`,
    )
    // The second slice starts where the first one ended.
    expect(arcs[1].getAttribute('stroke-dashoffset')).toBe((-(180 / 1000) * round).toFixed(2))
  })

  it('names every slice, because a colour is not a label', () => {
    // ⚠️ Six colours nobody can name are six unlabelled slices. The contrast
    // work in 0.2.0 was for nothing if the only way to read one is its hue.
    draw(RING, undefined, 'ring')
    expect(screen.getByText('Blocked')).toBeInTheDocument()
    expect(screen.getByText('Allowed')).toBeInTheDocument()
    expect(screen.getByText('180')).toBeInTheDocument()
    expect(screen.getByText('820')).toBeInTheDocument()
  })

  it("keeps the card's own headline in the middle", () => {
    // ⚠️ Not the first slice repeated: that number is already in the legend,
    // and a card that prints the same figure twice invites the reader to
    // look for the difference. Pi-hole's ring keeps saying "18% blocked",
    // which is what the card is for.
    draw(RING, undefined, 'ring')
    expect(screen.getByText('18%')).toBeInTheDocument()
    expect(screen.getByText('Blocked today')).toBeInTheDocument()
  })

  it('shows the whole in the middle when the card has no headline of its own', () => {
    draw({ status: 'ok', meta: RING.meta }, undefined, 'ring')
    // Through formatValue, so a thousand reads the way it does everywhere
    // else on the board rather than as four bare digits.
    expect(screen.getByText((1000).toLocaleString())).toBeInTheDocument()
    expect(screen.getByText('Total')).toBeInTheDocument()
  })

  it('draws nothing rather than an empty circle when the whole is nought', () => {
    draw({ status: 'ok', meta: { renderer: 'ring', ring: [{ label: 'Up', value: 0 }, { label: 'Down', value: 0 }] } },
         undefined, 'ring')
    expect(screen.getByText('Nothing to show')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// The chart, which used to draw one line of however many it had
// ---------------------------------------------------------------------------

describe('the chart', () => {
  const TWO: WidgetData = {
    status: 'ok',
    primary: { label: 'WAN in', value: 42, unit: 'MB/s', metric: 'wan_down' },
    secondary: [{ label: 'WAN out', value: 8, unit: 'MB/s', metric: 'wan_up' }],
    metrics: { wan_down: 42, wan_up: 8 },
  }
  const SERIES = {
    wan_down: [10, 20, 30, 42, 38],
    wan_up: [2, 4, 6, 8, 7],
  }

  it('draws a line for every metric, not only the first', () => {
    // ⚠️ This is the bug the card shipped with: it took
    // Object.keys(data.metrics)[0] and threw the rest away.
    const { container } = draw(TWO, SERIES, 'chart')
    expect(container.querySelectorAll('svg')).toHaveLength(2)
  })

  it('puts every line on one scale, which is the point of drawing them together', () => {
    const { container } = draw(TWO, SERIES, 'chart')
    const paths = [...container.querySelectorAll('path[stroke]')].map((one) => one.getAttribute('d') ?? '')
    // Both are drawn from the same low and high (2 and 42), so the smaller
    // series sits near the bottom of the box rather than filling it.
    const lowest = (d: string) => Math.max(...[...d.matchAll(/[ML][\d.]+ ([\d.]+)/g)].map((m) => Number(m[1])))
    expect(lowest(paths[1])).toBeGreaterThan(lowest(paths[0]))
  })

  it('names the lines by what the card calls them, not by the column name', () => {
    draw(TWO, SERIES, 'chart')
    expect(screen.getByText('WAN out')).toBeInTheDocument()
    expect(screen.queryByText('wan_up')).toBeNull()
  })

  it('has no legend when there is only one line', () => {
    draw({ status: 'ok', primary: { label: 'Load', value: 3 }, metrics: { load: 3 } },
         { load: [1, 2, 3, 4, 3] }, 'chart')
    expect(screen.queryByText('load')).toBeNull()
  })

  it('says it is still collecting when no series has enough points', () => {
    draw(TWO, { wan_down: [1] }, 'chart')
    expect(screen.getByText(/Collecting/)).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// The button's look, which is nobody's business but the card's
// ---------------------------------------------------------------------------

describe('the button card', () => {
  const VIEW_BUTTON: WidgetView = {
    ...VIEW, kind: 'core.button', title: 'Scan', renderer: 'button', client_only: true,
  }
  const SAID: WidgetData = { status: 'ok', meta: { kind: 'board', where: 'home', look: 'label' } }
  // A button to a board is a router link, so it needs a router around it.
  const drawButton = (widget: WidgetView, data: WidgetData) =>
    render(<MemoryRouter>{renderWidget({ widget, data })}</MemoryRouter>)

  it('takes its look from its own options, not from the last answer', () => {
    // ⚠️ How a button looks is nothing the service knows. Routing it through
    // a fetch meant "symbol only" waited for a preview to come back, and the
    // card kept its name until the page was reloaded.
    drawButton({ ...VIEW_BUTTON, options: { look: 'icon' } }, SAID)
    expect(screen.queryByText('Scan')).toBeNull()
    expect(screen.getByLabelText('Scan')).toBeInTheDocument()
  })

  it('falls back to the answer when the card has no say of its own', () => {
    drawButton({ ...VIEW_BUTTON, options: {} }, { ...SAID, meta: { ...SAID.meta, look: 'icon' } })
    expect(screen.queryByText('Scan')).toBeNull()
  })

  it('shows symbol and name when nobody said otherwise', () => {
    drawButton({ ...VIEW_BUTTON, options: {} }, SAID)
    expect(screen.getByText('Scan')).toBeInTheDocument()
  })
})
