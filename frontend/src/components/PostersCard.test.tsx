/**
 * Posters: a cover grid whose images come through the server, never with a
 * token in the address, and a calm line when nothing is new.
 */
import { render, screen } from '@testing-library/react'

import { mediaUrl } from '../api/client'
import type { WidgetView } from '../lib/types'
import { PostersCard } from './renderers'

const widget: WidgetView = { id: 77, kind: 'plex.recent', title: 'Recently added', icon: 'plex', link: '', renderer: 'posters', options: {}, integration_id: 1, refresh_seconds: null }

describe('PostersCard', () => {
  it('draws one poster per item with the image fetched through the server', () => {
    render(
      <PostersCard
        widget={widget}
        data={{
          status: 'ok',
          items: [
            { title: 'Harbour Lights', subtitle: 'Season 3', art: 'proxy:/library/metadata/20/thumb/1', kind: 'season' },
            { title: 'Orbital', subtitle: '2025', art: '', kind: 'movie' },
          ],
        }}
      />,
    )
    const tiles = screen.getByTestId('posters').querySelectorAll('li')
    expect(tiles).toHaveLength(2)
    const image = screen.getByTestId('posters').querySelector('img')!
    expect(image.getAttribute('src')).toBe('/api/v1/widgets/77/image?path=%2Flibrary%2Fmetadata%2F20%2Fthumb%2F1')
    expect(screen.getByText('Harbour Lights')).toBeInTheDocument()
    expect(screen.getByText('Season 3')).toBeInTheDocument()
    expect(screen.getByText('OR')).toBeInTheDocument()
  })

  it('says when nothing is new', () => {
    render(<PostersCard widget={widget} data={{ status: 'ok', items: [], meta: { empty: 'Nothing new' } }} />)
    expect(screen.getByText('Nothing new')).toBeInTheDocument()
  })
})

describe('mediaUrl', () => {
  it('routes proxy paths through the server and leaves other addresses alone', () => {
    expect(mediaUrl(5, 'proxy:/library/metadata/1/thumb/2')).toBe('/api/v1/widgets/5/image?path=%2Flibrary%2Fmetadata%2F1%2Fthumb%2F2')
    expect(mediaUrl(5, 'https://images.example.com/poster.jpg')).toBe('https://images.example.com/poster.jpg')
    expect(mediaUrl(5, '')).toBe('')
    expect(mediaUrl(5, null)).toBe('')
  })
})
