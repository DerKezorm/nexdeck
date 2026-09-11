/**
 * The app-wide player: what plays next, what shuffling keeps, and what this
 * browser remembers.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { MusicTrack } from '../api/music'
import { RESTART_AFTER, currentTrack, shuffled, usePlayer, type PlayerSource } from './player'

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

const source: PlayerSource = { widgetId: 7, title: 'Plex', icon: 'plex', features: [] }

function track(id: string, duration = 200): MusicTrack {
  return { id, title: id.toUpperCase(), artist: 'Harbour Brass', album: 'Slow Tide', album_id: 'a1', artist_id: 'ar1', duration, number: 1, disc: 1, art: '', thumb: '', codec: 'flac', bit_depth: null, sample_rate: null, bitrate: null }
}

const five = ['t1', 't2', 't3', 't4', 't5'].map((id) => track(id))

beforeEach(() => {
  vi.stubGlobal('localStorage', memoryStorage())
  usePlayer.getState().stop()
  usePlayer.setState({ shuffle: false, repeat: 'off', quality: 'original', controller: null })
})

describe('player store', () => {
  it('plays from the chosen track and walks the queue in order', () => {
    const player = usePlayer.getState()
    player.play(source, five, 2)
    expect(currentTrack(usePlayer.getState())?.id).toBe('t3')
    expect(usePlayer.getState().wantsToPlay).toBe(true)
    const load = usePlayer.getState().load
    player.next()
    expect(currentTrack(usePlayer.getState())?.id).toBe('t4')
    expect(usePlayer.getState().load).toBe(load + 1)
  })

  it('stops on the last track at the end of the queue, unless it repeats', () => {
    const player = usePlayer.getState()
    player.play(source, five, 4)
    player.next(true)
    expect(currentTrack(usePlayer.getState())?.id).toBe('t5')
    expect(usePlayer.getState().wantsToPlay).toBe(false)

    player.play(source, five, 4)
    usePlayer.setState({ repeat: 'all' })
    player.next(true)
    expect(currentTrack(usePlayer.getState())?.id).toBe('t1')
  })

  it('repeats one track only when it ends by itself, not when skipped', () => {
    const player = usePlayer.getState()
    player.play(source, five, 1)
    usePlayer.setState({ repeat: 'one' })
    player.next(true)
    expect(currentTrack(usePlayer.getState())?.id).toBe('t2')
    player.next()
    expect(currentTrack(usePlayer.getState())?.id).toBe('t3')
  })

  it('goes back a track only near its start; later it starts the track again', () => {
    const seek = vi.fn()
    const player = usePlayer.getState()
    player.play(source, five, 2)
    usePlayer.setState({ controller: { seek }, time: RESTART_AFTER + 5 })
    player.previous()
    expect(seek).toHaveBeenCalledWith(0)
    expect(currentTrack(usePlayer.getState())?.id).toBe('t3')
    usePlayer.setState({ time: 1 })
    player.previous()
    expect(currentTrack(usePlayer.getState())?.id).toBe('t2')
  })

  it('shuffling keeps what has played and mixes only what is to come, and gives the order back', () => {
    const player = usePlayer.getState()
    player.play(source, five, 1)
    // A mix known in advance: t3, t4, t5 come out as t4, t5, t3.
    const random = vi.spyOn(Math, 'random').mockReturnValue(0)
    player.toggleShuffle()
    random.mockRestore()
    expect(usePlayer.getState().queue.map((one) => one.id)).toEqual(['t1', 't2', 't4', 't5', 't3'])
    player.next()
    const playing = currentTrack(usePlayer.getState())
    expect(playing?.id).toBe('t4')
    player.toggleShuffle()
    const back = usePlayer.getState()
    expect(back.queue.map((one) => one.id)).toEqual(five.map((one) => one.id))
    expect(currentTrack(back)).toBe(playing)
  })

  it('a shuffled start plays the picked track first', () => {
    // A mix that leaves everything where it was, so only the pick can put t4 first.
    const random = vi.spyOn(Math, 'random').mockReturnValue(0.99)
    usePlayer.setState({ shuffle: true })
    usePlayer.getState().play(source, five, 3)
    random.mockRestore()
    expect(currentTrack(usePlayer.getState())?.id).toBe('t4')
  })

  it('taking out the track that plays moves the next one up', () => {
    const player = usePlayer.getState()
    player.play(source, five, 1)
    const load = usePlayer.getState().load
    player.removeAt(1)
    expect(currentTrack(usePlayer.getState())?.id).toBe('t3')
    expect(usePlayer.getState().load).toBe(load + 1)
    player.removeAt(0)
    expect(currentTrack(usePlayer.getState())?.id).toBe('t3')
    expect(usePlayer.getState().at).toBe(0)
  })

  it('adds to the queue of the same card and starts over for another card', () => {
    const player = usePlayer.getState()
    player.play(source, five.slice(0, 2), 0)
    player.playNext(source, [track('x')])
    expect(usePlayer.getState().queue.map((one) => one.id)).toEqual(['t1', 'x', 't2'])
    player.enqueue({ ...source, widgetId: 8 }, [track('y')])
    expect(usePlayer.getState().queue.map((one) => one.id)).toEqual(['y'])
    expect(usePlayer.getState().source?.widgetId).toBe(8)
  })

  it('a quality chosen by hand is remembered, one the player lowered itself is not', () => {
    const player = usePlayer.getState()
    player.play(source, five, 0)
    usePlayer.setState({ time: 42 })
    player.setQuality('low')
    expect(localStorage.getItem('nexdeck.player.quality')).toBe('low')
    expect(usePlayer.getState().startAt).toBe(42)
    player.setQuality('high', true)
    expect(usePlayer.getState().reduced).toBe(true)
    expect(localStorage.getItem('nexdeck.player.quality')).toBe('low')
  })

  it('remembers where the bar sits, and whether it is folded', () => {
    const player = usePlayer.getState()
    player.setBarStyle('header')
    player.setBarCorner('top-left')
    player.setBarCollapsed(true)
    expect(localStorage.getItem('nexdeck.player.bar')).toBe('header')
    expect(localStorage.getItem('nexdeck.player.corner')).toBe('top-left')
    expect(localStorage.getItem('nexdeck.player.collapsed')).toBe('1')
    expect(usePlayer.getState()).toMatchObject({ barStyle: 'header', barCorner: 'top-left', barCollapsed: true })
  })

  it('shuffles every item exactly once', () => {
    let seed = 0.37
    const random = () => {
      seed = (seed * 9301 + 0.49297) % 1
      return seed
    }
    const out = shuffled([1, 2, 3, 4, 5, 6], random)
    expect([...out].sort()).toEqual([1, 2, 3, 4, 5, 6])
  })
})
