/**
 * The consent page of an MCP connector (``/connect``).
 *
 * A program such as Claude sends its person here through
 * ``/api/mcp/oauth/authorize`` with the request in the address. The person,
 * signed in, sees which program asks, where it returns to, and chooses the
 * level (up to the administrator's ceiling) and the boards, like when making
 * a key by hand. Allow or decline, the server answers with the address to go
 * back to, and the browser leaves for it.
 *
 * Outside the app's frame like the sign-in page, and loaded only when a
 * program sends somebody here. Signed out, it goes to the sign-in first and
 * comes back with the whole request (``?next=``, kept in the tab across a sign-in
 * at a provider).
 */
import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, useLocation } from 'react-router-dom'

import { ApiError, get, post } from '../api/client'
import { Bar } from '../components/AppBar'
import { BackgroundLayer } from '../components/BackgroundLayer'
import { BrandLogo } from '../components/Brand'
import { LanguagePill } from '../components/HeaderTools'
import { Spinner } from '../components/ui'
import type { McpLevel } from '../lib/mcp'
import { useMcpTexts } from '../lib/mcpTexts'
import { useAuth } from '../stores/auth'

interface ConsentInfo {
  client_name: string
  redirect_host: string
  max_level: McpLevel
  boards: { id: number; name: string }[]
}

/** What the server needs to see again with the answer: the request exactly as the program made it. */
const ASKED = ['client_id', 'redirect_uri', 'code_challenge', 'code_challenge_method', 'resource'] as const

/** The server's refusals the page puts in its own words; anything else shows the server's sentence. */
const PROBLEMS: Record<string, string> = {
  oauth_off: 'mcp.connect.error.off',
  oauth_client: 'mcp.connect.error.client',
  oauth_redirect: 'mcp.connect.error.redirect',
  oauth_pkce: 'mcp.connect.error.request',
  oauth_resource: 'mcp.connect.error.request',
  forbidden: 'mcp.connect.error.guest',
  session_required: 'mcp.connect.error.session',
  home_session: 'mcp.connect.error.session',
  too_many_keys: 'mcp.connect.error.tooMany',
}

/** Leaves for the program. Its own function so a test can watch it: jsdom cannot leave. */
export const leave = {
  to(address: string): void {
    window.location.assign(address)
  },
}

export function ConnectPage() {
  const { user, status, loading } = useAuth()
  const location = useLocation()
  if (loading) {
    return (
      <div className="min-h-full flex items-center justify-center">
        <Spinner />
      </div>
    )
  }
  if (status?.needs_setup) return <Navigate to="/setup" replace />
  if (!user) {
    const here = `/connect${location.search}`
    return <Navigate to={`/login?next=${encodeURIComponent(here)}`} replace state={{ from: here }} />
  }
  return <Consent search={location.search} />
}

function Consent({ search }: { search: string }) {
  const { t } = useTranslation()
  const ready = useMcpTexts()
  const username = useAuth((s) => s.user?.username ?? '')
  const params = useMemo(() => new URLSearchParams(search), [search])
  const asked = useMemo(() => {
    const query = new URLSearchParams()
    for (const name of ASKED) query.set(name, params.get(name) ?? '')
    return query
  }, [params])
  const info = useQuery({
    queryKey: ['mcp-consent', asked.toString()],
    queryFn: () => get<ConsentInfo>(`/mcp/consent?${asked.toString()}`),
    retry: false,
  })
  const [level, setLevel] = useState<McpLevel>('read')
  const [allBoards, setAllBoards] = useState(true)
  const [picked, setPicked] = useState<number[]>([])
  const [busy, setBusy] = useState(false)
  const [leaving, setLeaving] = useState(false)
  const [failure, setFailure] = useState('')

  const explain = (problem: unknown) => {
    if (!(problem instanceof ApiError)) return t('errors.network')
    const key = PROBLEMS[problem.code]
    return key ? t(key) : problem.message
  }

  const answer = async (allow: boolean) => {
    setBusy(true)
    setFailure('')
    try {
      const body = {
        ...Object.fromEntries(ASKED.map((name) => [name, params.get(name) ?? ''])),
        state: params.get('state') ?? '',
        allow,
        level,
        boards: allBoards ? null : picked,
      }
      const { redirect } = await post<{ redirect: string }>('/mcp/consent', body)
      setLeaving(true)
      leave.to(redirect)
    } catch (problem) {
      setFailure(explain(problem))
      setBusy(false)
    }
  }

  const levels: McpLevel[] = info.data?.max_level === 'act' ? ['read', 'act'] : ['read']
  const complete = allBoards || picked.length > 0

  let content: React.ReactNode
  if (!ready || info.isLoading) {
    content = (
      <div className="flex justify-center py-6">
        <Spinner />
      </div>
    )
  } else if (info.isError || !info.data) {
    content = (
      <p className="text-sm text-bad" role="alert">
        {explain(info.error)}
      </p>
    )
  } else if (leaving) {
    content = <p className="text-sm text-muted">{t('mcp.connect.sending')}</p>
  } else {
    const data = info.data
    content = (
      <>
        <h1 className="text-lg font-semibold mb-2">{t('mcp.connect.heading', { program: data.client_name })}</h1>
        <p className="text-sm text-muted mb-4">{t('mcp.connect.help')}</p>
        <dl className="text-sm grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 mb-4">
          <dt className="text-muted">{t('mcp.connect.program')}</dt>
          <dd className="break-all" data-testid="connect-program">{data.client_name}</dd>
          <dt className="text-muted">{t('mcp.connect.returnsTo')}</dt>
          <dd className="break-all font-mono" data-testid="connect-host">{data.redirect_host}</dd>
          <dt className="text-muted">{t('mcp.connect.account')}</dt>
          <dd className="break-all">{username}</dd>
        </dl>
        <fieldset className="mb-3">
          <legend className="block text-xs font-medium text-muted mb-1">{t('mcp.connect.level')}</legend>
          {levels.map((value) => (
            <label key={value} className="flex items-start gap-2 text-sm py-0.5">
              <input
                type="radio"
                name="connect-level"
                className="accent-[var(--nd-accent)] mt-1"
                checked={level === value}
                onChange={() => setLevel(value)}
              />
              <span>
                {t(`mcp.level.${value}`)}
                <span className="block text-xs text-muted">{t(`mcp.form.levelHelp.${value}`)}</span>
              </span>
            </label>
          ))}
        </fieldset>
        <fieldset className="mb-3">
          <legend className="block text-xs font-medium text-muted mb-1">{t('mcp.connect.boards')}</legend>
          <label className="flex items-center gap-2 text-sm py-0.5">
            <input type="radio" name="connect-boards" className="accent-[var(--nd-accent)]" checked={allBoards} onChange={() => setAllBoards(true)} />
            {t('mcp.form.boardsAll')}
          </label>
          <label className="flex items-center gap-2 text-sm py-0.5">
            <input type="radio" name="connect-boards" className="accent-[var(--nd-accent)]" checked={!allBoards} onChange={() => setAllBoards(false)} />
            {t('mcp.form.boardsPick')}
          </label>
          {!allBoards && (
            <ul className="ml-6 mt-1 space-y-0.5">
              {data.boards.map((board) => (
                <li key={board.id}>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="accent-[var(--nd-accent)] w-4 h-4"
                      checked={picked.includes(board.id)}
                      onChange={(event) => setPicked((current) => (event.target.checked ? [...current, board.id] : current.filter((id) => id !== board.id)))}
                    />
                    {board.name}
                  </label>
                </li>
              ))}
            </ul>
          )}
        </fieldset>
        <p className="text-xs text-muted mb-3">{t('mcp.connect.check')}</p>
        {failure && (
          <p className="text-sm text-bad mb-3" role="alert">
            {failure}
          </p>
        )}
        <div className="flex gap-2">
          <button className="btn btn-accent flex-1 h-9" type="button" disabled={busy || !complete} onClick={() => void answer(true)}>
            {t('mcp.connect.allow')}
          </button>
          <button className="btn flex-1 h-9" type="button" disabled={busy} onClick={() => void answer(false)}>
            {t('mcp.connect.decline')}
          </button>
        </div>
      </>
    )
  }

  return (
    <div className="min-h-full flex items-center justify-center p-6">
      <BackgroundLayer />
      <Bar bare spacer={false}>
        <span className="flex-1" />
        <LanguagePill signedIn />
      </Bar>
      <main className="glass rounded-2xl p-6 w-full max-w-md shadow-2xl" aria-label={ready ? t('mcp.connect.title') : undefined}>
        <div className="flex justify-center mb-5">
          <BrandLogo size={30} />
        </div>
        {content}
      </main>
    </div>
  )
}
