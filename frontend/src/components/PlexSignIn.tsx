import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, get, post } from '../api/client'
import { Select } from './ui'

interface Pin {
  id: string
  code: string
  url: string
}

interface PlexServer {
  name: string
  owned: boolean
  machine_id: string
  urls: string[]
  access_token: string
}

const POLL_MS = 2000
const GIVE_UP_MS = 5 * 60 * 1000

/**
 * "Sign in with Plex": a PIN at plex.tv instead of a token copied out of an
 * XML page. The window opens synchronously on the click so popup blockers
 * let it through; the address is filled in once plex.tv has answered.
 * When the token arrives, the field gets it and the account's own server is
 * offered, local address first.
 */
export function PlexSignIn({ onFill }: { onFill: (values: Record<string, unknown>) => void }) {
  const { t } = useTranslation()
  const [phase, setPhase] = useState<'idle' | 'waiting' | 'done' | 'failed'>('idle')
  const [link, setLink] = useState('')
  const [username, setUsername] = useState('')
  const [servers, setServers] = useState<PlexServer[]>([])
  const [chosen, setChosen] = useState('')
  const [message, setMessage] = useState('')
  const timer = useRef<number>(0)
  useEffect(() => () => window.clearTimeout(timer.current), [])

  const pickServer = (server: PlexServer, url: string) => {
    setChosen(url)
    onFill({ url, token: server.access_token })
  }

  const finish = async (token: string, name: string) => {
    setUsername(name)
    onFill({ token })
    try {
      const found = await post<PlexServer[]>('/plex/servers', { token })
      setServers(found)
      const first = found.find((server) => server.owned && server.urls.length) ?? found.find((server) => server.urls.length)
      if (first) pickServer(first, first.urls[0])
      setPhase('done')
    } catch (failure) {
      setMessage(failure instanceof ApiError ? failure.message : t('errors.network'))
      setPhase('done')
    }
  }

  const poll = (pin: Pin, startedAt: number) => {
    timer.current = window.setTimeout(async () => {
      try {
        const answer = await get<{ token: string | null; username: string | null }>(`/plex/pin/${pin.id}?code=${encodeURIComponent(pin.code)}`)
        if (answer.token) {
          await finish(answer.token, answer.username ?? '')
          return
        }
      } catch (failure) {
        setMessage(failure instanceof ApiError ? failure.message : t('errors.network'))
        setPhase('failed')
        return
      }
      if (Date.now() - startedAt > GIVE_UP_MS) {
        setMessage(t('plex.timeout'))
        setPhase('failed')
        return
      }
      poll(pin, startedAt)
    }, POLL_MS)
  }

  const start = async () => {
    setMessage('')
    setServers([])
    // Opened right on the click, before any request: that is what popup blockers allow.
    const popup = window.open('', '_blank')
    try {
      const pin = await post<Pin>('/plex/pin')
      setLink(pin.url)
      if (popup) popup.location.href = pin.url
      setPhase('waiting')
      poll(pin, Date.now())
    } catch (failure) {
      popup?.close()
      setMessage(failure instanceof ApiError ? failure.message : t('errors.network'))
      setPhase('failed')
    }
  }

  return (
    <div className="rounded-xl border border-line p-3 mb-3 text-sm" data-testid="plex-signin">
      <div className="flex items-center gap-3">
        <button type="button" className="btn btn-accent whitespace-nowrap flex-none" onClick={() => void start()} disabled={phase === 'waiting'}>
          {t('plex.signIn')}
        </button>
        <span className="text-xs text-muted">{t('plex.help')}</span>
      </div>
      {phase === 'waiting' && (
        <p className="text-xs text-muted mt-2" role="status">
          {t('plex.waiting')}{' '}
          {link && (
            <a className="text-accent" href={link} target="_blank" rel="noreferrer">
              {t('plex.openLink')}
            </a>
          )}
        </p>
      )}
      {phase === 'done' && (
        <p className="text-xs text-ok mt-2" role="status">
          {t('plex.done', { name: username || 'Plex' })}
        </p>
      )}
      {phase === 'done' && servers.length > 0 && (
        <div className="mt-2">
          <label className="block text-xs font-medium text-muted mb-1" htmlFor="plex-server">
            {t('plex.server')}
          </label>
          <Select
            id="plex-server"
            value={chosen}
            onChange={(url) => {
              const server = servers.find((s) => s.urls.includes(url))
              if (server) pickServer(server, url)
            }}
            options={servers.flatMap((server) => server.urls.map((url) => ({ value: url, label: `${server.name}${server.owned ? '' : ` (${t('plex.shared')})`} · ${url}` })))}
          />
          <p className="text-[11px] text-faint mt-1">{t('plex.pickServer')}</p>
        </div>
      )}
      {phase === 'done' && servers.length === 0 && !message && (
        <p className="text-xs text-warn mt-2" role="status">
          {t('plex.noServers')}
        </p>
      )}
      {(phase === 'failed' || message) && message && (
        <p className="text-xs text-bad mt-2" role="alert">
          {message}
        </p>
      )}
    </div>
  )
}
