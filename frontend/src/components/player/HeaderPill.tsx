/**
 * What plays, as a pill in the top bar: nothing lies over the cards.
 *
 * The other of the two ways asked for on 11.09.2026. Only on a wide screen:
 * a phone's top bar has no room, so the floating bar stands in there.
 */
import { SkipForward } from 'lucide-react'
import type { CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'

import { mediaUrl } from '../../api/client'
import { currentTrack, usePlayer } from '../../stores/player'
import { Cover, PlayButton, useCoverColour, VolumeButton } from './parts'

export function HeaderPill() {
  const { t } = useTranslation()
  const source = usePlayer((state) => state.source)
  const track = usePlayer(currentTrack)
  const time = usePlayer((state) => state.time)
  const duration = usePlayer((state) => state.duration ?? currentTrack(state)?.duration ?? 0)
  const error = usePlayer((state) => state.error)
  const palette = useCoverColour(source && track ? mediaUrl(source.widgetId, track.thumb) : '')
  if (!source || !track) return null
  const share = duration ? Math.min(100, (time / duration) * 100) : 0
  const ring = 2 * Math.PI * 15
  const colours = (palette ? { '--pa': palette.accent, '--pa-ink': palette.ink } : {}) as CSSProperties
  return (
    <div className="player player-pill-bar hidden md:flex" style={colours} data-testid="player-header-pill">
      <button
        type="button"
        className="flex items-center gap-2 min-w-0 text-left"
        onClick={() => usePlayer.getState().openLibrary(source, 'queue')}
        aria-label={t('player.openLibrary')}
        title={`${track.title} · ${track.artist}`}
      >
        <span className="relative w-8 h-8 flex-none">
          <Cover src={mediaUrl(source.widgetId, track.thumb)} round className="absolute inset-[3px]" iconSize={12} />
          <svg className="absolute inset-0 -rotate-90" viewBox="0 0 34 34" aria-hidden="true">
            <circle cx="17" cy="17" r="15" fill="none" strokeWidth="2.5" className="player-bubble-track" />
            <circle cx="17" cy="17" r="15" fill="none" strokeWidth="2.5" className="player-bubble-fill" strokeDasharray={ring} strokeDashoffset={ring * (1 - share / 100)} strokeLinecap="round" />
          </svg>
        </span>
        <span className="min-w-0 leading-tight">
          <span className="block text-[12px] font-medium truncate max-w-44">{track.title}</span>
          <span className={`block text-[10px] truncate max-w-44 ${error ? 'text-bad' : 'text-muted'}`}>{error ? t('player.failed') : track.artist}</span>
        </span>
      </button>
      <PlayButton size={28} onPress={() => usePlayer.getState().toggle()} />
      <button type="button" className="player-icon h-7 w-7" onClick={() => usePlayer.getState().next()} aria-label={t('player.next')} title={t('player.next')}>
        <SkipForward size={13} fill="currentColor" />
      </button>
      <VolumeButton className="h-7 w-7" iconSize={13} />
    </div>
  )
}
