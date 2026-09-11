/**
 * The player's pieces that decide something: which face a card size gets,
 * which corner a dropped bar lands in, what the browser is asked to fetch,
 * where what plays is shown, and how loud.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { soundUrl, type MusicTrack } from '../../api/music'
import { canSetVolume, forgetFormats, playableFormats, playsHlsNatively } from '../../lib/audioFormats'
import type { WidgetView } from '../../lib/types'
import { PlayerSettings } from '../../pages/settings/PlayerSettings'
import { usePlayer } from '../../stores/player'
import { HeaderTools } from '../HeaderTools'
import { HeaderPill } from './HeaderPill'
import { cornerAt, MiniPlayer } from './MiniPlayer'
import { faceFor, PlayerCard } from './PlayerCard'
import { formatTime, soundBadge, VolumeButton, VolumeControl } from './parts'

/** Node's own half-made localStorage hides jsdom's in this runner; a plain map stands in. */
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

const widget: WidgetView = { id: 9, kind: 'plex.player', title: 'Plex', icon: 'plex', link: '', renderer: 'player', options: {}, integration_id: 1, refresh_seconds: null }

function album(id: string) {
  return { id, title: `Album ${id}`, artist: 'Harbour Brass', artist_id: 'ar1', year: 2025, tracks: 10, art: `proxy:/art/${id}`, thumb: `proxy:/thumb/${id}`, subtitle: 'Harbour Brass', kind: 'album' }
}

function withProviders(children: React.ReactNode) {
  return (
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.stubGlobal('localStorage', memoryStorage())
  usePlayer.getState().stop()
  usePlayer.setState({ barStyle: 'floating', barCorner: 'bottom-right', barCollapsed: false, library: null })
})

describe('card faces', () => {
  it('picks the face by width and height, not by width alone', () => {
    expect(faceFor(240, 160)).toBe('tiny')
    expect(faceFor(760, 180)).toBe('tiny')
    expect(faceFor(420, 230)).toBe('strip')
    expect(faceFor(420, 460)).toBe('stack')
    expect(faceFor(740, 390)).toBe('split')
    expect(faceFor(600, 390)).toBe('stack')
  })
})

describe('the floating bar', () => {
  it('lands in the corner nearest to where it was let go', () => {
    expect(cornerAt(100, 100, 1000, 800)).toBe('top-left')
    expect(cornerAt(900, 100, 1000, 800)).toBe('top-right')
    expect(cornerAt(100, 700, 1000, 800)).toBe('bottom-left')
    expect(cornerAt(900, 700, 1000, 800)).toBe('bottom-right')
  })
})

describe('what the browser is asked for', () => {
  it('names the formats this browser takes, none it turns down, and MP3 when it names none', () => {
    const answers: Record<string, string> = { 'audio/flac': 'probably', 'audio/mpeg': 'maybe', 'audio/mp4; codecs="alac"': '' }
    const probe = { canPlayType: (type: string) => (answers[type] ?? '') as CanPlayTypeResult }
    expect(playableFormats(probe)).toEqual(['flac', 'mp3'])
    expect(playableFormats({ canPlayType: () => '' as CanPlayTypeResult })).toEqual(['mp3'])
    expect(playsHlsNatively({ canPlayType: (type: string) => (type.includes('mpegurl') ? 'maybe' : '') as CanPlayTypeResult })).toBe(true)
  })

  it('asks converted sound from a second, and HLS as a playlist', () => {
    expect(soundUrl(3, 't1', { quality: 'low', formats: ['flac', 'mp3'], start: 61.7 })).toBe('/api/v1/widgets/3/audio/t1?quality=low&formats=flac%2Cmp3&start=61')
    expect(soundUrl(3, 't1', { quality: 'original', formats: ['flac'] })).toBe('/api/v1/widgets/3/audio/t1?quality=original&formats=flac')
    expect(soundUrl(3, 't1', { quality: 'low', formats: ['mp3'], hls: true })).toBe('/api/v1/widgets/3/audio/t1/hls/master.m3u8?quality=low&formats=mp3')
  })

  it('writes the shape of the sound in a few characters, and never a zero for no length', () => {
    const base = { codec: 'flac', bit_depth: 24, sample_rate: 96000, bitrate: 2800 } as MusicTrack
    expect(soundBadge(base, 'original')).toBe('FLAC 24/96')
    expect(soundBadge({ ...base, codec: 'mp3', bit_depth: null, sample_rate: null, bitrate: 320 }, 'original')).toBe('MP3 320')
    expect(soundBadge(base, 'low')).toBe('MP3 128')
    expect(formatTime(3725)).toBe('1:02:05')
    expect(formatTime(null)).toBe('-:--')
  })
})

describe('PlayerCard', () => {
  it('shows four covers while nothing plays, each opening its album', async () => {
    render(withProviders(<PlayerCard widget={widget} canAct data={{ status: 'ok', items: ['1', '2', '3', '4', '5'].map(album), secondary: [{ label: 'Albums', value: 5 }] }} />))
    const artwork = screen.getAllByTestId('player-artwork')[0]
    expect(artwork.dataset.count).toBe('4')
    expect(screen.getAllByRole('button', { name: /^Open Album/ })).toHaveLength(4)
    expect(screen.getAllByRole('button', { name: 'Open the library' }).length).toBeGreaterThan(0)
    await userEvent.click(screen.getByRole('button', { name: 'Open Album 2' }))
    // No library fits in a card the test gives no size, so the album opens beside the board.
    expect(usePlayer.getState().library?.album).toEqual({ id: '2', title: 'Album 2' })
  })

  it('shows one cover when set to, and random picks rather than the newest when there are some', () => {
    const data = { status: 'ok' as const, items: ['1', '2'].map(album), meta: { music: { features: [], picks: [album('9')] } } }
    render(withProviders(<PlayerCard widget={{ ...widget, options: { idle_art: 'one' } }} canAct data={data} />))
    expect(screen.getAllByTestId('player-artwork')[0].dataset.count).toBe('1')
    expect(screen.getByRole('button', { name: 'Open Album 9' })).toBeInTheDocument()
  })

  it('offers nothing to press to somebody who may only look', () => {
    render(withProviders(<PlayerCard widget={widget} canAct={false} data={{ status: 'ok', items: ['1'].map(album) }} />))
    expect(screen.queryByRole('button', { name: /^Open Album/ })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Open the library' })).toBeNull()
  })
})

describe('where what plays is shown', () => {
  const track = { id: 't1', title: 'Landfall', artist: 'Harbour Brass', album: 'Slow Tide', album_id: 'a1', artist_id: '', duration: 200, number: 1, disc: 1, art: '', thumb: '', codec: 'flac', bit_depth: null, sample_rate: null, bitrate: null }

  it('puts a pill into the top bar only when the viewer chose the top bar', async () => {
    usePlayer.getState().play({ widgetId: 9, title: 'Plex', icon: 'plex', features: [] }, [track], 0)
    usePlayer.getState().setBarStyle('header')
    render(withProviders(<HeaderTools user={null} unread={0} onNotices={() => undefined} />))
    await waitFor(() => expect(screen.getByTestId('player-header-pill')).toBeInTheDocument())
    expect(screen.getByText('Landfall')).toBeInTheDocument()
    // Taken away once loaded: a check before the lazy pill arrives would pass for nothing.
    act(() => usePlayer.getState().setBarStyle('floating'))
    await waitFor(() => expect(screen.queryByTestId('player-header-pill')).toBeNull())
  })

  it('the settings page changes the bar for this browser', async () => {
    render(withProviders(<PlayerSettings />))
    await userEvent.click(screen.getByRole('button', { name: 'In the top bar' }))
    await userEvent.click(screen.getByRole('button', { name: /Top left/ }))
    expect(usePlayer.getState()).toMatchObject({ barStyle: 'header', barCorner: 'top-left' })
    expect(localStorage.getItem('nexdeck.player.bar')).toBe('header')
    expect(screen.getByText(/no room in the top bar/)).toBeInTheDocument()
  })
})

describe('the volume', () => {
  afterEach(() => forgetFormats())

  it('opens a slider over the page from its button, and Escape closes it again', async () => {
    usePlayer.setState({ volume: 0.8, muted: false })
    render(<VolumeButton />)
    const button = screen.getByTestId('player-volume-button')
    expect(screen.queryByTestId('player-volume-pop')).toBeNull()
    await userEvent.click(button)
    const pop = screen.getByTestId('player-volume-pop')
    // Drawn into the page, not into the button's face, which would cut it off.
    expect(pop.parentElement).toBe(document.body)
    fireEvent.change(screen.getByRole('slider', { name: 'Volume' }), { target: { value: '0.3' } })
    expect(usePlayer.getState().volume).toBe(0.3)
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByTestId('player-volume-pop')).toBeNull()
  })

  it('turns five per cent a notch under the wheel, and a muted player starts from nothing', () => {
    usePlayer.setState({ volume: 0.5, muted: false })
    render(<VolumeButton />)
    const button = screen.getByTestId('player-volume-button')
    fireEvent.wheel(button, { deltaY: -100 })
    expect(usePlayer.getState().volume).toBe(0.55)
    fireEvent.wheel(button, { deltaY: 100 })
    fireEvent.wheel(button, { deltaY: 100 })
    expect(usePlayer.getState().volume).toBe(0.45)
    usePlayer.setState({ muted: true })
    fireEvent.wheel(button, { deltaY: -100 })
    expect(usePlayer.getState()).toMatchObject({ volume: 0.05, muted: false })
  })

  it('shows no volume where the page may not set it, as on an iPhone', () => {
    expect(canSetVolume()).toBe(true)
    render(<><VolumeButton /><VolumeControl /></>)
    expect(screen.getAllByRole('button', { name: /Volume|Mute/ })).toHaveLength(2)
    document.body.innerHTML = ''
    // Safari there keeps the volume at 1 whatever is written to it. One
    // descriptor for both halves: two spies on one property put back the
    // wrong getter, and the next test ran on an iPhone.
    const original = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'volume')!
    Object.defineProperty(HTMLMediaElement.prototype, 'volume', { configurable: true, get: () => 1, set: () => undefined })
    try {
      forgetFormats()
      const { container } = render(<><VolumeButton /><VolumeControl /></>)
      expect(container).toBeEmptyDOMElement()
    } finally {
      Object.defineProperty(HTMLMediaElement.prototype, 'volume', original)
    }
  })

  it('the floating bar and the pill in the top bar both carry it', () => {
    usePlayer.getState().play({ widgetId: 9, title: 'Plex', icon: 'plex', features: [] }, [{ id: 't1', title: 'Landfall', artist: 'Harbour Brass', album: 'Slow Tide', album_id: 'a1', artist_id: '', duration: 200, number: 1, disc: 1, art: '', thumb: '', codec: 'flac', bit_depth: null, sample_rate: null, bitrate: null }], 0)
    render(withProviders(<><MiniPlayer /><HeaderPill /></>))
    expect(within(screen.getByTestId('player-bar')).getByTestId('player-volume-button')).toBeInTheDocument()
    expect(within(screen.getByTestId('player-header-pill')).getByTestId('player-volume-button')).toBeInTheDocument()
  })

  it('a narrow card that plays carries the volume behind a button', () => {
    usePlayer.getState().play({ widgetId: 9, title: 'Plex', icon: 'plex', features: [] }, [{ id: 't1', title: 'Landfall', artist: 'Harbour Brass', album: 'Slow Tide', album_id: 'a1', artist_id: '', duration: 200, number: 1, disc: 1, art: '', thumb: '', codec: 'flac', bit_depth: null, sample_rate: null, bitrate: null }], 0)
    usePlayer.setState({ wantsToPlay: false })
    render(withProviders(<PlayerCard widget={widget} canAct data={{ status: 'ok', items: ['1'].map(album) }} />))
    expect(screen.getByTestId('player').dataset.face).toBe('stack')
    expect(screen.getByTestId('player-volume-button')).toBeInTheDocument()
  })
})
