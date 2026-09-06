/**
 * Links that come out of somebody else's service.
 *
 * A feed entry, a Hacker News story, a monitor from Uptime Kuma: the address
 * on those cards is written by a stranger. One of them saying `javascript:`
 * would run as part of nexdeck, on every board that shows the card.
 */
import { render, screen } from '@testing-library/react'

import { DEMO_VIEWS } from '../demo/board'
import { renderWidget } from './renderers'
import { WidgetCard } from './WidgetCard'

function feedView() {
  const found = DEMO_VIEWS.find((view) => view.renderer === 'feed')
  return { ...(found ?? DEMO_VIEWS[0]), renderer: 'feed' as const, link: '' }
}

describe('a link from a service', () => {
  it('is dropped from a feed row when its scheme is not one we open', () => {
    const data = {
      status: 'ok' as const,
      items: [
        { title: 'A poisoned entry', url: 'javascript:alert(document.cookie)', source: 'Feed' },
        { title: 'An ordinary entry', url: 'https://example.com/post', source: 'Feed' },
      ],
      meta: { style: 'list' },
    }
    render(<div>{renderWidget({ widget: feedView(), data, canAct: false })}</div>)
    const links = screen.getAllByRole('link')
    const targets = links.map((link) => link.getAttribute('href'))
    expect(targets).not.toContain('javascript:alert(document.cookie)')
    expect(targets).toContain('https://example.com/post')
  })

  it('does not make the card clickable when the service sends a bad one', () => {
    const view = { ...DEMO_VIEWS.find((v) => v.renderer === 'value')!, link: '' }
    render(<WidgetCard widget={view} data={{ status: 'ok', link: 'javascript:alert(1)', primary: { label: 'x', value: 1 } }} />)
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('keeps an ordinary link clickable', () => {
    const view = { ...DEMO_VIEWS.find((v) => v.renderer === 'value')!, link: '' }
    render(<WidgetCard widget={view} data={{ status: 'ok', link: 'https://example.com/service', primary: { label: 'x', value: 1 } }} />)
    expect(screen.getByRole('link').getAttribute('href')).toBe('https://example.com/service')
  })
})
