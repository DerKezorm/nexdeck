/**
 * The pieces every face of the player is built from: the cover, the buttons,
 * the seek bar, the volume, and the colour a cover lends the card.
 */
import { Disc3, Loader2, Pause, Play, Repeat, Repeat1, Shuffle, SkipBack, SkipForward, Volume1, Volume2, VolumeX } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type CSSProperties, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'

import type { MusicTrack, Quality } from '../../api/music'
import { canSetVolume } from '../../lib/audioFormats'
import { usePlayer } from '../../stores/player'

/** 3:05, or 1:02:09 for the long ones. Nothing known is a dash, never 0:00. */
export function formatTime(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) return '-:--'
  const whole = Math.floor(seconds)
  const hours = Math.floor(whole / 3600)
  const minutes = Math.floor((whole % 3600) / 60)
  const rest = String(whole % 60).padStart(2, '0')
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`
}

/** What the sound is, in the few characters a badge has: "FLAC 24/96", "MP3 320". */
export function soundBadge(track: MusicTrack | undefined, quality: Quality): string {
  if (!track) return ''
  if (quality === 'high') return 'MP3 320'
  if (quality === 'low') return 'MP3 128'
  const codec = track.codec.toUpperCase()
  if (!codec) return ''
  if (track.bit_depth && track.sample_rate) {
    const rate = track.sample_rate % 1000 === 0 ? track.sample_rate / 1000 : (track.sample_rate / 1000).toFixed(1)
    return `${codec} ${track.bit_depth}/${rate}`
  }
  if (track.bitrate && ['MP3', 'AAC', 'OPUS', 'VORBIS'].includes(codec)) return `${codec} ${track.bitrate}`
  return codec
}

/** The card's size, measured, because what fits depends on height as much as on width. */
export function useBoxSize(ref: RefObject<HTMLElement | null>): { width: number; height: number } {
  const [size, setSize] = useState({ width: 0, height: 0 })
  useEffect(() => {
    const node = ref.current
    if (!node) return
    // ⚠️ Measured once at once, not only when the observer reports. Its
    // reports come with the next painted frame, and a tab that is not on
    // screen paints none: the card sat in its fallback face until somebody
    // looked, and the first frame anybody saw was the wrong one.
    setSize({ width: node.clientWidth, height: node.clientHeight })
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) => {
      const box = entry.contentRect
      setSize((old) => (Math.abs(old.width - box.width) < 1 && Math.abs(old.height - box.height) < 1 ? old : { width: box.width, height: box.height }))
    })
    observer.observe(node)
    return () => observer.disconnect()
  }, [ref])
  return size
}

const colours = new Map<string, Palette>()

export interface Palette {
  accent: string
  ink: string
}

/**
 * The colour a cover lends the card: its most vivid tone, kept bright enough to
 * read on the dark card and dark enough to carry white on the light one.
 *
 * Only possible because covers come through nexdeck's own address. A cover
 * from another origin would taint the canvas and give nothing back.
 */
export function useCoverColour(url: string): Palette | null {
  const [palette, setPalette] = useState<Palette | null>(() => (url ? colours.get(url) ?? null : null))
  useEffect(() => {
    if (!url) {
      setPalette(null)
      return
    }
    const known = colours.get(url)
    if (known) {
      setPalette(known)
      return
    }
    let gone = false
    const image = new Image()
    image.decoding = 'async'
    image.onload = () => {
      if (gone) return
      const found = paletteOf(image)
      if (found) colours.set(url, found)
      setPalette(found)
    }
    image.onerror = () => {
      if (!gone) setPalette(null)
    }
    image.src = url
    return () => {
      gone = true
    }
  }, [url])
  return palette
}

function paletteOf(image: HTMLImageElement): Palette | null {
  try {
    const canvas = document.createElement('canvas')
    canvas.width = 24
    canvas.height = 24
    const context = canvas.getContext('2d', { willReadFrequently: true })
    if (!context) return null
    context.drawImage(image, 0, 0, 24, 24)
    const { data } = context.getImageData(0, 0, 24, 24)
    let red = 0
    let green = 0
    let blue = 0
    let weight = 0
    for (let index = 0; index < data.length; index += 4) {
      const [r, g, b] = [data[index] / 255, data[index + 1] / 255, data[index + 2] / 255]
      const high = Math.max(r, g, b)
      const low = Math.min(r, g, b)
      const light = (high + low) / 2
      const saturation = high === low ? 0 : (high - low) / (1 - Math.abs(2 * light - 1))
      // Vivid and neither near black nor near white counts most.
      const counts = saturation * saturation * (1 - Math.abs(light - 0.5) * 1.6) + 0.002
      red += r * counts
      green += g * counts
      blue += b * counts
      weight += counts
    }
    if (!weight) return null
    const [h, s] = toHsl(red / weight, green / weight, blue / weight)
    // Muted covers keep a little colour rather than turning the card grey.
    const saturation = Math.max(0.45, Math.min(0.9, s * 1.25))
    const accent = `hsl(${Math.round(h)} ${Math.round(saturation * 100)}% 62%)`
    return { accent, ink: '#0a0d12' }
  } catch {
    return null
  }
}

function toHsl(r: number, g: number, b: number): [number, number, number] {
  const high = Math.max(r, g, b)
  const low = Math.min(r, g, b)
  const light = (high + low) / 2
  if (high === low) return [0, 0, light]
  const delta = high - low
  const saturation = delta / (1 - Math.abs(2 * light - 1))
  let hue: number
  if (high === r) hue = ((g - b) / delta) % 6
  else if (high === g) hue = (b - r) / delta + 2
  else hue = (r - g) / delta + 4
  return [(hue * 60 + 360) % 360, saturation, light]
}

/** The cover, or a disc when there is none; the new one fades in over the old. */
export function Cover({ src, alt = '', className = '', round = false, iconSize = 28 }: { src: string; alt?: string; className?: string; round?: boolean; iconSize?: number }) {
  const [broken, setBroken] = useState(false)
  useEffect(() => setBroken(false), [src])
  return (
    <div className={`player-cover relative overflow-hidden ${round ? 'rounded-full' : 'rounded-xl'} ${className}`}>
      {src && !broken ? (
        <img key={src} src={src} alt={alt} loading="lazy" draggable={false} className="player-fade absolute inset-0 w-full h-full object-cover" onError={() => setBroken(true)} />
      ) : (
        <div className="absolute inset-0 grid place-items-center text-white/70">
          <Disc3 size={iconSize} strokeWidth={1.4} aria-hidden="true" />
        </div>
      )}
    </div>
  )
}

/** One cover on the card that can be pressed: open its album, and a round button to play it. */
export interface ArtTile {
  src: string
  /** What the cover is, for the names of its buttons. */
  title: string
  onOpen?: () => void
  onPlay?: () => void
}

function Tile({ tile, iconSize, playSize }: { tile: ArtTile | undefined; iconSize: number; playSize: number }) {
  const { t } = useTranslation()
  const [broken, setBroken] = useState(false)
  useEffect(() => setBroken(false), [tile?.src])
  const picture = tile?.src && !broken ? (
    <img key={tile.src} src={tile.src} alt="" loading="lazy" draggable={false} className="player-fade absolute inset-0 w-full h-full object-cover" onError={() => setBroken(true)} />
  ) : (
    <span className="absolute inset-0 grid place-items-center text-white/45">
      <Disc3 size={iconSize} strokeWidth={1.4} aria-hidden="true" />
    </span>
  )
  if (!tile?.onOpen) return <div className="relative overflow-hidden">{picture}</div>
  return (
    <div className="player-art-tile relative overflow-hidden">
      <button type="button" className="absolute inset-0 w-full h-full" onClick={tile.onOpen} aria-label={t('player.openAlbum', { name: tile.title })} title={tile.title}>
        {picture}
      </button>
      {tile.onPlay && (
        <button
          type="button"
          className="player-art-play"
          style={{ width: playSize, height: playSize }}
          onClick={tile.onPlay}
          aria-label={t('player.playAlbum', { name: tile.title })}
          title={t('player.playAlbum', { name: tile.title })}
        >
          <Play size={Math.round(playSize * 0.42)} fill="currentColor" className="translate-x-[1px]" />
        </button>
      )}
    </div>
  )
}

/** One cover or four, for a player with nothing playing. Missing ones are discs. */
export function Artwork({ tiles, count, className = '', iconSize = 28 }: { tiles: ArtTile[]; count: 1 | 4; className?: string; iconSize?: number }) {
  const shown = Array.from({ length: count }, (_, index) => tiles[index])
  return (
    <div className={`player-cover relative overflow-hidden rounded-xl grid ${count === 4 ? 'grid-cols-2 grid-rows-2 gap-px' : ''} ${className}`} data-testid="player-artwork" data-count={count}>
      {shown.map((tile, index) => (
        <Tile key={index} tile={tile} iconSize={count === 4 ? Math.round(iconSize * 0.6) : iconSize} playSize={count === 4 ? 28 : 38} />
      ))}
    </div>
  )
}

/** Three bars that dance while this row is what plays. */
export function Equalizer({ playing }: { playing: boolean }) {
  return (
    <span className={`player-eq ${playing ? '' : 'is-still'}`} aria-hidden="true">
      <i />
      <i />
      <i />
    </span>
  )
}

export function PlayButton({ size = 44, disabled, onPress, label }: { size?: number; disabled?: boolean; onPress: () => void; label?: string }) {
  const { t } = useTranslation()
  const wants = usePlayer((state) => state.wantsToPlay)
  const waiting = usePlayer((state) => state.state === 'loading' && state.wantsToPlay)
  const name = label ?? (wants ? t('player.pause') : t('player.play'))
  const icon = Math.round(size * 0.42)
  return (
    <button
      type="button"
      className="player-play"
      style={{ width: size, height: size } as CSSProperties}
      onClick={(event) => {
        event.stopPropagation()
        onPress()
      }}
      disabled={disabled}
      aria-label={name}
      title={name}
    >
      {waiting ? <Loader2 size={icon} className="animate-spin" /> : wants && !label ? <Pause size={icon} fill="currentColor" /> : <Play size={icon} fill="currentColor" className="translate-x-[1px]" />}
    </button>
  )
}

/** Back, play, forward, and on wider faces shuffle and repeat around them. */
export function Transport({ size = 44, extras = true, disabled }: { size?: number; extras?: boolean; disabled?: boolean }) {
  const { t } = useTranslation()
  const toggle = usePlayer((state) => state.toggle)
  const previous = usePlayer((state) => state.previous)
  const next = usePlayer((state) => state.next)
  const shuffle = usePlayer((state) => state.shuffle)
  const repeat = usePlayer((state) => state.repeat)
  const toggleShuffle = usePlayer((state) => state.toggleShuffle)
  const cycleRepeat = usePlayer((state) => state.cycleRepeat)
  const small = Math.round(size * 0.4)
  const repeatName = t(`player.repeat.${repeat}`)
  return (
    <div className="flex items-center justify-center gap-1.5">
      {extras && (
        <button type="button" className="player-icon" aria-pressed={shuffle} onClick={toggleShuffle} disabled={disabled} aria-label={t('player.shuffle')} title={t('player.shuffle')}>
          <Shuffle size={small - 2} />
        </button>
      )}
      <button type="button" className="player-icon" onClick={previous} disabled={disabled} aria-label={t('player.previous')} title={t('player.previous')}>
        <SkipBack size={small} fill="currentColor" />
      </button>
      <PlayButton size={size} onPress={toggle} disabled={disabled} />
      <button type="button" className="player-icon" onClick={() => next()} disabled={disabled} aria-label={t('player.next')} title={t('player.next')}>
        <SkipForward size={small} fill="currentColor" />
      </button>
      {extras && (
        <button type="button" className="player-icon" aria-pressed={repeat !== 'off'} onClick={cycleRepeat} disabled={disabled} aria-label={repeatName} title={repeatName}>
          {repeat === 'one' ? <Repeat1 size={small - 2} /> : <Repeat size={small - 2} />}
        </button>
      )}
    </div>
  )
}

/**
 * Where the track is, and where to go in it.
 *
 * A native range input, styled: it brings the keyboard, the screen reader and
 * the touch handling along, which a drawn bar has to be taught one by one.
 */
export function SeekBar({ compact = false, disabled }: { compact?: boolean; disabled?: boolean }) {
  const { t } = useTranslation()
  const time = usePlayer((state) => state.time)
  const duration = usePlayer((state) => state.duration ?? state.queue[state.at]?.duration ?? null)
  const seek = usePlayer((state) => state.seek)
  const [held, setHeld] = useState<number | null>(null)
  const shown = held ?? time
  const total = duration && duration > 0 ? duration : 0
  const share = total ? Math.min(100, (shown / total) * 100) : 0
  const commit = () => {
    if (held !== null) seek(held)
    setHeld(null)
  }
  return (
    <div className={`flex items-center gap-2 ${compact ? 'text-[10px]' : 'text-[11px]'}`}>
      {!compact && <span className="num text-muted w-10 text-right tabular-nums">{formatTime(shown)}</span>}
      <input
        type="range"
        className="player-range flex-1"
        min={0}
        max={total || 1}
        step={1}
        value={total ? Math.min(shown, total) : 0}
        style={{ '--fill': `${share}%` } as CSSProperties}
        disabled={disabled || !total}
        aria-label={t('player.position')}
        aria-valuetext={t('player.positionText', { at: formatTime(shown), of: formatTime(total) })}
        onChange={(event) => setHeld(Number(event.target.value))}
        onPointerUp={commit}
        onKeyUp={commit}
        onBlur={commit}
      />
      {!compact && <span className="num text-muted w-10 tabular-nums">{formatTime(total)}</span>}
    </div>
  )
}

/** What is heard, 0 when muted, with the speaker that says so. */
function useVolume() {
  const { t } = useTranslation()
  const volume = usePlayer((state) => state.volume)
  const muted = usePlayer((state) => state.muted)
  const shown = muted ? 0 : volume
  return {
    shown,
    Icon: shown === 0 ? VolumeX : shown < 0.5 ? Volume1 : Volume2,
    muteName: muted ? t('player.unmute') : t('player.mute'),
  }
}

/** The slider with its speaker; the speaker mutes. */
function VolumeSlider({ className = 'w-20', autoFocus = false }: { className?: string; autoFocus?: boolean }) {
  const { t } = useTranslation()
  const { shown, Icon, muteName } = useVolume()
  const setVolume = usePlayer((state) => state.setVolume)
  const toggleMute = usePlayer((state) => state.toggleMute)
  const slider = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (autoFocus) slider.current?.focus({ preventScroll: true })
  }, [autoFocus])
  return (
    <>
      <button type="button" className="player-icon flex-none" onClick={toggleMute} aria-label={muteName} title={muteName}>
        <Icon size={16} />
      </button>
      <input
        ref={slider}
        type="range"
        className={`player-range ${className}`}
        min={0}
        max={1}
        step={0.01}
        value={shown}
        style={{ '--fill': `${shown * 100}%` } as CSSProperties}
        aria-label={t('player.volume')}
        aria-valuetext={`${Math.round(shown * 100)} %`}
        onChange={(event) => setVolume(Number(event.target.value))}
      />
    </>
  )
}

/** The volume laid out in full, for a face with room for it. None where a page may not set it. */
export function VolumeControl() {
  if (!canSetVolume()) return null
  return (
    <div className="flex items-center gap-1.5 min-w-0">
      <VolumeSlider />
    </div>
  )
}

/** How wide the opened volume is; the position is worked out from it. */
const POP_WIDTH = 216

/**
 * The volume behind one button, for a face with no room for a slider: the
 * floating bar, the pill in the top bar, a narrow card.
 *
 * ⚠️ The slider is drawn over the page, not inside the button's face: the bar
 * and the cards cut off whatever sticks out of them. It opens towards the
 * middle of the screen, so it fits above a bar at the bottom and below one at
 * the top. The wheel over the button changes the volume without opening it.
 */
export function VolumeButton({ className = '', iconSize = 15 }: { className?: string; iconSize?: number }) {
  if (!canSetVolume()) return null
  return <VolumePopover className={className} iconSize={iconSize} />
}

function VolumePopover({ className, iconSize }: { className: string; iconSize: number }) {
  const { t } = useTranslation()
  const { shown, Icon } = useVolume()
  const [spot, setSpot] = useState<CSSProperties | null>(null)
  const button = useRef<HTMLButtonElement>(null)
  const pop = useRef<HTMLDivElement>(null)
  const open = spot !== null

  const place = useCallback(() => {
    const node = button.current
    if (!node) return
    const box = node.getBoundingClientRect()
    const left = Math.max(8, Math.min(box.left + box.width / 2 - POP_WIDTH / 2, window.innerWidth - POP_WIDTH - 8))
    const above = box.top + box.height / 2 > window.innerHeight / 2
    // The cover's colour comes along; outside the card nothing would lend it.
    const looks = getComputedStyle(node)
    const accent = looks.getPropertyValue('--pa').trim()
    const ink = looks.getPropertyValue('--pa-ink').trim()
    setSpot({
      left,
      ...(above ? { bottom: window.innerHeight - box.top + 8 } : { top: box.bottom + 8 }),
      ...(accent ? { '--pa': accent } : {}),
      ...(ink ? { '--pa-ink': ink } : {}),
    } as CSSProperties)
  }, [])

  useEffect(() => {
    const node = button.current
    if (!node) return
    // Not passive, or the page scrolls along with every notch.
    const onWheel = (event: WheelEvent) => {
      event.preventDefault()
      const state = usePlayer.getState()
      const from = state.muted ? 0 : state.volume
      state.setVolume(Math.round((from + (event.deltaY < 0 ? 0.05 : -0.05)) * 100) / 100)
    }
    node.addEventListener('wheel', onWheel, { passive: false })
    return () => node.removeEventListener('wheel', onWheel)
  }, [])

  useEffect(() => {
    if (!open) return
    const close = () => setSpot(null)
    const onDown = (event: globalThis.PointerEvent) => {
      const target = event.target as Node
      if (pop.current?.contains(target) || button.current?.contains(target)) return
      close()
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      close()
      button.current?.focus()
    }
    window.addEventListener('pointerdown', onDown, true)
    window.addEventListener('keydown', onKey)
    window.addEventListener('resize', close)
    window.addEventListener('scroll', close, true)
    return () => {
      window.removeEventListener('pointerdown', onDown, true)
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('resize', close)
      window.removeEventListener('scroll', close, true)
    }
  }, [open])

  const name = `${t('player.volume')} · ${Math.round(shown * 100)} %`
  return (
    <>
      <button
        ref={button}
        type="button"
        className={`player-icon ${className}`}
        aria-label={t('player.volume')}
        aria-expanded={open}
        title={name}
        data-testid="player-volume-button"
        onClick={(event) => {
          event.stopPropagation()
          if (open) setSpot(null)
          else place()
        }}
      >
        <Icon size={iconSize} />
      </button>
      {open &&
        createPortal(
          // Events stop here: in React they would still bubble to the bar, which would start dragging.
          <div
            ref={pop}
            className="player-volume-pop glass-strong"
            style={spot}
            role="group"
            aria-label={t('player.volume')}
            data-testid="player-volume-pop"
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => event.stopPropagation()}
          >
            <VolumeSlider className="flex-1" autoFocus />
            <span className="num text-[11px] text-muted w-8 text-right tabular-nums">{Math.round(shown * 100)}</span>
          </div>,
          document.body,
        )}
    </>
  )
}

/** The small print under a title: where the sound comes from and in what shape. */
export function QualityChip({ track }: { track: MusicTrack | undefined }) {
  const { t } = useTranslation()
  const quality = usePlayer((state) => state.quality)
  const reduced = usePlayer((state) => state.reduced)
  const text = soundBadge(track, quality)
  if (!text) return null
  return (
    <span className={`player-chip ${reduced ? 'is-reduced' : ''}`} title={reduced ? t('player.reduced') : undefined}>
      {text}
    </span>
  )
}

/** Tells the store while a card is on screen, so the bar at the bottom steps aside. */
export function useOnScreen(ref: RefObject<HTMLElement | null>, widgetId: number): void {
  const setCardOnScreen = usePlayer((state) => state.setCardOnScreen)
  const last = useRef<boolean | null>(null)
  useEffect(() => {
    const node = ref.current
    if (!node || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver(([entry]) => {
      const visible = entry.isIntersecting && entry.intersectionRatio > 0.35
      if (last.current !== visible) {
        last.current = visible
        setCardOnScreen(widgetId, visible)
      }
    }, { threshold: [0, 0.35, 0.6] })
    observer.observe(node)
    return () => {
      observer.disconnect()
      setCardOnScreen(widgetId, false)
    }
  }, [ref, widgetId, setCardOnScreen])
}
