/**
 * The card frame: a link makes the whole card clickable (its own buttons
 * excepted), editing switches that off, and the status dot says in words
 * what its colour means.
 */
import { fireEvent, render, screen } from '@testing-library/react'

import { DEMO_DATA, DEMO_VIEWS } from '../demo/board'
import { WidgetCard } from './WidgetCard'

function valueView() {
  return { ...DEMO_VIEWS.find((v) => v.renderer === 'value')!, link: 'https://example.com/service' }
}

describe('WidgetCard', () => {
  let opened: string[] = []
  const original = window.open
  beforeEach(() => {
    opened = []
    window.open = ((url: string | URL | undefined) => {
      opened.push(String(url))
      return null
    }) as typeof window.open
  })
  afterEach(() => {
    window.open = original
  })

  it('opens the link from the card body, but not from its buttons', () => {
    const view = valueView()
    render(<WidgetCard widget={view} data={DEMO_DATA[view.id]} onRefresh={() => undefined} />)
    fireEvent.click(screen.getByRole('heading', { name: view.title }))
    expect(opened).toEqual(['https://example.com/service'])
    fireEvent.click(screen.getByRole('button', { name: 'Refresh now' }))
    expect(opened).toHaveLength(1)
    expect(screen.getByRole('link', { name: 'Open the service' })).toHaveAttribute('href', 'https://example.com/service')
  })

  it('does not open the link while editing', () => {
    const view = valueView()
    render(<WidgetCard widget={view} data={DEMO_DATA[view.id]} editing onSettings={() => undefined} />)
    fireEvent.click(screen.getByRole('heading', { name: view.title }))
    expect(opened).toEqual([])
    expect(screen.getByRole('button', { name: 'Widget settings' })).toBeInTheDocument()
  })

  it('explains the status dot in words, with the reason the service gives', () => {
    const view = { ...DEMO_VIEWS.find((v) => v.renderer === 'value')!, link: '', options: { show_findings: true } }
    render(<WidgetCard widget={view} data={{ status: 'bad', primary: { label: 'Waiting', value: 0 }, meta: { status_reason: '1 error finding(s), 0 warning(s)', urgent: ['A service is unreachable'] } }} />)
    const dot = screen.getByRole('img', { name: /^Error/ })
    expect(dot).toHaveAttribute('title', 'Error · 1 error finding(s), 0 warning(s) · A service is unreachable')
  })

  it('lays a red veil with the reason over a failed card, keeping the body underneath', () => {
    const view = { ...DEMO_VIEWS.find((v) => v.renderer === 'value')!, link: '' }
    render(<WidgetCard widget={view} data={{ status: 'unknown', error: 'The service could not be reached: ConnectError.', primary: { label: 'Waiting', value: 3 }, meta: { code: 'unreachable', hint: 'Check the URL.', stale_since: 1 } }} />)
    const veil = screen.getByTestId('card-error')
    expect(veil).toHaveTextContent('The service could not be reached: ConnectError.')
    expect(veil).toHaveTextContent('Showing the last good values')
    expect(veil).toHaveAttribute('title', 'Check the URL.')
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /^Error/ })).toBeInTheDocument()
    expect(screen.queryByRole('contentinfo')).toBeNull()
  })

  it('writes the reason for a warning into the header', () => {
    const view = { ...DEMO_VIEWS.find((v) => v.renderer === 'value')!, link: '', options: { show_findings: true } }
    render(<WidgetCard widget={view} data={{ status: 'warn', primary: { label: 'Clients', value: 76 }, meta: { status_reason: '3 device(s) offline' } }} />)
    const header = screen.getByRole('heading', { name: view.title }).parentElement!
    expect(header).toHaveTextContent('3 device(s) offline')
    expect(screen.getByRole('img', { name: 'Warning · 3 device(s) offline' })).toBeInTheDocument()
  })

  it('is calm until findings are switched on, which is how a new card starts', () => {
    /** ⚠️ Switched on, not switched off. A board where every card may shout
        is a board where the colour stops meaning anything. */
    const view = { ...DEMO_VIEWS.find((v) => v.renderer === 'value')!, link: '', options: {} }
    render(<WidgetCard widget={view} data={{ status: 'warn', primary: { label: 'Clients', value: 76 }, meta: { status_reason: '3 device(s) offline' } }} />)
    expect(screen.queryByText('3 device(s) offline')).toBeNull()
    expect(screen.getByRole('img', { name: 'Everything is fine' })).toBeInTheDocument()
    // A failed fetch still shows: that is the card's own problem, not a finding of the service.
    render(<WidgetCard widget={{ ...view, id: view.id + 1000 }} data={{ status: 'unknown', error: 'The service could not be reached.', meta: { code: 'unreachable' } }} />)
    expect(screen.getByTestId('card-error')).toBeInTheDocument()
  })
})
