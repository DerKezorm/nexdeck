import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { DEMO_VIEWS } from '../demo/board'
import { useShowcase } from '../lib/showcase'
import type { WidgetData, WidgetView } from '../lib/types'
import { renderWidget } from './renderers'

const view = (kind: string, renderer: string) => ({ ...DEMO_VIEWS[0], id: 51, kind, renderer, options: {} }) as WidgetView
const playing = { status: 'ok', items: [{ title: 'Dune', subtitle: 'Alex · TV · 4K', user: 'Alex', backdrop: 'proxy:/library/metadata/7/art/1' }] } as unknown as WidgetData

afterEach(() => useShowcase.setState({ on: false, media: false }))

describe('the picture behind what plays', () => {
  it('lies behind the card, through the image route of the widget', () => {
    render(<>{renderWidget({ widget: view('plex.nowplaying', 'nowplaying'), data: playing })}</>)
    const picture = screen.getByTestId('backdrop').querySelector('img')
    expect(picture?.getAttribute('src')).toContain('/widgets/51/image?path=%2Flibrary%2Fmetadata%2F7%2Fart%2F1')
  })

  it('goes when titles are hidden, since the picture names the film', () => {
    useShowcase.setState({ on: true, media: true })
    render(<>{renderWidget({ widget: view('plex.nowplaying', 'nowplaying'), data: playing })}</>)
    expect(screen.queryByTestId('backdrop')).toBeNull()
  })
})

describe('covers as a band', () => {
  it('runs the row twice so it never jumps, and the copy is hidden from a screen reader', () => {
    const data = { status: 'ok', items: [{ title: 'Orbital' }, { title: 'Nightshift' }, { title: 'Low Tide' }], meta: { band: true } } as unknown as WidgetData
    render(<>{renderWidget({ widget: view('plex.recent', 'posters'), data })}</>)
    const covers = screen.getByTestId('poster-band').querySelectorAll('li')
    expect(covers).toHaveLength(6)
    expect([...covers].filter((cover) => cover.getAttribute('aria-hidden') === 'true')).toHaveLength(3)
    expect(screen.queryByTestId('posters')).toBeNull()
  })
})
