/**
 * The one player of the whole app.
 *
 * ⚠️ Not the card's. A card is unmounted the moment somebody switches board or
 * page, and music that stops there is music nobody can listen to while doing
 * anything else. Decided on 11.09.2026: it keeps playing, and a bar at the
 * bottom takes over while the card is out of sight. The cards and that bar
 * only tell this store what to do; `PlayerHost` owns the element that makes
 * the sound.
 */
import { create } from 'zustand'

import type { MusicAlbum, MusicTrack, Quality } from '../api/music'

export type Repeat = 'off' | 'all' | 'one'
export type PlayState = 'idle' | 'loading' | 'playing' | 'paused' | 'error'
export type LibraryTab = 'new' | 'albums' | 'artists' | 'playlists' | 'search' | 'queue'
/**
 * Where what plays is shown while its card is out of sight.
 *
 * Both asked for on 11.09.2026, as a setting: a floating bar that folds into a
 * round button and sits in a chosen corner, or a pill in the top bar that
 * covers nothing. Kept per browser, like the quality: a phone has no top bar
 * worth the name, and a desktop has room for one.
 */
export type BarStyle = 'floating' | 'header'
export type BarCorner = 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left'
export const BAR_CORNERS: BarCorner[] = ['top-left', 'top-right', 'bottom-left', 'bottom-right']

/**
 * The library opened as a sheet beside the board.
 *
 * ⚠️ For every card too small to carry the library itself, and for the bar at
 * the bottom. Decided on 11.09.2026 after the first test: a player two rows
 * high played beautifully and offered no way to find anything else to play.
 */
export interface LibraryRequest {
  source: PlayerSource
  tab: LibraryTab
  /** The newest albums the card already has, so the sheet does not ask again. */
  newest?: MusicAlbum[]
  /** An album to open straight away, when a cover on the card was pressed. */
  album?: { id: string; title: string }
}

/** Which card the queue came from: its server plays it, its name stands in the bar. */
export interface PlayerSource {
  widgetId: number
  title: string
  icon: string
  features: string[]
}

/** What the element making the sound can be asked, registered by the host. */
export interface PlayerController {
  seek: (seconds: number) => void
}

const STORAGE = {
  volume: 'nexdeck.player.volume',
  muted: 'nexdeck.player.muted',
  quality: 'nexdeck.player.quality',
  repeat: 'nexdeck.player.repeat',
  bar: 'nexdeck.player.bar',
  corner: 'nexdeck.player.corner',
  collapsed: 'nexdeck.player.collapsed',
}
/** Pressing "back" this far into a track starts it again instead of going to the one before. */
export const RESTART_AFTER = 3

interface PlayerState {
  source: PlayerSource | null
  /** In the order it plays. */
  queue: MusicTrack[]
  /** The same tracks in the order they came, while shuffle has mixed `queue`. */
  unshuffled: MusicTrack[] | null
  at: number
  wantsToPlay: boolean
  state: PlayState
  time: number
  duration: number | null
  /** The second the current load started from. Converted sound restarts there when skipped into. */
  startAt: number
  /** Counted up whenever the current track has to be fetched again. */
  load: number
  volume: number
  muted: boolean
  shuffle: boolean
  repeat: Repeat
  quality: Quality
  /** The player turned the quality down itself, after the sound kept stalling. Not remembered. */
  reduced: boolean
  error: string
  barHidden: boolean
  barStyle: BarStyle
  barCorner: BarCorner
  barCollapsed: boolean
  cardsOnScreen: Record<number, boolean>
  controller: PlayerController | null
  library: LibraryRequest | null

  play:(source: PlayerSource, tracks: MusicTrack[], start?: number, options?: { shuffle?: boolean }) => void
  playNext: (source: PlayerSource, tracks: MusicTrack[]) => void
  enqueue: (source: PlayerSource, tracks: MusicTrack[]) => void
  toggle: () => void
  pause: () => void
  resume: () => void
  next: (auto?: boolean) => void
  previous: () => void
  jump: (index: number) => void
  removeAt: (index: number) => void
  seek: (seconds: number) => void
  restartFrom: (seconds: number) => void
  setVolume: (volume: number) => void
  toggleMute: () => void
  toggleShuffle: () => void
  cycleRepeat: () => void
  setQuality: (quality: Quality, auto?: boolean) => void
  stop: () => void
  report: (patch: Partial<Pick<PlayerState, 'state' | 'time' | 'duration' | 'error'>>) => void
  setController: (controller: PlayerController | null) => void
  setCardOnScreen: (widgetId: number, onScreen: boolean) => void
  setBarHidden: (hidden: boolean) => void
  setBarStyle: (style: BarStyle) => void
  setBarCorner: (corner: BarCorner) => void
  setBarCollapsed: (collapsed: boolean) => void
  openLibrary:(source: PlayerSource, tab?: LibraryTab, newest?: MusicAlbum[], album?: { id: string; title: string }) => void
  closeLibrary: () => void
}

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function write(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    // storage may be unavailable; the setting then lasts as long as the page
  }
}

function storedVolume(): number {
  const value = Number(read(STORAGE.volume))
  return read(STORAGE.volume) !== null && Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 1
}

function storedQuality(): Quality {
  const value = read(STORAGE.quality)
  return value === 'high' || value === 'low' ? value : 'original'
}

function storedRepeat(): Repeat {
  const value = read(STORAGE.repeat)
  return value === 'all' || value === 'one' ? value : 'off'
}

function storedCorner(): BarCorner {
  const value = read(STORAGE.corner)
  return BAR_CORNERS.includes(value as BarCorner) ? (value as BarCorner) : 'bottom-right'
}

/** Fisher and Yates; `random` is there for the tests. */
export function shuffled<T>(items: T[], random: () => number = Math.random): T[] {
  const copy = [...items]
  for (let index = copy.length - 1; index > 0; index -= 1) {
    const other = Math.floor(random() * (index + 1))
    ;[copy[index], copy[other]] = [copy[other], copy[index]]
  }
  return copy
}

export function currentTrack(state: Pick<PlayerState, 'queue' | 'at'>): MusicTrack | undefined {
  return state.queue[state.at]
}

/** Tracks a new queue starts with; copies, so the same track twice is two entries rather than one object in two places. */
function fresh(tracks: MusicTrack[]): MusicTrack[] {
  return tracks.map((track) => ({ ...track }))
}

export const usePlayer = create<PlayerState>((set, get) => ({
  source: null,
  queue: [],
  unshuffled: null,
  at: 0,
  wantsToPlay: false,
  state: 'idle',
  time: 0,
  duration: null,
  startAt: 0,
  load: 0,
  volume: storedVolume(),
  muted: read(STORAGE.muted) === '1',
  shuffle: false,
  repeat: storedRepeat(),
  quality: storedQuality(),
  reduced: false,
  error: '',
  barHidden: false,
  barStyle: read(STORAGE.bar) === 'header' ? 'header' : 'floating',
  barCorner: storedCorner(),
  barCollapsed: read(STORAGE.collapsed) === '1',
  cardsOnScreen: {},
  controller: null,
  library: null,

  play:(source, tracks, start = 0, options = {}) => {
    if (!tracks.length) return
    const list = fresh(tracks)
    const mix = options.shuffle ?? get().shuffle
    const first = Math.min(Math.max(0, start), list.length - 1)
    let queue = list
    let at = first
    if (mix) {
      // Shuffle on and a track picked: that track first, the rest mixed behind it.
      // Shuffle asked for without a pick: everything mixed.
      const chosen = options.shuffle && start === 0 ? null : list[first]
      queue = chosen ? [chosen, ...shuffled(list.filter((track) => track !== chosen))] : shuffled(list)
      at = 0
    }
    set((state) => ({
      source, queue, unshuffled: mix ? list : null, at, shuffle: mix, wantsToPlay: true, state: 'loading',
      time: 0, duration: queue[at].duration, startAt: 0, load: state.load + 1, error: '',
    }))
  },

  playNext: (source, tracks) => {
    const state = get()
    if (!state.queue.length || state.source?.widgetId !== source.widgetId) return state.play(source, tracks)
    const added = fresh(tracks)
    const queue = [...state.queue.slice(0, state.at + 1), ...added, ...state.queue.slice(state.at + 1)]
    set({ queue, unshuffled: state.unshuffled ? [...state.unshuffled, ...added] : null })
  },

  enqueue: (source, tracks) => {
    const state = get()
    if (!state.queue.length || state.source?.widgetId !== source.widgetId) return state.play(source, tracks)
    const added = fresh(tracks)
    set({ queue: [...state.queue, ...added], unshuffled: state.unshuffled ? [...state.unshuffled, ...added] : null })
  },

  toggle: () => {
    const state = get()
    if (!currentTrack(state)) return
    set({ wantsToPlay: !state.wantsToPlay })
  },
  pause: () => set({ wantsToPlay: false }),
  resume: () => {
    if (currentTrack(get())) set({ wantsToPlay: true })
  },

  next: (auto = false) => {
    const state = get()
    if (!state.queue.length) return
    if (auto && state.repeat === 'one') {
      set({ time: 0, startAt: 0, load: state.load + 1, wantsToPlay: true })
      return
    }
    if (state.at + 1 < state.queue.length) {
      set({ at: state.at + 1, time: 0, startAt: 0, duration: state.queue[state.at + 1].duration, load: state.load + 1, error: '' })
      return
    }
    if (state.repeat === 'all') {
      set({ at: 0, time: 0, startAt: 0, duration: state.queue[0].duration, load: state.load + 1, error: '' })
      return
    }
    // The end of the queue: stop on the last track, so pressing play hears it again.
    if (auto) set({ wantsToPlay: false, state: 'paused', time: 0, startAt: 0, load: state.load + 1 })
  },

  previous: () => {
    const state = get()
    if (!state.queue.length) return
    if (state.time > RESTART_AFTER || state.at === 0) {
      state.seek(0)
      return
    }
    set({ at: state.at - 1, time: 0, startAt: 0, duration: state.queue[state.at - 1].duration, load: state.load + 1, error: '' })
  },

  jump: (index) => {
    const state = get()
    if (index < 0 || index >= state.queue.length) return
    set({ at: index, time: 0, startAt: 0, duration: state.queue[index].duration, load: state.load + 1, wantsToPlay: true, error: '' })
  },

  removeAt: (index) => {
    const state = get()
    if (index < 0 || index >= state.queue.length) return
    const gone = state.queue[index]
    const queue = state.queue.filter((_, position) => position !== index)
    const unshuffled = state.unshuffled ? state.unshuffled.filter((track) => track !== gone) : null
    if (!queue.length) return state.stop()
    if (index < state.at) {
      set({ queue, unshuffled, at: state.at - 1 })
      return
    }
    if (index > state.at) {
      set({ queue, unshuffled })
      return
    }
    // The track playing was taken out: the one after it moves up and plays.
    const at = Math.min(state.at, queue.length - 1)
    set({ queue, unshuffled, at, time: 0, startAt: 0, duration: queue[at].duration, load: state.load + 1 })
  },

  seek: (seconds) => {
    const state = get()
    const limit = state.duration ?? currentTrack(state)?.duration ?? null
    const to = Math.max(0, limit ? Math.min(seconds, limit) : seconds)
    if (state.controller) state.controller.seek(to)
    else set({ time: to })
  },

  restartFrom: (seconds) => set((state) => ({ startAt: Math.max(0, seconds), time: Math.max(0, seconds), load: state.load + 1 })),

  setVolume: (volume) => {
    const value = Math.min(1, Math.max(0, volume))
    write(STORAGE.volume, String(value))
    set({ volume: value, muted: value === 0 ? get().muted : false })
  },

  toggleMute: () => {
    const muted = !get().muted
    write(STORAGE.muted, muted ? '1' : '0')
    set({ muted })
  },

  toggleShuffle: () => {
    const state = get()
    const current = currentTrack(state)
    if (!state.shuffle) {
      if (!current) return set({ shuffle: true })
      // What has played stays where it is; what is still to come gets mixed.
      const queue = [...state.queue.slice(0, state.at + 1), ...shuffled(state.queue.slice(state.at + 1))]
      set({ shuffle: true, queue, unshuffled: state.queue })
      return
    }
    if (!state.unshuffled || !current) return set({ shuffle: false, unshuffled: null })
    const at = Math.max(0, state.unshuffled.indexOf(current))
    set({ shuffle: false, queue: state.unshuffled, unshuffled: null, at })
  },

  cycleRepeat: () => {
    const repeat: Repeat = { off: 'all', all: 'one', one: 'off' }[get().repeat] as Repeat
    write(STORAGE.repeat, repeat)
    set({ repeat })
  },

  setQuality: (quality, auto = false) => {
    const state = get()
    if (!auto) write(STORAGE.quality, quality)
    const playing = Boolean(currentTrack(state))
    set({
      quality,
      reduced: auto,
      // Fetched again from where it is, so the change is heard at once and nothing is skipped.
      ...(playing && quality !== state.quality ? { startAt: state.time, load: state.load + 1 } : {}),
    })
  },

  stop: () => set((state) => ({
    source: null, queue: [], unshuffled: null, at: 0, wantsToPlay: false, state: 'idle', time: 0, duration: null,
    startAt: 0, load: state.load + 1, error: '', reduced: false,
  })),

  report: (patch) => set(patch),
  setController: (controller) => set({ controller }),
  setCardOnScreen: (widgetId, onScreen) =>
    set((state) => (Boolean(state.cardsOnScreen[widgetId]) === onScreen ? state : { cardsOnScreen: { ...state.cardsOnScreen, [widgetId]: onScreen } })),
  setBarHidden: (hidden) => set((state) => (state.barHidden === hidden ? state : { barHidden: hidden })),
  setBarStyle: (style) => {
    write(STORAGE.bar, style)
    set({ barStyle: style })
  },
  setBarCorner: (corner) => {
    write(STORAGE.corner, corner)
    set({ barCorner: corner })
  },
  setBarCollapsed: (collapsed) => {
    write(STORAGE.collapsed, collapsed ? '1' : '0')
    set({ barCollapsed: collapsed })
  },
  openLibrary:(source, tab = 'new', newest, album) => set({ library: { source, tab, newest, album } }),
  closeLibrary: () => set({ library: null }),
}))
