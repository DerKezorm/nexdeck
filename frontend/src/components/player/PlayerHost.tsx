/**
 * The element that makes the sound, once for the whole app.
 *
 * It sits beside the routes, so switching board or page does not unmount it.
 * Everything else about the player only writes to the store; this listens and
 * turns that into what an `<audio>` element understands, and reports back what
 * the element really did.
 */
import { lazy, Suspense, useEffect, useRef } from 'react'

import { mediaUrl } from '../../api/client'
import { soundUrl, type MusicTrack } from '../../api/music'
import { playableFormats, playsHlsNatively } from '../../lib/audioFormats'
import { currentTrack, usePlayer, type PlayerSource } from '../../stores/player'

const MiniPlayer = lazy(() => import('./MiniPlayer').then((module) => ({ default: module.MiniPlayer })))
const LibrarySheet = lazy(() => import('./LibrarySheet').then((module) => ({ default: module.LibrarySheet })))

/** Stalls inside this window, after playing had begun, turn the quality down. */
const STALL_WINDOW_MS = 30_000
const STALLS_TO_REDUCE = 3
/** A skip makes the element wait for data too; that is not the line being slow. */
const SEEK_GRACE_MS = 2500
/** How long an error stays on screen before the next track is tried. */
const SKIP_AFTER_ERROR_MS = 2500
/**
 * How long the sound may wait for data before it is asked for again.
 *
 * ⚠️ Measured on 11.09.2026 over a phone's hotspot: a board with four player
 * cards loaded about fifty covers, each a second through the media server,
 * and the browser opens six connections to one address. The track's request
 * got its first bytes, then queued behind the covers, and the element sat at
 * "loading" for over a minute without ever saying it had given up. Asked for
 * again once the covers were through, it played within two seconds.
 */
const STUCK_AFTER_MS = 12_000
const RETRIES_WHEN_STUCK = 2

export function PlayerHost() {
  const element = useRef<HTMLAudioElement>(null)
  const hasQueue = usePlayer((state) => state.queue.length > 0)
  const libraryOpen = usePlayer((state) => state.library !== null)

  useEffect(() => {
    const audio = element.current
    if (!audio) return
    const store = usePlayer
    /** The second the element's own zero stands for: converted sound fetched from a later point starts there. */
    let offset = 0
    /**
     * The second a load was asked to start at, until the element says what it got.
     *
     * ⚠️ Decided on arrival, not on asking. The server honours a start only
     * when it converts; the file itself always comes from its first byte.
     * Which of the two arrived is only known once the element has a length:
     * a file has one and is skipped into, a conversion has none and already
     * starts there.
     */
    let pendingStart = 0
    let lastKey = ''
    let lastTrackKey = ''
    let lastWant = store.getState().wantsToPlay
    let lastReported = -1
    let lastPosition = 0
    let loadedAt = 0
    let seekingUntil = 0
    let stalls: number[] = []
    /** Converted sound that failed is tried once more as the file itself. */
    let fellBack = false
    let skipTimer = 0
    let stuckTimer = 0
    let retries = 0

    /** Started whenever the element waits for data; `playing` ends the wait. */
    const watch = () => {
      window.clearTimeout(stuckTimer)
      stuckTimer = window.setTimeout(() => {
        const state = store.getState()
        if (!state.wantsToPlay || !currentTrack(state) || audio.readyState >= 3) return
        if (retries >= RETRIES_WHEN_STUCK) {
          onError()
          return
        }
        retries += 1
        state.restartFrom(state.time)
      }, STUCK_AFTER_MS)
    }
    const unwatch = () => window.clearTimeout(stuckTimer)
    const tab = Math.random().toString(36).slice(2)
    const channel = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('nexdeck-player') : null

    const tryPlay = () => {
      void audio.play().catch((failure: unknown) => {
        // ⚠️ A browser refuses sound nobody asked for, which is what a kiosk
        // or a reloaded page is. That is not a broken track: the button goes
        // back to "play" and the next press works.
        if (failure instanceof DOMException && failure.name === 'NotAllowedError') {
          store.setState({ wantsToPlay: false, state: 'paused' })
        }
      })
    }

    const sourceFor = (source: PlayerSource, track: MusicTrack, startAt: number, original: boolean) => {
      const state = store.getState()
      const quality = original ? 'original' : state.quality
      const hls = quality !== 'original' && source.features.includes('hls') && playsHlsNatively()
      offset = 0
      pendingStart = startAt
      return soundUrl(source.widgetId, track.id, { quality, formats: playableFormats(), start: startAt, hls })
    }

    const load = (original = false) => {
      const state = store.getState()
      const track = currentTrack(state)
      window.clearTimeout(skipTimer)
      if (!track || !state.source) {
        audio.pause()
        audio.removeAttribute('src')
        audio.load()
        clearSession()
        return
      }
      audio.src = sourceFor(state.source, track, state.startAt, original)
      audio.load()
      loadedAt = Date.now()
      stalls = []
      lastReported = -1
      store.getState().report({ state: 'loading', time: state.startAt, error: '' })
      describe(state.source, track)
      if (state.wantsToPlay) {
        tryPlay()
        watch()
      }
    }

    const apply = (state: ReturnType<typeof store.getState>) => {
      const track = currentTrack(state)
      const key = track && state.source ? `${state.source.widgetId}|${state.load}` : ''
      const trackKey = track && state.source ? `${state.source.widgetId}|${track.id}|${state.at}` : ''
      if (key !== lastKey) {
        // A new track starts with its retries unspent; the same track asked for again keeps counting.
        if (trackKey !== lastTrackKey) retries = 0
        lastTrackKey = trackKey
        lastKey = key
        fellBack = false
        load()
      }
      if (state.wantsToPlay !== lastWant) {
        lastWant = state.wantsToPlay
        if (state.wantsToPlay && track) {
          tryPlay()
          if (audio.readyState < 3) watch()
        } else {
          audio.pause()
          unwatch()
        }
      }
      audio.volume = state.volume
      audio.muted = state.muted
    }

    // -- the lock screen, the headphone button and the keyboard's media keys --
    const session = typeof navigator !== 'undefined' && 'mediaSession' in navigator ? navigator.mediaSession : null
    const describe = (source: PlayerSource, track: MusicTrack) => {
      if (!session || typeof MediaMetadata === 'undefined') return
      const art = track.art ? new URL(mediaUrl(source.widgetId, track.art), window.location.href).toString() : ''
      session.metadata = new MediaMetadata({
        title: track.title,
        artist: track.artist,
        album: track.album,
        artwork: art ? [{ src: art, sizes: '800x800', type: 'image/jpeg' }] : [],
      })
    }
    const clearSession = () => {
      if (!session) return
      session.metadata = null
      session.playbackState = 'none'
    }
    const handlers: [MediaSessionAction, MediaSessionActionHandler][] = [
      ['play', () => store.getState().resume()],
      ['pause', () => store.getState().pause()],
      ['previoustrack', () => store.getState().previous()],
      ['nexttrack', () => store.getState().next()],
      ['seekto', (details) => store.getState().seek(Number(details.seekTime ?? 0))],
      ['seekbackward', (details) => store.getState().seek(store.getState().time - Number(details.seekOffset ?? 10))],
      ['seekforward', (details) => store.getState().seek(store.getState().time + Number(details.seekOffset ?? 10))],
    ]
    for (const [action, handler] of handlers) {
      try {
        session?.setActionHandler(action, handler)
      } catch {
        // an action this browser does not know
      }
    }

    store.getState().setController({
      seek: (to) => {
        seekingUntil = Date.now() + SEEK_GRACE_MS
        // The file itself, and HLS with its length, skip where they are. Converted
        // sound has no length to skip in and is fetched again from that second.
        if (offset === 0 && Number.isFinite(audio.duration) && audio.duration > 0) {
          audio.currentTime = to
          store.getState().report({ time: to })
        } else {
          store.getState().restartFrom(to)
        }
      },
    })

    const onTime = () => {
      // Until the element says what arrived, its zero is not yet anybody's second.
      if (pendingStart > 0) return
      const time = offset + audio.currentTime
      if (Math.abs(time - lastReported) >= 0.25) {
        lastReported = time
        store.getState().report({ time })
      }
      const duration = store.getState().duration
      if (session && duration && Math.abs(time - lastPosition) >= 1 && time <= duration) {
        lastPosition = time
        try {
          session.setPositionState({ duration, position: time, playbackRate: 1 })
        } catch {
          // a position the browser finds implausible for a moment
        }
      }
    }
    const onDuration = () => {
      const measured = Number.isFinite(audio.duration) && audio.duration > 0
      if (pendingStart > 0 && !Number.isNaN(audio.duration)) {
        if (measured) {
          // The file itself, or HLS with its length: skipped into on the element.
          audio.currentTime = pendingStart
          offset = 0
        } else {
          // A conversion that the server already started at that second.
          offset = pendingStart
        }
        pendingStart = 0
      }
      if (offset === 0 && measured) {
        store.getState().report({ duration: audio.duration })
      }
    }
    const onPlaying = () => {
      unwatch()
      retries = 0
      store.getState().report({ state: 'playing', error: '' })
      if (!store.getState().wantsToPlay) store.setState({ wantsToPlay: true })
      lastWant = true
      if (session) session.playbackState = 'playing'
      channel?.postMessage({ playing: tab })
    }
    const onPause = () => {
      unwatch()
      if (audio.ended) return
      const state = store.getState()
      state.report({ state: currentTrack(state) ? 'paused' : 'idle' })
      // Paused from outside (the lock screen, another tab): the button follows.
      if (state.wantsToPlay && currentTrack(state)) store.setState({ wantsToPlay: false })
      lastWant = false
      if (session) session.playbackState = 'paused'
    }
    const onWaiting = () => {
      const now = Date.now()
      store.getState().report({ state: 'loading' })
      if (store.getState().wantsToPlay) watch()
      if (now < seekingUntil || now - loadedAt < 4000 || audio.currentTime < 1) return
      stalls = [...stalls.filter((at) => now - at < STALL_WINDOW_MS), now]
      const state = store.getState()
      if (stalls.length >= STALLS_TO_REDUCE && state.quality === 'original') {
        stalls = []
        state.setQuality('high', true)
      }
    }
    const onEnded = () => store.getState().next(true)
    const onError = () => {
      if (!audio.getAttribute('src')) return
      const state = store.getState()
      if (!fellBack && state.quality !== 'original') {
        // Converted sound the browser would not take, which is Safari with a
        // stream that has no length: the file itself plays there.
        fellBack = true
        load(true)
        return
      }
      state.report({ state: 'error', error: 'failed' })
      const more = state.at + 1 < state.queue.length || state.repeat === 'all'
      if (more && state.wantsToPlay) skipTimer = window.setTimeout(() => store.getState().next(), SKIP_AFTER_ERROR_MS)
    }

    audio.addEventListener('timeupdate', onTime)
    audio.addEventListener('durationchange', onDuration)
    audio.addEventListener('loadedmetadata', onDuration)
    audio.addEventListener('playing', onPlaying)
    audio.addEventListener('pause', onPause)
    audio.addEventListener('waiting', onWaiting)
    audio.addEventListener('ended', onEnded)
    audio.addEventListener('error', onError)
    audio.addEventListener('stalled', onWaiting)
    if (channel) {
      // One tab plays at a time: two players on the same speakers are noise.
      channel.onmessage = (event: MessageEvent<{ playing?: string }>) => {
        if (event.data?.playing && event.data.playing !== tab && !audio.paused) store.getState().pause()
      }
    }

    apply(store.getState())
    const unsubscribe = store.subscribe(apply)
    return () => {
      unsubscribe()
      window.clearTimeout(skipTimer)
      window.clearTimeout(stuckTimer)
      store.getState().setController(null)
      audio.removeEventListener('timeupdate', onTime)
      audio.removeEventListener('durationchange', onDuration)
      audio.removeEventListener('loadedmetadata', onDuration)
      audio.removeEventListener('playing', onPlaying)
      audio.removeEventListener('pause', onPause)
      audio.removeEventListener('waiting', onWaiting)
      audio.removeEventListener('ended', onEnded)
      audio.removeEventListener('error', onError)
      audio.removeEventListener('stalled', onWaiting)
      channel?.close()
      for (const [action] of handlers) {
        try {
          session?.setActionHandler(action, null)
        } catch {
          // as above
        }
      }
    }
  }, [])

  return (
    <>
      <audio ref={element} preload="auto" data-testid="player-audio" />
      {hasQueue && (
        <Suspense fallback={null}>
          <MiniPlayer />
        </Suspense>
      )}
      {libraryOpen && (
        <Suspense fallback={null}>
          <LibrarySheet />
        </Suspense>
      )}
    </>
  )
}
