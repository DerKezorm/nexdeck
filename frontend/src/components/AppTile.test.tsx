/** An app tile without a link of its own leads to the address of the integration it follows. */
import { render, screen } from '@testing-library/react'

import type { WidgetView } from '../lib/types'
import { AppTile } from './renderers'

const tile: WidgetView = { id: 4, kind: 'core.app', title: 'Sonarr', icon: 'sonarr', link: '', service_link: 'http://sonarr:8989', renderer: 'app', options: {}, integration_id: 3, refresh_seconds: null }

describe('AppTile', () => {
  it('links to the service of the integration when it has no link of its own', () => {
    render(<AppTile widget={tile} data={{ status: 'ok' }} />)
    expect(screen.getByRole('link')).toHaveAttribute('href', 'http://sonarr:8989')
  })

  it('prefers its own link', () => {
    render(<AppTile widget={{ ...tile, link: 'https://tv.example.com' }} data={{ status: 'ok' }} />)
    expect(screen.getByRole('link')).toHaveAttribute('href', 'https://tv.example.com')
  })
})
