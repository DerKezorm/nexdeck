/**
 * What plays, while its card is out of sight: a floating bar, or a round
 * button when folded, in one of the four corners.
 *
 * Steps aside when the card is on screen (two players for one song is one too
 * many), while a board is being edited, where the edit bar sits, and on a wide
 * screen whose top bar carries the player instead.
 *
 * ⚠️ Folding and corners were asked for on 11.09.2026, after the first evening
 * with it: the bar was liked and it lay on top of the card underneath. It can
 * be dragged by any part that is not a button and lands in the nearest corner;
 * the settings page offers the same corners to a keyboard.
 */
import { Library as LibraryIcon, Minimize2, SkipBack, SkipForward, X } from 'lucide-react'
import { useEffect, useRef, useState, type CSSProperties, type PointerEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation } from 'react-router-dom'

import { mediaUrl } from '../../api/client'
import { currentTrack, usePlayer, type BarCorner } from '../../stores/player'
import { Cover, PlayButton, QualityChip, useCoverColour, VolumeButton } from './parts'

/** How far a press may wander before it counts as dragging rather than a click. */
const DRAG_AFTER_PX = 6

/** True on screens wide enough to have a top bar worth putting the player into. */
export function useWideScreen(): boolean {
  const query = '(min-width: 768px)'
  const [wide, setWide] = useState(() => (typeof window !== 'undefined' && window.matchMedia ? window.matchMedia(query).matches : true))
  useEffect(() => {
    if (!window.matchMedia) return
    const media = window.matchMedia(query)
    const change = () => setWide(media.matches)
    media.addEventListener('change', change)
    return () => media.removeEventListener('change', change)
  }, [])
  return wide
}

/** The corner nearest to where something was let go. */
export function cornerAt(x: number, y: number, width: number, height: number): BarCorner {
  return `${y < height / 2 ? 'top' : 'bottom'}-${x < width / 2 ? 'left' : 'right'}` as BarCorner
}

export function MiniPlayer() {
  const { t } = useTranslation()
  const location = useLocation()
  const source = usePlayer((state) => state.source)
  const track = usePlayer(currentTrack)
  const hidden = usePlayer((state) => state.barHidden || Boolean(state.source && state.cardsOnScreen[state.source.widgetId]))
  const style = usePlayer((state) => state.barStyle)
  const corner = usePlayer((state) => state.barCorner)
  const collapsed = usePlayer((state) => state.barCollapsed)
  const error = usePlayer((state) => state.error)
  const time = usePlayer((state) => state.time)
  const duration = usePlayer((state) => state.duration ?? currentTrack(state)?.duration ?? 0)
  const palette = useCoverColour(source && track ? mediaUrl(source.widgetId, track.thumb) : '')
  const wide = useWideScreen()
  // /k alone as well: a display takes the token out of its address once it is in.
  const kiosk = location.pathname === '/k' || location.pathname.startsWith('/k/')
  // In the top bar on a wide screen with a top bar; everywhere else the bar stands in.
  const inHeader = style === 'header' && wide && !kiosk
  const shown = Boolean(source && track && !hidden && !inHeader)

  const [drag, setDrag] = useState<{ x: number; y: number; moved: boolean } | null>(null)
  const start = useRef<{ x: number; y: number } | null>(null)

  useEffect(() => {
    if (!shown || !corner.startsWith('bottom')) return
    // Room under the last row of cards, so it can always be scrolled out from under the bar.
    document.body.classList.add('has-player-bar')
    return () => document.body.classList.remove('has-player-bar')
  }, [shown, corner])

  if (!shown || !source || !track) return null
  const share = duration ? Math.min(100, (time / duration) * 100) : 0
  const colours = (palette ? { '--pa': palette.accent, '--pa-ink': palette.ink } : {}) as CSSProperties
  const player = usePlayer.getState()

  const onPointerDown = (event: PointerEvent<HTMLElement>) => {
    if ((event.target as HTMLElement).closest('button:not([data-drag-handle]), input, a')) return
    start.current = { x: event.clientX, y: event.clientY }
    event.currentTarget.setPointerCapture(event.pointerId)
  }
  const onPointerMove = (event: PointerEvent<HTMLElement>) => {
    if (!start.current) return
    const x = event.clientX - start.current.x
    const y = event.clientY - start.current.y
    if (!drag?.moved && Math.hypot(x, y) < DRAG_AFTER_PX) return
    setDrag({ x, y, moved: true })
  }
  const onPointerUp = (event: PointerEvent<HTMLElement>) => {
    const moved = Boolean(drag?.moved)
    start.current = null
    setDrag(null)
    if (moved) {
      player.setBarCorner(cornerAt(event.clientX, event.clientY, window.innerWidth, window.innerHeight))
    } else if (collapsed && !(event.target as HTMLElement).closest('button:not([data-drag-handle])')) {
      player.setBarCollapsed(false)
    }
  }
  const handlers = { onPointerDown, onPointerMove, onPointerUp, onPointerCancel: () => { start.current = null; setDrag(null) } }
  const place = `player-bar-at-${corner} ${kiosk ? 'is-kiosk' : ''} ${drag?.moved ? 'is-dragging' : ''}`
  const moving = drag?.moved ? { transform: `translate(${drag.x}px, ${drag.y}px)` } : undefined

  if (collapsed) {
    const ring = 2 * Math.PI * 27
    return (
      <aside
        className={`player-bubble ${place}`}
        style={{ ...colours, ...moving }}
        aria-label={t('player.bar', { name: source.title })}
        data-testid="player-bubble"
        title={t('player.dragHint')}
        {...handlers}
      >
        <Cover src={mediaUrl(source.widgetId, track.thumb)} round className="absolute inset-[4px]" iconSize={18} />
        <svg className="absolute inset-0 -rotate-90" viewBox="0 0 60 60" aria-hidden="true">
          <circle cx="30" cy="30" r="27" fill="none" strokeWidth="3" className="player-bubble-track" />
          <circle cx="30" cy="30" r="27" fill="none" strokeWidth="3" className="player-bubble-fill" strokeDasharray={ring} strokeDashoffset={ring * (1 - share / 100)} strokeLinecap="round" />
        </svg>
        <span className="player-bubble-play">
          <PlayButton size={30} onPress={player.toggle} />
        </span>
        <button type="button" data-drag-handle className="sr-only" onClick={() => player.setBarCollapsed(false)}>
          {t('player.expand')}
        </button>
      </aside>
    )
  }

  return (
    <aside
      className={`player-bar glass-strong ${place}`}
      style={{ ...colours, ...moving }}
      aria-label={t('player.bar', { name: source.title })}
      data-testid="player-bar"
      title={t('player.dragHint')}
      {...handlers}
    >
      <Cover src={mediaUrl(source.widgetId, track.thumb)} className="w-11 h-11 flex-none shadow-lg" iconSize={18} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 min-w-0">
          <p className="text-[13px] font-medium truncate">{track.title}</p>
          <span className="hidden sm:inline-flex"><QualityChip track={track} /></span>
        </div>
        <p className={`text-[11px] truncate ${error ? 'text-bad' : 'text-muted'}`}>{error ? t('player.failed') : track.artist}</p>
      </div>
      <div className="flex items-center gap-1 flex-none">
        <button type="button" className="player-icon hidden sm:grid" onClick={player.previous} aria-label={t('player.previous')} title={t('player.previous')}>
          <SkipBack size={15} fill="currentColor" />
        </button>
        <PlayButton size={38} onPress={player.toggle} />
        <button type="button" className="player-icon" onClick={() => player.next()} aria-label={t('player.next')} title={t('player.next')}>
          <SkipForward size={15} fill="currentColor" />
        </button>
        <VolumeButton />
        {/* The card may be on another board; the library comes along to wherever this is. */}
        <button type="button" className="player-icon" onClick={() => player.openLibrary(source, 'queue')} aria-label={t('player.openLibrary')} title={t('player.openLibrary')}>
          <LibraryIcon size={15} />
        </button>
        <button type="button" className="player-icon" onClick={() => player.setBarCollapsed(true)} aria-label={t('player.collapse')} title={t('player.collapse')}>
          <Minimize2 size={14} />
        </button>
        <button type="button" className="player-icon" onClick={player.stop} aria-label={t('player.stop')} title={t('player.stop')}>
          <X size={15} />
        </button>
      </div>
      <div className="player-bar-progress" aria-hidden="true">
        <div className="h-full player-fill" style={{ width: `${share}%` }} />
      </div>
    </aside>
  )
}
