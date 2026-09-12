/**
 * On a wall display the player keeps its floating bar, also once the token has left the address.
 *
 * ⚠️ A display has no top bar, so the bar stands in even when the browser chose
 * "in the top bar". The player recognised a display by /k/ with a token behind
 * it. Since 12.09.2026 the display takes the token out of its address and runs
 * on /k alone, and there the player would have waited for a top bar that is
 * never drawn: music playing and nothing on screen to stop it.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { usePlayer } from '../../stores/player'
import { MiniPlayer } from './MiniPlayer'

function memoryStorage(): Storage {
  const items = new Map<string, string>()
  return {
    get length() {
      return items.size
    },
    clear: () => items.clear(),
    getItem: (key) => items.get(key) ?? null,
    key: (index) => [...items.keys()][index] ?? null,
    removeItem: (key) => void items.delete(key),
    setItem: (key, value) => void items.set(key, String(value)),
  }
}

const track = { id: 't1', title: 'Landfall', artist: 'Harbour Brass', album: 'Slow Tide', album_id: 'a1', artist_id: '', duration: 200, number: 1, disc: 1, art: '', thumb: '', codec: 'flac', bit_depth: null, sample_rate: null, bitrate: null }

function showAt(address: string) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[address]}>
        <MiniPlayer />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('the player on a wall display', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', memoryStorage())
    usePlayer.getState().stop()
    usePlayer.setState({ barStyle: 'header', barCorner: 'bottom-right', barCollapsed: false, library: null })
    usePlayer.getState().play({ widgetId: 9, title: 'Plex', icon: 'plex', features: [] }, [track], 0)
  })

  it('keeps the floating bar on /k without a token', () => {
    showAt('/k')
    expect(screen.getByTestId('player-bar')).toBeInTheDocument()
  })

  it('keeps it on the link that still carries the token', () => {
    showAt('/k/nk_example-token')
    expect(screen.getByTestId('player-bar')).toBeInTheDocument()
  })

  it('leaves the top bar to a board that has one', () => {
    // The control: without it the two above would pass for a bar that never goes away.
    showAt('/b/home')
    expect(screen.queryByTestId('player-bar')).toBeNull()
  })
})
