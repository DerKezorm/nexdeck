import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, del, get, post } from '../../../api/client'
import { Spinner } from '../../../components/ui'
import { GITHUB_KEY, SUBMISSIONS_KEY, type GithubPending, type GithubState, type PollAnswer } from '../../../lib/cardShare'

/** Whether the administrator is signed in to GitHub, as whom and until when (`GET /workshop/github`). Never asks GitHub. */
export function useGithub(enabled = true) {
  return useQuery({ queryKey: GITHUB_KEY, queryFn: () => get<GithubState>('/workshop/github'), enabled, staleTime: 30_000, retry: false })
}

/** The words for something that went wrong with the sign-in; the server's English when the interface has none. */
export function signInFailure(t: (key: string, options?: Record<string, unknown>) => string, failure: unknown): string {
  if (!(failure instanceof ApiError)) return t('errors.network')
  return t(`cards.share.errors.${failure.code}`, { defaultValue: failure.message })
}

type Phase = 'idle' | 'starting' | 'waiting' | 'expired' | 'denied'

/**
 * Signing in to GitHub with a code (KARTEN-16 AC-3, EC-1): the code and a link, a wait that asks the server in the
 * rhythm it names (the server asks GitHub no faster than GitHub allows), a new code when it ran out.
 *
 * `onSignedIn` is called once when GitHub has said yes.
 */
export function GithubSignIn({ onSignedIn, lead }: { onSignedIn?: () => void; lead?: string }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const known = useGithub()
  const [phase, setPhase] = useState<Phase>('idle')
  const [code, setCode] = useState<GithubPending | null>(null)
  const [error, setError] = useState('')
  const alive = useRef(true)
  const done = useRef(onSignedIn)
  useEffect(() => {
    done.current = onSignedIn
  })

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  // A code that is waiting already (the page was opened again): carry on with it.
  useEffect(() => {
    const waiting = known.data?.pending
    if (phase === 'idle' && waiting) {
      setCode(waiting)
      setPhase('waiting')
    }
  }, [known.data, phase])

  // The wait: ask the server when GitHub's interval is over. Each answer says how long to wait for the next.
  useEffect(() => {
    if (phase !== 'waiting' || !code) return
    let timer: ReturnType<typeof setTimeout> | undefined
    let stopped = false
    const ask = async (seconds: number) => {
      timer = setTimeout(async () => {
        if (stopped) return
        try {
          const answer = await post<PollAnswer>('/workshop/github/login/poll')
          if (stopped || !alive.current) return
          if (answer.status === 'pending') return void ask(answer.interval)
          if (answer.status === 'signed_in') {
            queryClient.setQueryData(GITHUB_KEY, { signed_in: true, login: answer.login, github_id: answer.github_id, until: answer.until, pending: null })
            await queryClient.invalidateQueries({ queryKey: SUBMISSIONS_KEY })
            setPhase('idle')
            setCode(null)
            done.current?.()
          } else if (answer.status === 'denied') setPhase('denied')
          else setPhase('expired')
        } catch (failure) {
          if (stopped || !alive.current) return
          setError(signInFailure(t, failure))
          setPhase('idle')
          setCode(null)
        }
      }, Math.max(1, seconds) * 1000)
    }
    void ask(code.interval)
    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
    }
  }, [phase, code, queryClient, t])

  const start = async () => {
    setError('')
    setPhase('starting')
    try {
      const fresh = await post<GithubPending>('/workshop/github/login')
      setCode(fresh)
      setPhase('waiting')
    } catch (failure) {
      setError(signInFailure(t, failure))
      setPhase('idle')
    }
  }

  return (
    <div className="rounded-xl border border-line p-4 grid gap-3 justify-items-start" data-testid="github-signin">
      <h3 className="font-semibold text-[15px]">{t('cards.share.signIn.title')}</h3>
      <p className="text-sm text-muted">{lead ?? t('cards.share.signIn.lead')}</p>
      {(phase === 'idle' || phase === 'starting') && (
        <button type="button" className="btn btn-accent" disabled={phase === 'starting'} onClick={() => void start()}>
          {phase === 'starting' && <Spinner />}
          {t('cards.share.signIn.start')}
        </button>
      )}
      {phase === 'waiting' && code && (
        <div className="grid gap-2 justify-items-start" aria-live="polite">
          <p className="text-sm">{t('cards.share.signIn.code')}</p>
          <p className="font-mono text-2xl tracking-widest select-all break-all" data-testid="github-code">
            {code.user_code}
          </p>
          <a className="btn" href={code.verification_uri} target="_blank" rel="noopener noreferrer">
            {t('cards.share.signIn.open')}
          </a>
          <p className="text-sm text-muted" role="status">
            {t('cards.share.signIn.waiting')}
          </p>
        </div>
      )}
      {(phase === 'expired' || phase === 'denied') && (
        <div className="grid gap-2 justify-items-start" role="alert">
          <p className="text-sm text-bad">{t(phase === 'expired' ? 'cards.share.signIn.expired' : 'cards.share.signIn.denied')}</p>
          <button type="button" className="btn btn-accent" onClick={() => void start()}>
            {t('cards.share.signIn.newCode')}
          </button>
        </div>
      )}
      {error && (
        <p className="text-sm text-bad break-words" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}

/** "Signed in to GitHub as …", until when, and the way out (KARTEN-16 AC-4). */
export function GithubSignedIn({ state, onSignedOut }: { state: GithubState; onSignedOut?: () => void }) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const [busy, setBusy] = useState(false)
  const out = async () => {
    setBusy(true)
    try {
      await del('/workshop/github')
      queryClient.setQueryData(GITHUB_KEY, { signed_in: false, login: null, github_id: null, until: null, pending: null })
      await queryClient.invalidateQueries({ queryKey: SUBMISSIONS_KEY })
      onSignedOut?.()
    } finally {
      setBusy(false)
    }
  }
  const until = state.until ? new Date(state.until).toLocaleDateString(i18n.language) : ''
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm" data-testid="github-signed-in">
      <span>{t('cards.share.signedInAs', { login: state.login ?? '' })}</span>
      {until && <span className="text-muted">{t('cards.share.signIn.until', { date: until })}</span>}
      <button type="button" className="btn btn-flat" disabled={busy} onClick={() => void out()}>
        {t('cards.share.signIn.signOut')}
      </button>
    </div>
  )
}
