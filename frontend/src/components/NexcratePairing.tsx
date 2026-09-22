/**
 * "Pair with nexcrate": nexdeck asks nexcrate for a key, shows the code, and
 * the owner confirms it in nexcrate; the key then lands in the field by
 * itself. The same way nexbeat connects, and no key is ever copied by hand.
 *
 * nexdeck's server does the asking: nexcrate allows no calls from another
 * origin, and the pairing's secret must not reach the browser.
 */
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, post } from '../api/client'

interface Started {
  id: string
  code: string
  expires_at: string | null
  poll_seconds: number
}

type Phase = 'idle' | 'waiting' | 'done' | 'denied' | 'expired' | 'failed'

export function NexcratePairing({ url, insecure, onKey }: { url: string; insecure: boolean; onKey: (key: string) => void }) {
  const { t } = useTranslation()
  const [phase, setPhase] = useState<Phase>('idle')
  const [started, setStarted] = useState<Started | null>(null)
  const [message, setMessage] = useState('')
  const [now, setNow] = useState(() => Date.now())
  const timer = useRef<number>(0)
  useEffect(() => () => window.clearTimeout(timer.current), [])
  useEffect(() => {
    if (phase !== 'waiting') return
    const tick = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(tick)
  }, [phase])

  const ask = (pairing: Started) => {
    timer.current = window.setTimeout(() => {
      post<{ state: string; key?: string }>(`/nexcrate/pairing/${pairing.id}`, {})
        .then((answer) => {
          if (answer.state === 'confirmed' && answer.key) {
            onKey(answer.key)
            setPhase('done')
          } else if (answer.state === 'denied' || answer.state === 'expired') {
            setPhase(answer.state)
          } else ask(pairing)
        })
        .catch((failure) => {
          setMessage(failure instanceof ApiError ? failure.message : t('errors.network'))
          setPhase('failed')
        })
    }, Math.max(1, pairing.poll_seconds) * 1000)
  }

  const start = () => {
    setMessage('')
    post<Started>('/nexcrate/pairing', { url: url.trim(), insecure })
      .then((answer) => {
        setStarted(answer)
        setPhase('waiting')
        ask(answer)
      })
      .catch((failure) => {
        setMessage(failure instanceof ApiError ? failure.message : t('errors.network'))
        setPhase('failed')
      })
  }

  const stop = () => {
    window.clearTimeout(timer.current)
    setPhase('idle')
  }

  const left = started?.expires_at ? Math.max(0, Math.round((new Date(started.expires_at).getTime() - now) / 1000)) : null

  return (
    <div className="mt-2">
      {phase === 'waiting' && started ? (
        <div className="rounded-xl border border-line p-3">
          <p className="text-sm text-muted">{t('nexcrate.pairingText')}</p>
          <p aria-live="polite" className="my-3 inline-block rounded-xl border border-line px-6 py-3 font-mono text-3xl tracking-[0.3em] num">
            {started.code}
          </p>
          <p className="text-xs text-muted">
            {left !== null ? t('nexcrate.pairingWaiting', { time: `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}` }) : t('nexcrate.pairingWaitingPlain')}
          </p>
          <button type="button" className="btn mt-2" onClick={stop}>
            {t('common.cancel')}
          </button>
        </div>
      ) : (
        <>
          {phase === 'done' && <p className="text-sm text-ok mb-2" role="status">{t('nexcrate.pairingDone')}</p>}
          {(phase === 'denied' || phase === 'expired') && (
            <p className="text-sm text-bad mb-2" role="alert">
              {phase === 'denied' ? t('nexcrate.pairingDenied') : t('nexcrate.pairingExpired')}
            </p>
          )}
          {phase === 'failed' && message && (
            <p className="text-sm text-bad mb-2" role="alert">
              {message}
            </p>
          )}
          <button type="button" className="btn" disabled={!/^https?:\/\/./.test(url.trim())} onClick={start}>
            {phase === 'idle' ? t('nexcrate.pair') : t('nexcrate.pairAgain')}
          </button>
          {!/^https?:\/\/./.test(url.trim()) && <p className="text-[11px] text-faint mt-1">{t('nexcrate.urlFirst')}</p>}
        </>
      )}
    </div>
  )
}
