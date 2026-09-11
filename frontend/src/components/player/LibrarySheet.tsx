/**
 * The library as a sheet beside the board, for cards too small to carry it
 * and for the bar at the bottom.
 *
 * nexdeck's own sheet, the one the card settings open in, so it looks and
 * closes like everything else: Escape, the shade, the cross. On a phone it
 * takes the whole width.
 */
import { SkipForward } from 'lucide-react'
import { useCallback, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { mediaUrl } from '../../api/client'
import { currentTrack, usePlayer } from '../../stores/player'
import { ServiceIcon } from '../ServiceIcon'
import { Sheet } from '../ui'
import { Library } from './Library'
import { Cover, PlayButton, QualityChip, useCoverColour } from './parts'

export function LibrarySheet() {
  const { t } = useTranslation()
  const request = usePlayer((state) => state.library)
  const close = useCallback(() => usePlayer.getState().closeLibrary(), [])
  const [message, setMessage] = useState<{ text: string; worked: boolean } | null>(null)
  if (!request) return null
  const say = (text: string, worked = false) => {
    setMessage({ text, worked })
    window.setTimeout(() => setMessage(null), 4000)
  }
  return (
    <Sheet
      open
      wide
      onClose={close}
      title={
        <span className="flex items-center gap-2 min-w-0">
          <ServiceIcon icon={request.source.icon} size={16} />
          <span className="truncate">{t('player.library')}</span>
          <span className="text-muted font-normal truncate">· {request.source.title}</span>
        </span>
      }
      footer={<NowPlaying message={message} />}
    >
      <div className="player relative">
        {/* Keyed by what was asked for, so pressing the magnifier while the sheet is open lands on the search. */}
        <Library
          key={`${request.source.widgetId}:${request.tab}:${request.album?.id ?? ''}`}
          source={request.source}
          newest={request.newest}
          canAct
          onProblem={say}
          onNotice={(text) => say(text, true)}
          initialTab={request.tab}
          initialDetail={request.album ? { kind: 'album', ...request.album } : undefined}
          variant="sheet"
        />
      </div>
    </Sheet>
  )
}

/** What plays, at the foot of the sheet, so choosing the next thing does not mean losing the controls. */
function NowPlaying({ message }: { message: { text: string; worked: boolean } | null }) {
  const { t } = useTranslation()
  const source = usePlayer((state) => state.source)
  const track = usePlayer(currentTrack)
  const palette = useCoverColour(source && track ? mediaUrl(source.widgetId, track.thumb) : '')
  if (message) return <p className={`flex-1 text-[12px] ${message.worked ? 'text-ok' : 'text-bad'}`} role="status">{message.text}</p>
  if (!source || !track) return <p className="flex-1 text-[12px] text-muted">{t('player.pickSomething')}</p>
  const style = palette ? ({ '--pa': palette.accent, '--pa-ink': palette.ink } as React.CSSProperties) : undefined
  return (
    <div className="player flex-1 flex items-center gap-3 min-w-0" style={style}>
      <Cover src={mediaUrl(source.widgetId, track.thumb)} className="w-10 h-10 flex-none" iconSize={16} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 min-w-0">
          <p className="text-[13px] font-medium truncate">{track.title}</p>
          <QualityChip track={track} />
        </div>
        <p className="text-[11px] text-muted truncate">{track.artist}</p>
      </div>
      <PlayButton size={36} onPress={() => usePlayer.getState().toggle()} />
      <button type="button" className="player-icon" onClick={() => usePlayer.getState().next()} aria-label={t('player.next')} title={t('player.next')}>
        <SkipForward size={15} fill="currentColor" />
      </button>
    </div>
  )
}
