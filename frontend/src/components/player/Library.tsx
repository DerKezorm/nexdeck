/**
 * The library inside the player card: what is new, albums, artists, playlists,
 * a search and the queue, with one level of detail below each.
 *
 * Everything here is asked for when it is opened, never on the card's refresh:
 * a card nobody touches must not walk thirty thousand tracks every quarter hour.
 */
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { ArrowLeft, ListEnd, ListPlus, ListStart, Pencil, Search, Shuffle, Sparkles, Trash2, X } from 'lucide-react'
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { mediaUrl } from '../../api/client'
import { playlists as lists, QUALITIES, shelf, type MusicAlbum, type MusicArtist, type MusicPlaylist, type MusicTrack, type Quality, type Shelf } from '../../api/music'
import { currentTrack, usePlayer, type LibraryTab, type PlayerSource } from '../../stores/player'
import { Confirm } from '../ui'
import { Cover, Equalizer, formatTime } from './parts'
import { AddToPlaylistDialog, RenamePlaylistDialog, useForgetPlaylists } from './PlaylistDialogs'

export type Tab = LibraryTab
export type Detail = { kind: 'album' | 'artist' | 'playlist'; id: string; title: string }

/** What any list inside the library may ask of it, without handing callbacks down five levels. */
interface LibraryActions {
  addToPlaylist: (tracks: MusicTrack[], suggestedName?: string) => void
  notice: (text: string) => void
  problem: (text: string) => void
}

const Actions = createContext<LibraryActions>({ addToPlaylist: () => undefined, notice: () => undefined, problem: () => undefined })

interface Props {
  source: PlayerSource
  /** The newest albums the card already carries; without them the tab asks the server. */
  newest?: MusicAlbum[]
  canAct: boolean
  /** Hand the user a message for a moment. */
  onProblem: (text: string) => void
  /** The same for something that worked. */
  onNotice?: (text: string) => void
  initialTab?: Tab
  /** Something to open at once, such as the album of a cover that was pressed. */
  initialDetail?: Detail
  /** The same while the library is already open; a new `nonce` opens it again. */
  opening?: { detail: Detail; nonce: number } | null
  /** In a card the list scrolls under the tabs; in the sheet the sheet scrolls and the tabs stay on top. */
  variant?: 'card' | 'sheet'
}

export function Library({ source, newest, canAct, onProblem, onNotice, initialTab = 'new', initialDetail, opening, variant = 'card' }: Props) {
  const { t } = useTranslation()
  const mine = usePlayer((state) => state.source?.widgetId === source.widgetId && state.queue.length > 0)
  const [tab, setTab] = useState<Tab>(initialTab)
  const [trail, setTrail] = useState<Detail[]>(initialDetail ? [initialDetail] : [])
  const [adding, setAdding] = useState<{ tracks: MusicTrack[]; name: string } | null>(null)
  useEffect(() => {
    if (opening) setTrail([opening.detail])
  }, [opening])
  const detail = trail[trail.length - 1]
  const open = (next: Detail) => setTrail((old) => [...old, next])
  const back = () => setTrail((old) => old.slice(0, -1))
  const tabs: Tab[] = ['new', 'albums', 'artists', 'playlists', 'search', ...(mine ? (['queue'] as Tab[]) : [])]
  useEffect(() => {
    if (tab === 'queue' && !mine) setTab('new')
  }, [mine, tab])
  const sheet = variant === 'sheet'
  const notice = onNotice ?? onProblem
  const actions: LibraryActions = { addToPlaylist: (tracks, name = '') => setAdding({ tracks, name }), notice, problem: onProblem }

  return (
    <Actions.Provider value={actions}>
    {adding && <AddToPlaylistDialog source={source} tracks={adding.tracks} suggestedName={adding.name} onClose={() => setAdding(null)} onDone={notice} onProblem={onProblem} />}
    <div className={sheet ? 'flex flex-col' : 'flex-1 min-h-0 flex flex-col'}>
      <div
        // ⚠️ -top-4, not top-0: a sticky element stops at the inner edge of
        // the sheet's padding, and at top-0 the tabs sat sixteen pixels low,
        // over the first row of what they are the tabs of.
        className={`flex-none flex items-center gap-1 overflow-x-auto scrollbar-none ${sheet ? 'player-sheet-tabs sticky -top-4 z-10 -mx-4 -mt-4 px-4 pt-3 pb-2.5 mb-3' : 'px-3 pt-1 pb-2'}`}
        role="tablist"
        aria-label={t('player.library')}
      >
        {tabs.map((one) => (
          <button
            key={one}
            type="button"
            role="tab"
            aria-selected={tab === one && !detail}
            className={`player-tab ${tab === one && !detail ? 'is-active' : ''}`}
            onClick={() => {
              setTab(one)
              setTrail([])
            }}
          >
            {t(`player.tabs.${one}`)}
          </button>
        ))}
      </div>
      <div className={sheet ? '' : 'flex-1 min-h-0 scroll px-3 pb-3'} role="tabpanel">
        {!canAct ? (
          <p className="text-xs text-muted py-6 text-center">{t('player.lookOnly')}</p>
        ) : detail ? (
          <DetailView key={`${detail.kind}:${detail.id}`} source={source} detail={detail} onBack={back} onOpen={open} onProblem={onProblem} />
        ) : tab === 'new' ? (
          newest?.length ? <AlbumGrid source={source} albums={newest} onOpen={open} onProblem={onProblem} /> : <NewestTab source={source} onOpen={open} onProblem={onProblem} />
        ) : tab === 'albums' ? (
          <AlbumsTab source={source} onOpen={open} onProblem={onProblem} />
        ) : tab === 'artists' ? (
          <ArtistsTab source={source} onOpen={open} />
        ) : tab === 'playlists' ? (
          <PlaylistsTab source={source} onOpen={open} />
        ) : tab === 'search' ? (
          <SearchTab source={source} onOpen={open} onProblem={onProblem} />
        ) : (
          <QueueTab />
        )}
      </div>
    </div>
    </Actions.Provider>
  )
}

// -- the pieces of the lists ------------------------------------------------------

/** Fetch the tracks of an album or playlist and play them, from the first or mixed. */
export async function playShelf(source: PlayerSource, kind: 'album' | 'playlist' | 'artist' | 'shuffle' | 'mix', id: string, options: { shuffle?: boolean } = {}): Promise<void> {
  let tracks: MusicTrack[]
  if (kind === 'artist') {
    // An artist is its albums, one after the other, as the artist page lists them.
    const albums = (await shelf(source.widgetId, 'artist', { id })).albums.slice(0, 12)
    const each = await Promise.all(albums.map((album) => shelf(source.widgetId, 'album', { id: album.id })))
    tracks = each.flatMap((one) => one.tracks)
  } else {
    tracks = (await shelf(source.widgetId, kind, id ? { id } : {})).tracks
  }
  if (!tracks.length) throw new Error('empty')
  usePlayer.getState().play(source, tracks, 0, options)
}

function AlbumGrid({ source, albums, onOpen, onProblem, footer }: { source: PlayerSource; albums: MusicAlbum[]; onOpen: (detail: Detail) => void; onProblem: (text: string) => void; footer?: ReactNode }) {
  const { t } = useTranslation()
  if (!albums.length) return <p className="text-xs text-muted py-6 text-center">{t('player.nothingHere')}</p>
  return (
    <>
      <ul className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(104px, 1fr))' }}>
        {albums.map((album) => (
          <li key={album.id} className="player-tile group">
            <button type="button" className="block w-full text-left" onClick={() => onOpen({ kind: 'album', id: album.id, title: album.title })}>
              <Cover src={mediaUrl(source.widgetId, album.thumb)} className="aspect-square w-full shadow-lg" />
              <span className="block mt-1.5 text-[12px] font-medium leading-tight truncate">{album.title}</span>
              <span className="block text-[11px] text-muted truncate">{album.artist}</span>
            </button>
            <div className="player-tile-overlay">
              <button
                type="button"
                className="player-tile-play"
                aria-label={t('player.playAlbum', { name: album.title })}
                title={t('player.playAlbum', { name: album.title })}
                onClick={() => void playShelf(source, 'album', album.id).catch(() => onProblem(t('player.failed')))}
              >
                <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M8 5v14l11-7z" fill="currentColor" /></svg>
              </button>
            </div>
          </li>
        ))}
      </ul>
      {footer}
    </>
  )
}

function useSentinel(onVisible: () => void, active: boolean) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const node = ref.current
    if (!node || !active || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) onVisible()
    }, { rootMargin: '200px' })
    observer.observe(node)
    return () => observer.disconnect()
  }, [onVisible, active])
  return ref
}

function Loading() {
  return (
    <ul className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(104px, 1fr))' }} aria-hidden="true">
      {Array.from({ length: 8 }, (_, index) => (
        <li key={index}>
          <div className="aspect-square rounded-xl player-skeleton" />
          <div className="h-2.5 mt-2 w-3/4 rounded player-skeleton" />
        </li>
      ))}
    </ul>
  )
}

function Failed({ retry }: { retry: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="py-6 text-center text-xs text-muted">
      <p>{t('player.failed')}</p>
      <button type="button" className="btn btn-xs mt-2" onClick={retry}>
        {t('player.retry')}
      </button>
    </div>
  )
}

/** What is new, for a sheet opened from the bar, which has no card data to hand over. */
function NewestTab({ source, onOpen, onProblem }: { source: PlayerSource; onOpen: (detail: Detail) => void; onProblem: (text: string) => void }) {
  const newest = useQuery({ queryKey: ['music', source.widgetId, 'albums', 'newest', 'first'], queryFn: () => shelf(source.widgetId, 'albums', { sort: 'newest' }), staleTime: 5 * 60_000 })
  if (newest.isPending) return <Loading />
  if (newest.isError) return <Failed retry={() => void newest.refetch()} />
  return <AlbumGrid source={source} albums={newest.data.albums} onOpen={onOpen} onProblem={onProblem} />
}

function AlbumsTab({ source, onOpen, onProblem }: { source: PlayerSource; onOpen: (detail: Detail) => void; onProblem: (text: string) => void }) {
  const { t } = useTranslation()
  const [sort, setSort] = useState<'newest' | 'name' | 'random'>('name')
  const pages = useInfiniteQuery({
    queryKey: ['music', source.widgetId, 'albums', sort],
    queryFn: ({ pageParam }) => shelf(source.widgetId, 'albums', { sort, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last: Shelf) => last.next ?? undefined,
    staleTime: sort === 'random' ? 0 : 5 * 60_000,
  })
  const albums = useMemo(() => pages.data?.pages.flatMap((page) => page.albums) ?? [], [pages.data])
  const sentinel = useSentinel(() => void pages.fetchNextPage(), Boolean(pages.hasNextPage) && !pages.isFetchingNextPage)
  return (
    <>
      <div className="flex items-center gap-1 mb-2.5">
        {(['name', 'newest', 'random'] as const).map((one) => (
          <button key={one} type="button" className="btn btn-xs" aria-pressed={sort === one} onClick={() => setSort(one)}>
            {t(`player.sort.${one}`)}
          </button>
        ))}
        {pages.data?.pages[0]?.total ? <span className="ml-auto text-[11px] text-muted num">{pages.data.pages[0].total.toLocaleString()}</span> : null}
      </div>
      {pages.isPending ? <Loading /> : pages.isError ? <Failed retry={() => void pages.refetch()} /> : (
        <AlbumGrid source={source} albums={albums} onOpen={onOpen} onProblem={onProblem} footer={<div ref={sentinel} className="h-6" />} />
      )}
    </>
  )
}

function ArtistGrid({ source, artists, onOpen }: { source: PlayerSource; artists: MusicArtist[]; onOpen: (detail: Detail) => void }) {
  return (
    <ul className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(92px, 1fr))' }}>
      {artists.map((artist) => (
        <li key={artist.id}>
          <button type="button" className="block w-full text-center group" onClick={() => onOpen({ kind: 'artist', id: artist.id, title: artist.name })}>
            <Cover src={mediaUrl(source.widgetId, artist.thumb)} round className="aspect-square w-full shadow-lg transition-transform group-hover:scale-[1.03]" />
            <span className="block mt-1.5 text-[12px] font-medium truncate">{artist.name}</span>
          </button>
        </li>
      ))}
    </ul>
  )
}

function ArtistsTab({ source, onOpen }: { source: PlayerSource; onOpen: (detail: Detail) => void }) {
  const pages = useInfiniteQuery({
    queryKey: ['music', source.widgetId, 'artists'],
    queryFn: ({ pageParam }) => shelf(source.widgetId, 'artists', { offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last: Shelf) => last.next ?? undefined,
    staleTime: 5 * 60_000,
  })
  const artists = useMemo(() => pages.data?.pages.flatMap((page) => page.artists) ?? [], [pages.data])
  const sentinel = useSentinel(() => void pages.fetchNextPage(), Boolean(pages.hasNextPage) && !pages.isFetchingNextPage)
  if (pages.isPending) return <Loading />
  if (pages.isError) return <Failed retry={() => void pages.refetch()} />
  return (
    <>
      <ArtistGrid source={source} artists={artists} onOpen={onOpen} />
      <div ref={sentinel} className="h-6" />
    </>
  )
}

function PlaylistRows({ source, playlists, onOpen }: { source: PlayerSource; playlists: MusicPlaylist[]; onOpen: (detail: Detail) => void }) {
  const { t } = useTranslation()
  if (!playlists.length) return <p className="text-xs text-muted py-6 text-center">{t('player.nothingHere')}</p>
  return (
    <ul className="space-y-1">
      {playlists.map((playlist) => (
        <li key={playlist.id}>
          <button type="button" className="player-row w-full" onClick={() => onOpen({ kind: 'playlist', id: playlist.id, title: playlist.title })}>
            <Cover src={mediaUrl(source.widgetId, playlist.thumb)} className="w-10 h-10 flex-none" iconSize={16} />
            <span className="min-w-0 flex-1 text-left">
              <span className="flex items-center gap-1.5 min-w-0">
                <span className="block text-[13px] font-medium truncate">{playlist.title}</span>
                {playlist.editable === false && <span className="player-chip" title={t('player.lists.smartHint')}>{t('player.lists.smart')}</span>}
              </span>
              <span className="block text-[11px] text-muted truncate">
                {playlist.tracks !== null ? t('player.trackCount', { count: playlist.tracks }) : ''}
                {playlist.duration ? ` · ${formatTime(playlist.duration)}` : ''}
              </span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  )
}

function PlaylistsTab({ source, onOpen }: { source: PlayerSource; onOpen: (detail: Detail) => void }) {
  const answer = useQuery({ queryKey: ['music', source.widgetId, 'playlists'], queryFn: () => shelf(source.widgetId, 'playlists'), staleTime: 5 * 60_000 })
  if (answer.isPending) return <Loading />
  if (answer.isError) return <Failed retry={() => void answer.refetch()} />
  return <PlaylistRows source={source} playlists={answer.data.playlists} onOpen={onOpen} />
}

function SearchTab({ source, onOpen, onProblem }: { source: PlayerSource; onOpen: (detail: Detail) => void; onProblem: (text: string) => void }) {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const [words, setWords] = useState('')
  const field = useRef<HTMLInputElement>(null)
  useEffect(() => {
    const timer = window.setTimeout(() => setWords(text.trim()), 350)
    return () => window.clearTimeout(timer)
  }, [text])
  // ⚠️ After a tick, not with autoFocus: the sheet puts the focus on its first
  // button when it opens, and that ran after autoFocus and took it away again.
  useEffect(() => {
    const timer = window.setTimeout(() => field.current?.focus(), 30)
    return () => window.clearTimeout(timer)
  }, [])
  const found = useQuery({
    queryKey: ['music', source.widgetId, 'search', words],
    queryFn: () => shelf(source.widgetId, 'search', { q: words }),
    enabled: words.length >= 2,
    staleTime: 60_000,
  })
  return (
    <div className="space-y-4">
      <label className="flex items-center gap-2 input h-9">
        <Search size={15} className="text-faint flex-none" aria-hidden="true" />
        <input
          ref={field}
          type="search"
          className="flex-1 bg-transparent border-0 outline-none min-w-0 text-[13px]"
          value={text}
          placeholder={t('player.searchPlaceholder')}
          aria-label={t('player.tabs.search')}
          onChange={(event) => setText(event.target.value)}
        />
        {text && (
          <button type="button" className="player-icon h-6 w-6" onClick={() => setText('')} aria-label={t('player.clearSearch')}>
            <X size={13} />
          </button>
        )}
      </label>
      {words.length >= 2 && found.isPending && <Loading />}
      {found.isError && <Failed retry={() => void found.refetch()} />}
      {found.data && (
        <>
          {found.data.artists.length > 0 && (
            <section>
              <h4 className="player-heading">{t('player.tabs.artists')}</h4>
              <ArtistGrid source={source} artists={found.data.artists} onOpen={onOpen} />
            </section>
          )}
          {found.data.albums.length > 0 && (
            <section>
              <h4 className="player-heading">{t('player.tabs.albums')}</h4>
              <AlbumGrid source={source} albums={found.data.albums} onOpen={onOpen} onProblem={onProblem} />
            </section>
          )}
          {found.data.tracks.length > 0 && (
            <section>
              <h4 className="player-heading">{t('player.tracks')}</h4>
              <TrackRows source={source} tracks={found.data.tracks} showAlbum />
            </section>
          )}
          {!found.data.artists.length && !found.data.albums.length && !found.data.tracks.length && (
            <p className="text-xs text-muted py-6 text-center">{t('player.noHits', { words })}</p>
          )}
        </>
      )}
    </div>
  )
}

/** Rows of tracks; pressing one plays the list from there. */
export function TrackRows({ source, tracks, showAlbum = false, numbered = false, onRemove }: { source: PlayerSource; tracks: MusicTrack[]; showAlbum?: boolean; numbered?: boolean; onRemove?: (track: MusicTrack) => void }) {
  const { t } = useTranslation()
  const actions = useContext(Actions)
  const playing = usePlayer((state) => state.source?.widgetId === source.widgetId ? currentTrack(state)?.id : undefined)
  const moving = usePlayer((state) => state.state === 'playing')
  const discs = new Set(tracks.map((track) => track.disc ?? 1)).size > 1
  return (
    <ol className="space-y-0.5">
      {tracks.map((track, index) => {
        const current = playing === track.id
        return (
          <li key={`${track.id}-${index}`} className={`player-track group ${current ? 'is-current' : ''}`}>
            <button type="button" className="player-track-main" onClick={() => usePlayer.getState().play(source, tracks, index)} aria-current={current ? 'true' : undefined}>
              <span className="player-track-number num">
                {current ? <Equalizer playing={moving} /> : numbered ? (discs && track.disc ? `${track.disc}.${track.number ?? index + 1}` : track.number ?? index + 1) : <Cover src={mediaUrl(source.widgetId, track.thumb)} className="w-8 h-8" iconSize={14} />}
              </span>
              <span className="min-w-0 flex-1 text-left">
                <span className="block text-[13px] truncate">{track.title}</span>
                <span className="block text-[11px] text-muted truncate">{showAlbum ? [track.artist, track.album].filter(Boolean).join(' · ') : track.artist}</span>
              </span>
              <span className="num text-[11px] text-muted">{formatTime(track.duration)}</span>
            </button>
            <span className="player-track-more">
              <button type="button" className="player-icon h-7 w-7" onClick={() => usePlayer.getState().playNext(source, [track])} aria-label={t('player.playNext', { name: track.title })} title={t('player.playNextShort')}>
                <ListStart size={14} />
              </button>
              <button type="button" className="player-icon h-7 w-7" onClick={() => usePlayer.getState().enqueue(source, [track])} aria-label={t('player.enqueue', { name: track.title })} title={t('player.enqueueShort')}>
                <ListEnd size={14} />
              </button>
              <button type="button" className="player-icon h-7 w-7" onClick={() => actions.addToPlaylist([track])} aria-label={t('player.lists.addTrack', { name: track.title })} title={t('player.lists.addShort')}>
                <ListPlus size={14} />
              </button>
              {onRemove && track.entry && (
                <button type="button" className="player-icon h-7 w-7" onClick={() => onRemove(track)} aria-label={t('player.lists.removeTrack', { name: track.title })} title={t('player.lists.removeShort')}>
                  <X size={14} />
                </button>
              )}
            </span>
          </li>
        )
      })}
    </ol>
  )
}

function DetailView({ source, detail, onBack, onOpen, onProblem }: { source: PlayerSource; detail: Detail; onBack: () => void; onOpen: (detail: Detail) => void; onProblem: (text: string) => void }) {
  const { t } = useTranslation()
  const actions = useContext(Actions)
  const forget = useForgetPlaylists(source.widgetId)
  const answer = useQuery({ queryKey: ['music', source.widgetId, detail.kind, detail.id], queryFn: () => shelf(source.widgetId, detail.kind, { id: detail.id }), staleTime: 5 * 60_000 })
  const data = answer.data
  const tracks = data?.tracks ?? []
  const mixes = source.features.includes('mix')
  const editable = detail.kind === 'playlist' && data?.editable === true
  const [renaming, setRenaming] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const title = data?.title || detail.title
  const removeTrack = (track: MusicTrack) => {
    if (!track.entry) return
    void lists
      .remove(source.widgetId, detail.id, [track.entry])
      .then(() => forget(detail.id))
      .then(() => actions.notice(t('player.lists.removed')))
      .catch(() => onProblem(t('player.lists.failed')))
  }
  const deletePlaylist = () => {
    setDeleting(false)
    void lists
      .delete(source.widgetId, detail.id)
      .then(() => forget())
      .then(() => {
        actions.notice(t('player.lists.deleted'))
        onBack()
      })
      .catch(() => onProblem(t('player.lists.failed')))
  }
  const start = (options: { shuffle?: boolean } = {}) => {
    if (detail.kind === 'artist') {
      void playShelf(source, 'artist', detail.id, options).catch(() => onProblem(t('player.failed')))
      return
    }
    if (tracks.length) usePlayer.getState().play(source, tracks, 0, options)
  }
  const mix = () => void playShelf(source, 'mix', detail.id).catch(() => onProblem(t('player.failed')))
  return (
    <div>
      <button type="button" className="btn btn-xs mb-3" onClick={onBack}>
        <ArrowLeft size={13} /> {t('player.back')}
      </button>
      <header className="flex items-end gap-3 mb-4">
        <Cover src={mediaUrl(source.widgetId, data?.art ?? '')} round={detail.kind === 'artist'} className="w-24 h-24 @min-[520px]:w-32 @min-[520px]:h-32 flex-none shadow-2xl" />
        <div className="min-w-0 flex-1">
          <p className="text-[10px] uppercase tracking-wider text-muted">{t(`player.kind.${detail.kind}`)}</p>
          <h3 className="text-lg font-semibold leading-tight line-clamp-2">{data?.title || detail.title}</h3>
          {data?.subtitle ? <p className="text-[12px] text-muted truncate">{data.subtitle}</p> : null}
          <div className="flex flex-wrap items-center gap-1.5 mt-2">
            <button type="button" className="player-pill is-accent" onClick={() => start()} disabled={detail.kind !== 'artist' && !tracks.length}>
              <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true"><path d="M8 5v14l11-7z" fill="currentColor" /></svg>
              {t('player.play')}
            </button>
            <button type="button" className="player-pill" onClick={() => start({ shuffle: true })} disabled={detail.kind !== 'artist' && !tracks.length}>
              <Shuffle size={13} /> {t('player.shuffle')}
            </button>
            {mixes && (
              <button type="button" className="player-pill" onClick={mix}>
                <Sparkles size={13} /> {t('player.mix')}
              </button>
            )}
            {detail.kind !== 'artist' && tracks.length > 0 && (
              <button type="button" className="player-pill" onClick={() => actions.addToPlaylist(tracks, title)} title={t('player.lists.addAll')}>
                <ListPlus size={13} /> {t('player.lists.addShort')}
              </button>
            )}
            {editable && (
              <>
                <button type="button" className="player-icon" onClick={() => setRenaming(true)} aria-label={t('player.lists.rename')} title={t('player.lists.rename')}>
                  <Pencil size={14} />
                </button>
                <button type="button" className="player-icon btn-danger" onClick={() => setDeleting(true)} aria-label={t('player.lists.delete')} title={t('player.lists.delete')}>
                  <Trash2 size={14} />
                </button>
              </>
            )}
            {detail.kind === 'playlist' && data && !data.editable && <span className="player-chip" title={t('player.lists.smartHint')}>{t('player.lists.smart')}</span>}
          </div>
        </div>
      </header>
      {answer.isPending ? <Loading /> : answer.isError ? <Failed retry={() => void answer.refetch()} /> : detail.kind === 'artist' ? (
        <AlbumGrid source={source} albums={data?.albums ?? []} onOpen={onOpen} onProblem={onProblem} />
      ) : (
        <TrackRows source={source} tracks={tracks} numbered={detail.kind === 'album'} showAlbum={detail.kind === 'playlist'} onRemove={editable ? removeTrack : undefined} />
      )}
      {renaming && <RenamePlaylistDialog source={source} playlistId={detail.id} current={title} onClose={() => setRenaming(false)} onDone={actions.notice} onProblem={onProblem} />}
      <Confirm
        open={deleting}
        danger
        title={t('player.lists.deleteTitle', { name: title })}
        body={t('player.lists.deleteBody')}
        confirmLabel={t('player.lists.delete')}
        onCancel={() => setDeleting(false)}
        onConfirm={deletePlaylist}
      />
    </div>
  )
}

function QueueTab() {
  const { t } = useTranslation()
  const actions = useContext(Actions)
  const source = usePlayer((state) => state.source)
  const queue = usePlayer((state) => state.queue)
  const at = usePlayer((state) => state.at)
  const moving = usePlayer((state) => state.state === 'playing')
  const quality = usePlayer((state) => state.quality)
  const reduced = usePlayer((state) => state.reduced)
  const rows = useRef<HTMLOListElement>(null)
  useEffect(() => {
    rows.current?.querySelector('[aria-current="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [at])
  if (!source) return null
  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <label className="text-[11px] text-muted flex items-center gap-1.5">
          {t('player.quality.label')}
          <select
            className="bg-transparent border border-line rounded-md px-1.5 py-0.5 text-[11px] text-ink"
            value={quality}
            onChange={(event) => usePlayer.getState().setQuality(event.target.value as Quality)}
          >
            {QUALITIES.map((one) => (
              <option key={one} value={one}>
                {t(`player.quality.${one}`)}
              </option>
            ))}
          </select>
        </label>
        {reduced && <span className="text-[11px] text-warn truncate">{t('player.reduced')}</span>}
        <button type="button" className="btn btn-xs ml-auto" onClick={() => actions.addToPlaylist(queue)}>
          <ListPlus size={12} /> {t('player.lists.saveQueue')}
        </button>
        <button type="button" className="btn btn-xs" onClick={() => usePlayer.getState().stop()}>
          <Trash2 size={12} /> {t('player.clearQueue')}
        </button>
      </div>
      <ol ref={rows} className="space-y-0.5">
        {queue.map((track, index) => {
          const current = index === at
          return (
            <li key={`${track.id}-${index}`} className={`player-track group ${current ? 'is-current' : ''} ${index < at ? 'opacity-55' : ''}`}>
              <button type="button" className="player-track-main" onClick={() => usePlayer.getState().jump(index)} aria-current={current ? 'true' : undefined}>
                <span className="player-track-number">{current ? <Equalizer playing={moving} /> : <Cover src={mediaUrl(source.widgetId, track.thumb)} className="w-8 h-8" iconSize={14} />}</span>
                <span className="min-w-0 flex-1 text-left">
                  <span className="block text-[13px] truncate">{track.title}</span>
                  <span className="block text-[11px] text-muted truncate">{track.artist}</span>
                </span>
                <span className="num text-[11px] text-muted">{formatTime(track.duration)}</span>
              </button>
              <span className="player-track-more">
                <button type="button" className="player-icon h-7 w-7" onClick={() => usePlayer.getState().removeAt(index)} aria-label={t('player.remove', { name: track.title })} title={t('player.removeShort')}>
                  <X size={14} />
                </button>
              </span>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
