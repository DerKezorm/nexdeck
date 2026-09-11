/**
 * Putting tracks into playlists, and naming a playlist anew.
 *
 * Both write to the media server, on the account the card plays as. A smart
 * playlist is the server's to fill and is not offered as a place to add to.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ListMusic, Plus } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { mediaUrl } from '../../api/client'
import { playlists as lists, shelf, type MusicTrack } from '../../api/music'
import type { PlayerSource } from '../../stores/player'
import { Dialog } from '../ui'
import { Cover } from './parts'

/** Everything the library shows of a card's playlists is asked for again after a change. */
export function useForgetPlaylists(widgetId: number): (playlistId?: string) => Promise<void> {
  const queries = useQueryClient()
  return async (playlistId) => {
    await queries.invalidateQueries({ queryKey: ['music', widgetId, 'playlists'] })
    if (playlistId) await queries.invalidateQueries({ queryKey: ['music', widgetId, 'playlist', playlistId] })
  }
}

interface AddProps {
  source: PlayerSource
  tracks: MusicTrack[]
  /** What a new playlist is called unless somebody types something else. */
  suggestedName?: string
  onClose: () => void
  onDone: (text: string) => void
  onProblem: (text: string) => void
}

export function AddToPlaylistDialog({ source, tracks, suggestedName = '', onClose, onDone, onProblem }: AddProps) {
  const { t } = useTranslation()
  const forget = useForgetPlaylists(source.widgetId)
  const existing = useQuery({ queryKey: ['music', source.widgetId, 'playlists'], queryFn: () => shelf(source.widgetId, 'playlists'), staleTime: 60_000 })
  const [name, setName] = useState(suggestedName)
  const [busy, setBusy] = useState(false)
  const ids = tracks.map((track) => track.id)
  const editable = (existing.data?.playlists ?? []).filter((one) => one.editable !== false)

  const addTo = async (playlistId: string, title: string) => {
    setBusy(true)
    try {
      await lists.add(source.widgetId, playlistId, ids)
      await forget(playlistId)
      onDone(t('player.lists.added', { name: title }))
      onClose()
    } catch {
      onProblem(t('player.lists.failed'))
    } finally {
      setBusy(false)
    }
  }
  const create = async () => {
    const wanted = name.trim()
    if (!wanted) return
    setBusy(true)
    try {
      await lists.create(source.widgetId, wanted, ids)
      await forget()
      onDone(t('player.lists.created', { name: wanted }))
      onClose()
    } catch {
      onProblem(t('player.lists.failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onClose={onClose} title={t('player.lists.addTitle', { count: tracks.length })} size="sm">
      <form
        className="flex items-center gap-2 mb-4"
        onSubmit={(event) => {
          event.preventDefault()
          void create()
        }}
      >
        <input className="input flex-1" value={name} maxLength={200} placeholder={t('player.lists.namePlaceholder')} aria-label={t('player.lists.newPlaylist')} onChange={(event) => setName(event.target.value)} />
        <button type="submit" className="btn btn-accent" disabled={busy || !name.trim()}>
          <Plus size={14} /> {t('player.lists.create')}
        </button>
      </form>
      {existing.isPending ? (
        <p className="text-xs text-muted">{t('common.loading')}</p>
      ) : editable.length === 0 ? (
        <p className="text-xs text-muted">{t('player.lists.noEditable')}</p>
      ) : (
        <ul className="space-y-1">
          {editable.map((playlist) => (
            <li key={playlist.id}>
              <button type="button" className="player-row w-full" disabled={busy} onClick={() => void addTo(playlist.id, playlist.title)}>
                {playlist.thumb ? (
                  <Cover src={mediaUrl(source.widgetId, playlist.thumb)} className="w-9 h-9 flex-none" iconSize={14} />
                ) : (
                  <span className="w-9 h-9 flex-none grid place-items-center rounded-lg bg-accent-soft text-accent">
                    <ListMusic size={16} />
                  </span>
                )}
                <span className="min-w-0 flex-1 text-left">
                  <span className="block text-[13px] font-medium truncate">{playlist.title}</span>
                  {playlist.tracks !== null && <span className="block text-[11px] text-muted">{t('player.trackCount', { count: playlist.tracks })}</span>}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  )
}

export function RenamePlaylistDialog({ source, playlistId, current, onClose, onDone, onProblem }: { source: PlayerSource; playlistId: string; current: string; onClose: () => void; onDone: (text: string) => void; onProblem: (text: string) => void }) {
  const { t } = useTranslation()
  const forget = useForgetPlaylists(source.widgetId)
  const [name, setName] = useState(current)
  const [busy, setBusy] = useState(false)
  useEffect(() => setName(current), [current])
  const save = async () => {
    const wanted = name.trim()
    if (!wanted || wanted === current) return onClose()
    setBusy(true)
    try {
      await lists.rename(source.widgetId, playlistId, wanted)
      await forget(playlistId)
      onDone(t('player.lists.renamed'))
      onClose()
    } catch {
      onProblem(t('player.lists.failed'))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog
      open
      onClose={onClose}
      title={t('player.lists.rename')}
      size="sm"
      footer={
        <button type="button" className="btn btn-accent" disabled={busy || !name.trim()} onClick={() => void save()}>
          {t('common.save')}
        </button>
      }
    >
      <form
        onSubmit={(event) => {
          event.preventDefault()
          void save()
        }}
      >
        <input className="input" value={name} maxLength={200} autoFocus aria-label={t('player.lists.namePlaceholder')} onChange={(event) => setName(event.target.value)} />
      </form>
    </Dialog>
  )
}
