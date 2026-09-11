/**
 * The player card's library and sound, as the server hands them out.
 *
 * Covers are ``proxy:`` paths like every other picture of a service and go
 * through ``mediaUrl``. The sound goes through the server too, so the media
 * server's key never reaches the browser.
 */
import { del, get, patch, post } from './client'

const BASE = ((globalThis as { __NEXDECK_BASE__?: string }).__NEXDECK_BASE__ ?? '') + '/api/v1'

export type Quality = 'original' | 'high' | 'low'
export const QUALITIES: Quality[] = ['original', 'high', 'low']

export interface MusicTrack {
  id: string
  title: string
  artist: string
  album: string
  album_id: string
  artist_id: string
  duration: number | null
  number: number | null
  disc: number | null
  art: string
  thumb: string
  codec: string
  bit_depth: number | null
  sample_rate: number | null
  bitrate: number | null
  /** The track's place in a playlist, which is what taking it out names. Empty elsewhere. */
  entry?: string
}

export interface MusicAlbum {
  id: string
  title: string
  artist: string
  artist_id: string
  year: number | null
  tracks: number | null
  art: string
  thumb: string
}

export interface MusicArtist {
  id: string
  name: string
  art: string
  thumb: string
}

export interface MusicPlaylist {
  id: string
  title: string
  tracks: number | null
  duration: number | null
  art: string
  thumb: string
  /** False for a list the server fills by itself, such as Plex's smart playlists. */
  editable?: boolean
}

export interface Shelf {
  title: string
  subtitle: string
  art: string
  albums: MusicAlbum[]
  artists: MusicArtist[]
  playlists: MusicPlaylist[]
  tracks: MusicTrack[]
  total: number | null
  next: number | null
  /** For a playlist: whether its tracks can be taken out and it renamed or deleted. */
  editable?: boolean
}

/** Playlists on the media server, written on the account the card plays as. */
export const playlists = {
  create: (widgetId: number, name: string, trackIds: string[]) => post<MusicPlaylist>(`/widgets/${widgetId}/music/playlists`, { name, track_ids: trackIds }),
  add: (widgetId: number, playlistId: string, trackIds: string[]) =>
    post<{ ok: boolean }>(`/widgets/${widgetId}/music/playlists/${encodeURIComponent(playlistId)}/tracks`, { track_ids: trackIds }),
  remove: (widgetId: number, playlistId: string, entries: string[]) =>
    del<{ ok: boolean }>(`/widgets/${widgetId}/music/playlists/${encodeURIComponent(playlistId)}/tracks`, { entries }),
  rename: (widgetId: number, playlistId: string, name: string) => patch<{ ok: boolean }>(`/widgets/${widgetId}/music/playlists/${encodeURIComponent(playlistId)}`, { name }),
  delete: (widgetId: number, playlistId: string) => del(`/widgets/${widgetId}/music/playlists/${encodeURIComponent(playlistId)}`),
}

export type ShelfView = 'albums' | 'artists' | 'artist' | 'album' | 'playlists' | 'playlist' | 'search' | 'shuffle' | 'mix'

export function shelf(widgetId: number, view: ShelfView, params: { id?: string; q?: string; sort?: string; offset?: number } = {}): Promise<Shelf> {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') query.set(key, String(value))
  }
  const text = query.toString()
  return get<Shelf>(`/widgets/${widgetId}/music/${view}${text ? `?${text}` : ''}`)
}

/**
 * Where the browser fetches one track.
 *
 * ``start`` only means something for converted sound, which has no length and
 * cannot be skipped into by Range: the server asks the media server for the
 * track from that second instead.
 */
export function soundUrl(widgetId: number, trackId: string, options: { quality: Quality; formats: string[]; start?: number; hls?: boolean }): string {
  const query = new URLSearchParams({ quality: options.quality, formats: options.formats.join(',') })
  const track = encodeURIComponent(trackId)
  if (options.hls) return `${BASE}/widgets/${widgetId}/audio/${track}/hls/master.m3u8?${query.toString()}`
  if (options.start && options.start > 0) query.set('start', String(Math.floor(options.start)))
  return `${BASE}/widgets/${widgetId}/audio/${track}?${query.toString()}`
}
