/**
 * Showcase mode on the cards themselves: what a person would black out by
 * hand before posting a screenshot is made up, and the rest stays.
 */
import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { DEMO_VIEWS } from '../demo/board'
import { forgetGivenNames, useShowcase } from '../lib/showcase'
import type { WidgetData, WidgetView } from '../lib/types'
import { renderWidget } from './renderers'
import { WidgetCard } from './WidgetCard'

const view = (kind: string, renderer: string, extra: Partial<WidgetView> = {}): WidgetView => ({ ...DEMO_VIEWS[0], id: 77, kind, renderer, title: 'Card', options: {}, ...extra }) as WidgetView
const data = (items: Record<string, unknown>[], extra: Partial<WidgetData> = {}): WidgetData => ({ status: 'ok', items, ...extra }) as WidgetData
const showcase = (on: boolean, media = false) => useShowcase.setState({ on, media, domains: ['mydomain.example'], names: ['Morgan'] })

beforeEach(() => forgetGivenNames())
afterEach(() => showcase(false))

describe('a list in showcase mode', () => {
  it('makes up the sender and the subject of a mail', () => {
    showcase(true)
    render(<>{renderWidget({ widget: view('imap.latest', 'list'), data: data([{ title: 'Dr. Weber', subtitle: 'Your test results' }]) })}</>)
    expect(screen.queryByText('Dr. Weber')).toBeNull()
    expect(screen.queryByText('Your test results')).toBeNull()
    expect(screen.getByText('Shop')).toBeInTheDocument()
  })

  it('makes up the people of a list of users', () => {
    showcase(true)
    render(<>{renderWidget({ widget: view('plex.users', 'list'), data: data([{ title: 'grandma', subtitle: '3 play(s)' }]) })}</>)
    expect(screen.queryByText('grandma')).toBeNull()
    expect(screen.getByText('Alex')).toBeInTheDocument()
    expect(screen.getByText('3 play(s)')).toBeInTheDocument()
  })

  it('replaces addresses and the names of the home in any row, and keeps the rest', () => {
    showcase(true)
    render(<>{renderWidget({ widget: view('docker.containers', 'list'), data: data([{ title: 'sonarr', subtitle: 'sonarr.mydomain.example on 10.20.30.4' }]) })}</>)
    expect(screen.getByText('sonarr')).toBeInTheDocument()
    expect(screen.getByText('host-a.example on 192.0.2.1')).toBeInTheDocument()
  })

  it('keeps the titles of a queue unless media titles are asked for too', () => {
    showcase(true)
    const { unmount } = render(<>{renderWidget({ widget: view('radarr.queue', 'list'), data: data([{ title: 'Dune (2021)', subtitle: '12 min left' }]) })}</>)
    expect(screen.getByText('Dune (2021)')).toBeInTheDocument()
    unmount()
    showcase(true, true)
    render(<>{renderWidget({ widget: view('radarr.queue', 'list'), data: data([{ title: 'Dune (2021)', subtitle: '12 min left' }]) })}</>)
    expect(screen.queryByText('Dune (2021)')).toBeNull()
    expect(screen.getByText('The Quiet Harbour')).toBeInTheDocument()
  })

  it('changes nothing while it is off', () => {
    showcase(false)
    render(<>{renderWidget({ widget: view('imap.latest', 'list'), data: data([{ title: 'Dr. Weber', subtitle: 'at 10.20.30.4' }]) })}</>)
    expect(screen.getByText('Dr. Weber')).toBeInTheDocument()
    expect(screen.getByText('at 10.20.30.4')).toBeInTheDocument()
  })
})

describe('what is playing in showcase mode', () => {
  it('makes up the person and the device and keeps the quality', () => {
    showcase(true)
    render(<>{renderWidget({ widget: view('plex.sessions', 'nowplaying'), data: data([{ title: 'Dune', subtitle: 'Morgan · Morgan iPhone · 4K · Direct play', user: 'Morgan', progress: 40 }]) })}</>)
    expect(screen.getByText('Dune')).toBeInTheDocument()
    expect(screen.getByText('Alex · Living room TV · 4K · Direct play')).toBeInTheDocument()
  })
})

describe('a calendar in showcase mode', () => {
  it('makes up an appointment and leaves out where it is, and keeps a release', () => {
    showcase(true)
    render(
      <>
        {renderWidget({
          widget: view('calendar.upcoming', 'calendar'),
          data: data([
            { date: '2026-10-02', title: 'Therapy', subtitle: 'Hauptstraße 3', appointment: true },
            { date: '2026-10-02', title: 'Harbour Lights', subtitle: 'S03E05' },
          ]),
        })}
      </>,
    )
    expect(screen.queryByText('Therapy')).toBeNull()
    expect(screen.queryByText('Hauptstraße 3')).toBeNull()
    expect(screen.getByText('Dentist')).toBeInTheDocument()
    expect(screen.getByText('Harbour Lights')).toBeInTheDocument()
  })
})

describe('the card frame in showcase mode', () => {
  it('blurs a camera and says so', () => {
    showcase(true)
    render(<WidgetCard widget={view('frigate.camera', 'camera')} data={data([])} />)
    expect(screen.getByTestId('showcase-veil')).toBeInTheDocument()
  })

  it('replaces an address in the title and leaves an ordinary one', () => {
    showcase(true)
    render(<WidgetCard widget={view('docker.containers', 'list', { title: 'Docker on nas.lan' })} data={data([])} />)
    expect(screen.getByRole('heading', { name: 'Docker on host-a.example' })).toBeInTheDocument()
    expect(screen.queryByTestId('showcase-veil')).toBeNull()
  })
})
