/**
 * The music player card.
 *
 * Four faces by size, measured rather than guessed, because a card two cells
 * tall and twelve wide wants something else than one six by six:
 *
 * - tiny: the cover fills the card, the play button sits on it
 * - strip: cover on the left, title, seek bar and buttons beside it
 * - stack: the playing track on top, the library underneath
 * - split: the playing track as a column on the left, the library beside it
 *
 * The card never holds the sound. It tells the app-wide player what to do, so
 * the music carries on when the board changes, and it lends the player its
 * cover's colour while it is on screen.
 */
import { Disc3, Library as LibraryIcon, ListMusic, Shuffle } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'

import { mediaUrl, post } from '../../api/client'
import type { MusicAlbum } from '../../api/music'
import { tLabel } from '../../i18n/texts'
import { currentTrack, usePlayer, type PlayerSource } from '../../stores/player'
import type { RenderProps } from '../renderers'
import { ServiceIcon } from '../ServiceIcon'
import { Library, playShelf, type Detail } from './Library'
import { Artwork, PlayButton, QualityChip, SeekBar, Transport, useBoxSize, useCoverColour, useOnScreen, VolumeButton, VolumeControl, type ArtTile } from './parts'

type Face = 'tiny' | 'strip' | 'stack' | 'split'

export function faceFor(width: number, height: number): Face {
  if (width < 280 || height < 190) return 'tiny'
  if (height < 300) return 'strip'
  if (width >= 620 && height >= 340) return 'split'
  return 'stack'
}

export function PlayerCard({ widget, data, canAct, editing }: RenderProps) {
  const { t, i18n } = useTranslation()
  const root = useRef<HTMLDivElement>(null)
  const { width, height } = useBoxSize(root)
  const face = faceFor(width || 400, height || 320)
  useOnScreen(root, widget.id)

  const features = useMemo(() => {
    const music = data?.meta?.music as { features?: unknown } | undefined
    return Array.isArray(music?.features) ? music.features.map(String) : []
  }, [data?.meta?.music])
  const source: PlayerSource = useMemo(
    () => ({ widgetId: widget.id, title: widget.title, icon: widget.icon, features }),
    [widget.id, widget.title, widget.icon, features],
  )
  const newest = useMemo(() => (data?.items ?? []) as unknown as MusicAlbum[], [data?.items])
  // Random covers, when the card is set to them, come apart from the newest: the newest stay the "New" tab.
  const picks = useMemo(() => {
    const music = data?.meta?.music as { picks?: unknown } | undefined
    return Array.isArray(music?.picks) ? (music.picks as MusicAlbum[]) : null
  }, [data?.meta?.music])
  const mine = usePlayer((state) => state.source?.widgetId === widget.id && state.queue.length > 0)
  const track = usePlayer((state) => (state.source?.widgetId === widget.id ? currentTrack(state) : undefined))
  const [problem, setProblem] = useState('')
  const [shuffling, setShuffling] = useState(false)

  // ⚠️ A card whose first read failed stays red until the collector tries
  // again, and after a failure that is up to half an hour away. Measured on
  // 11.09.2026: nexdeck started while the network was still down, the media
  // servers were back a minute later, and all four player cards stayed locked
  // behind their error. Somebody who may play here asks again every minute
  // while the card is on screen, so it opens up soon after the server is back.
  const failed = Boolean(data?.error)
  useEffect(() => {
    if (!failed || !canAct || editing) return
    const timer = window.setInterval(() => void post(`/widgets/${widget.id}/refresh`).catch(() => undefined), 60_000)
    return () => window.clearInterval(timer)
  }, [failed, canAct, editing, widget.id])

  const cover = track ? mediaUrl(widget.id, track.art) : mediaUrl(widget.id, newest[0]?.art ?? '')
  const palette = useCoverColour(track ? mediaUrl(widget.id, track.thumb) : '')
  const style = (palette ? { '--pa': palette.accent, '--pa-ink': palette.ink } : {}) as CSSProperties
  const locale = i18n.language
  const counts = (data?.secondary ?? [])
    .filter((row) => typeof row.value === 'number')
    .map((row) => `${Number(row.value).toLocaleString(locale)} ${tLabel(row.label)}`)
  const blocked = !canAct || Boolean(editing)

  const [good, setGood] = useState(false)
  const say = (text: string, worked = false) => {
    setProblem(text)
    setGood(worked)
    window.setTimeout(() => setProblem(''), 4000)
  }
  const sayDone = (text: string) => say(text, true)
  const shuffleAll = () => {
    setShuffling(true)
    void playShelf(source, 'shuffle', '', { shuffle: true })
      .catch(() => say(t('player.failed')))
      .finally(() => setShuffling(false))
  }
  // The big button: carries on with this card's queue, or starts a shuffle of the library.
  const press = () => (mine ? usePlayer.getState().toggle() : shuffleAll())
  const idleTitle = widget.title || t('player.title')

  const heading = track ? track.title : idleTitle
  const subheading = track ? [track.artist, track.album].filter(Boolean).join(' · ') : counts.slice(0, 2).join(' · ')

  const noAct = !canAct ? <p className="text-[11px] text-muted">{t('player.lookOnly')}</p> : null
  // The way into the library for a face too small to carry it. One door: the search is one of its tabs.
  const openLibrary = () => usePlayer.getState().openLibrary(source, 'new', newest)
  const doors = canAct ? <LibraryDoor onOpen={openLibrary} disabled={Boolean(editing)} /> : null

  // A pressed cover opens its album where the library is: inside the card
  // when the card carries one, beside the board when it does not.
  const inlineLibrary = face === 'split' || (face === 'stack' && height >= 400)
  const [opening, setOpening] = useState<{ detail: Detail; nonce: number } | null>(null)
  const openAlbum = (album: { id: string; title: string }) => {
    if (!album.id) return
    // Counted up, so pressing the same cover twice opens it twice.
    if (inlineLibrary) setOpening((old) => ({ detail: { kind: 'album', ...album }, nonce: (old?.nonce ?? 0) + 1 }))
    else usePlayer.getState().openLibrary(source, 'new', newest, album)
  }
  const playAlbum = (album: MusicAlbum) => void playShelf(source, 'album', album.id).catch(() => say(t('player.failed')))

  // ⚠️ Nothing playing is what is new, one cover or four as the card is set,
  // and each opens its album. A single cover beside the card's name read as
  // "this is playing" when nothing was, which is why four is the default.
  const count: 1 | 4 = widget.options?.idle_art === 'one' ? 1 : 4
  const pressable = !blocked
  const artwork = (className: string, iconSize: number, withPlay = true) => {
    const tiles: ArtTile[] = track
      ? [{ src: cover, title: track.album || track.title, onOpen: pressable && track.album_id ? () => openAlbum({ id: track.album_id, title: track.album }) : undefined }]
      : (picks?.length ? picks : newest).slice(0, count).map((album) => ({
          src: mediaUrl(widget.id, count === 1 ? album.art : album.thumb),
          title: album.title,
          onOpen: pressable ? () => openAlbum({ id: album.id, title: album.title }) : undefined,
          onPlay: pressable && withPlay ? () => playAlbum(album) : undefined,
        }))
    return <Artwork tiles={tiles} count={track ? 1 : count} className={className} iconSize={iconSize} />
  }

  return (
    <div ref={root} className={`player player-${face} relative flex-1 min-h-0 overflow-hidden`} style={style} data-testid="player" data-face={face}>
      <div className="player-backdrop" aria-hidden="true" style={cover ? { backgroundImage: `url("${cover}")` } : undefined} />
      <div className="player-veil" aria-hidden="true" />

      {face === 'tiny' && (
        <div className="relative h-full">
          <div className="absolute inset-0">
            {/* No play buttons on the covers here: the card's own button sits right on top of them. */}
            {track || newest.length ? artwork('absolute inset-0 !rounded-none', 40, false) : <Placeholder />}
          </div>
          <div className="absolute inset-x-0 bottom-0 p-3 pt-10 bg-gradient-to-t from-black/85 via-black/45 to-transparent text-white flex items-end gap-2">
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-semibold leading-tight truncate">{heading}</p>
              <p className="text-[11px] text-white/70 truncate">{subheading}</p>
            </div>
            <PlayButton size={40} onPress={press} disabled={blocked || shuffling} label={mine ? undefined : t('player.shuffleAll')} />
          </div>
          {canAct && (
            <button
              type="button"
              className="player-icon player-corner"
              onClick={openLibrary}
              disabled={Boolean(editing)}
              aria-label={t('player.openLibrary')}
              title={t('player.openLibrary')}
            >
              <LibraryIcon size={15} />
            </button>
          )}
          {mine && <TinyProgress />}
        </div>
      )}

      {face === 'strip' && (
        <div className="relative h-full flex items-center gap-4 p-3">
          {artwork('h-full aspect-square flex-none shadow-2xl', 36)}
          <div className="min-w-0 flex-1 flex flex-col justify-center gap-2">
            <Title icon={widget.icon} kicker={idleTitle} title={heading} subtitle={subheading} chip={track ? <QualityChip track={track} /> : null} />
            {mine ? (
              <>
                <SeekBar disabled={blocked} />
                <div className="flex items-center gap-3">
                  <Transport size={40} extras={width >= 460} disabled={blocked} />
                  <div className="ml-auto flex items-center gap-2">
                    {width >= 700 ? <VolumeControl /> : <VolumeButton />}
                    {doors}
                  </div>
                </div>
              </>
            ) : (
              <div className="flex items-end gap-2">
                <StartRow onShuffle={shuffleAll} busy={shuffling} disabled={blocked} note={noAct} />
                <div className="ml-auto">{doors}</div>
              </div>
            )}
          </div>
        </div>
      )}

      {face === 'stack' && (
        <div className="relative h-full flex flex-col">
          <div className="flex-none flex items-center gap-3.5 p-3 pb-2">
            {artwork('w-[min(34%,132px)] aspect-square flex-none shadow-2xl', 34)}
            <div className="min-w-0 flex-1 flex flex-col gap-2">
              <Title icon={widget.icon} kicker={idleTitle} title={heading} subtitle={subheading} chip={track ? <QualityChip track={track} /> : null} />
              <div className="flex items-center gap-2">
                {mine ? <Transport size={42} extras={width >= 400} disabled={blocked} /> : <StartRow onShuffle={shuffleAll} busy={shuffling} disabled={blocked} note={noAct} />}
                <div className="ml-auto flex items-center gap-2">
                  {/* The slider in full where the row has room, behind a button where it has not. */}
                  {mine && (width >= 540 ? <VolumeControl /> : <VolumeButton />)}
                  {/* Only while the library does not fit underneath. */}
                  {height < 400 && doors}
                </div>
              </div>
            </div>
          </div>
          {mine && (
            <div className="flex-none px-3 pb-1">
              <SeekBar disabled={blocked} />
            </div>
          )}
          {height >= 400 ? <Library source={source} newest={newest} canAct={canAct === true} onProblem={say} onNotice={sayDone} opening={opening} /> : null}
        </div>
      )}

      {face === 'split' && (
        <div className="relative h-full flex">
          <div className="flex-none w-[min(42%,340px)] flex flex-col p-4 pr-3 gap-3 min-h-0">
            <div className="flex items-center gap-2 text-[11px] text-muted min-w-0">
              <ServiceIcon icon={widget.icon} size={14} />
              <span className="truncate">{idleTitle}</span>
            </div>
            {/* ⚠️ A square as large as the room allows, in either direction. With
                aspect-square, w-full and max-h-full the cover came out wide and
                cropped whenever the column was wider than it was tall; measuring
                the room as a container and taking the smaller side keeps it square. */}
            <div className="flex-1 min-h-0 flex items-center justify-center [container-type:size]">
              {artwork('player-hero-cover aspect-square w-[min(100cqw,100cqh)] shadow-2xl', 56)}
            </div>
            <div className="flex-none min-w-0">
              <div className="flex items-center gap-2 min-w-0">
                <h3 className="text-[17px] font-semibold leading-tight truncate flex-1" title={heading}>{heading}</h3>
                {track && <QualityChip track={track} />}
              </div>
              <p className="text-[12px] text-muted truncate">{subheading}</p>
            </div>
            {mine ? (
              <div className="flex-none flex flex-col gap-2">
                <SeekBar disabled={blocked} />
                <Transport size={46} disabled={blocked} />
                <div className="flex justify-center"><VolumeControl /></div>
              </div>
            ) : (
              <StartRow onShuffle={shuffleAll} busy={shuffling} disabled={blocked} note={noAct} />
            )}
          </div>
          <div className="flex-1 min-w-0 flex flex-col pt-3 border-l border-line/60">
            <Library source={source} newest={newest} canAct={canAct === true} onProblem={say} onNotice={sayDone} opening={opening} />
          </div>
        </div>
      )}

      {problem && (
        <div className={`absolute left-1/2 bottom-3 -translate-x-1/2 z-10 player-toast ${good ? 'is-ok' : ''}`} role="status">
          {problem}
        </div>
      )}
    </div>
  )
}

function Title({ icon, kicker, title, subtitle, chip }: { icon: string; kicker: string; title: string; subtitle: string; chip: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted min-w-0">
        <ServiceIcon icon={icon} size={12} />
        <span className="truncate">{kicker}</span>
        {chip}
      </div>
      <h3 className="text-[15px] font-semibold leading-snug truncate mt-0.5" title={title}>{title}</h3>
      <p className="text-[12px] text-muted truncate">{subtitle}</p>
    </div>
  )
}

/** The shelf: opens the library beside the board, search included. */
function LibraryDoor({ onOpen, disabled }: { onOpen: () => void; disabled: boolean }) {
  const { t } = useTranslation()
  return (
    <button type="button" className="player-icon" onClick={onOpen} disabled={disabled} aria-label={t('player.openLibrary')} title={t('player.openLibrary')}>
      <LibraryIcon size={16} />
    </button>
  )
}

function StartRow({ onShuffle, busy, disabled, note }: { onShuffle: () => void; busy: boolean; disabled: boolean; note: React.ReactNode }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col gap-1.5 items-start min-w-0">
      {/* One line, always: a button whose words wrap is a button that looks broken. */}
      <button type="button" className="player-pill is-accent whitespace-nowrap" onClick={onShuffle} disabled={disabled || busy}>
        <Shuffle size={14} /> {busy ? t('common.loading') : t('player.shuffleAll')}
      </button>
      {note}
    </div>
  )
}

function Placeholder() {
  return (
    <div className="absolute inset-0 grid place-items-center bg-gradient-to-br from-accent/35 via-indigo-500/25 to-transparent text-white/80">
      <div className="flex flex-col items-center gap-1">
        <Disc3 size={36} strokeWidth={1.3} aria-hidden="true" />
        <ListMusic size={14} aria-hidden="true" className="opacity-60" />
      </div>
    </div>
  )
}

function TinyProgress() {
  const time = usePlayer((state) => state.time)
  const duration = usePlayer((state) => state.duration ?? currentTrack(state)?.duration ?? 0)
  const share = duration ? Math.min(100, (time / duration) * 100) : 0
  return (
    <div className="absolute inset-x-0 bottom-0 h-[3px] bg-white/15" aria-hidden="true">
      <div className="h-full player-fill" style={{ width: `${share}%` }} />
    </div>
  )
}

export default PlayerCard
