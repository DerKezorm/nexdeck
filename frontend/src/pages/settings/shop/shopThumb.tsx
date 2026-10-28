import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ThumbsUp } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, get, put } from '../../../api/client'
import { entryPath, type ShopEntry } from '../../../lib/cardShop'
import { safeUrl } from '../../../lib/safeUrl'
import { GithubSignIn, signInFailure } from '../share/GithubSignIn'

/** What the server knows of this administrator's thumb on an entry (`GET /workshop/entries/{author}/{slug}/thumb`). */
export interface ThumbState {
  signed_in: boolean
  on: boolean | null
}

export const thumbKey = (id: string) => ['workshop-thumb', id]
const thumbPath = (entry: ShopEntry) => `/workshop/entries/${entryPath(entry)}/thumb`

/** Whether an entry has a discussion to put a thumb on (the address in the catalog, as a link that is safe to follow). */
export function hasDiscussion(entry: ShopEntry): boolean {
  return safeUrl(entry.discussion) !== ''
}

/**
 * The thumb of an entry in nexdeck (W2): reading whether the administrator has put his thumb up (the page of one entry
 * only, never the tiles of the list) and setting it in his own GitHub name. The number that is shown stays the catalog's,
 * which the Workshop counts once a day; after a change the page says so.
 */
export function useThumb(entry: ShopEntry, read: boolean) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const known = useQuery({
    queryKey: thumbKey(entry.id),
    queryFn: () => get<ThumbState>(thumbPath(entry)),
    enabled: read && hasDiscussion(entry),
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 0,
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [counted, setCounted] = useState(false)
  const [signIn, setSignIn] = useState(false)
  const [wanted, setWanted] = useState(true)

  const readError = known.error instanceof ApiError && known.error.code === 'github_no_discussions' ? known.error : null
  const on = known.data?.on === true
  const signedOut = known.data?.signed_in === false

  const words = (failure: unknown) => (failure instanceof ApiError && failure.code === 'github_no_discussions' ? t('cards.shop.thumb.noRight') : signInFailure(t, failure))

  /** Sets or takes away the thumb. Returns `login` when GitHub has to be signed in to first, `failed` or `ok`. */
  const send = async (next: boolean): Promise<'ok' | 'login' | 'failed'> => {
    setBusy(true)
    setError('')
    try {
      const answer = await put<{ on: boolean }>(thumbPath(entry), { on: next })
      queryClient.setQueryData<ThumbState>(thumbKey(entry.id), { signed_in: true, on: answer.on })
      setCounted(true)
      setSignIn(false)
      return 'ok'
    } catch (failure) {
      if (failure instanceof ApiError && failure.code === 'github_login_needed') {
        setWanted(next)
        setSignIn(true)
        return 'login'
      }
      setError(words(failure))
      return 'failed'
    } finally {
      setBusy(false)
    }
  }

  return {
    on,
    busy,
    counted,
    signIn,
    /** The sentence for a missing right, from the reading or from a try. */
    note: error || (readError ? words(readError) : ''),
    /** The detail page: switches the thumb; when nobody is signed in the sign-in shows first and the switch follows it. */
    toggle: async () => {
      if (signedOut) {
        setWanted(!on)
        setSignIn(true)
        return
      }
      await send(!on)
    },
    /** The tile: sets the thumb (never takes it away). `login` means the detail page is the place to sign in. */
    set: () => send(true),
    /** The sign-in is done: the switch that was asked for goes out. */
    signedIn: async () => {
      setSignIn(false)
      await send(wanted)
    },
    close: () => setSignIn(false),
  }
}

/** The thumb as a button with the number; `aria-pressed` says whether this administrator has put his up. */
export function ThumbButton({ entry, thumb, onPress, tile }: { entry: ShopEntry; thumb: ReturnType<typeof useThumb>; onPress: () => void; tile?: boolean }) {
  const { t } = useTranslation()
  const label = t('cards.shop.thumbs', { count: entry.thumbs })
  return (
    <button
      type="button"
      aria-pressed={thumb.on}
      aria-label={label}
      title={label}
      disabled={thumb.busy}
      onClick={onPress}
      className={`inline-flex items-center gap-1 rounded ${tile ? 'relative z-10 text-[12px] text-muted hover:text-accent' : 'hover:text-accent'} ${thumb.on ? 'text-accent' : ''} focus-visible:outline-2 focus-visible:outline-accent`}
    >
      <ThumbsUp size={tile ? 12 : 13} aria-hidden="true" fill={thumb.on ? 'currentColor' : 'none'} />
      {entry.thumbs}
    </button>
  )
}

/** What stands under the thumb: that the number is counted once a day, a sentence that something failed, and the GitHub sign-in. */
export function ThumbNotes({ thumb, small }: { thumb: ReturnType<typeof useThumb>; small?: boolean }) {
  const { t } = useTranslation()
  return (
    <>
      {thumb.counted && (
        <p className="text-[11px] text-muted" role="status" data-testid="thumb-counted">
          {t('cards.shop.thumb.counted')}
        </p>
      )}
      {thumb.note && (
        <p className={`${small ? 'text-[11px]' : 'text-sm'} text-warn break-words`} role="alert" data-testid="thumb-note">
          {thumb.note}
        </p>
      )}
    </>
  )
}

/** The sign-in of the Card shop thumb: the same block as when sharing, then the thumb goes on. */
export function ThumbSignIn({ thumb }: { thumb: ReturnType<typeof useThumb> }) {
  const { t } = useTranslation()
  if (!thumb.signIn) return null
  return (
    <div className="mt-3" data-testid="thumb-signin">
      <GithubSignIn lead={t('cards.shop.thumb.signIn')} onSignedIn={() => void thumb.signedIn()} />
    </div>
  )
}
