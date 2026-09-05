/**
 * Camera: one picture large, never cropped. A snapshot that renews itself every few seconds,
 * or live video the server relays as HTTP-FLV and the browser plays through
 * Media Source Extensions. The player library loads only when a live card is
 * on the board, so the first visit stays as light as before.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { mediaUrl, videoUrl } from '../api/client'
import { tLabel } from '../i18n/texts'
import type { Status } from '../lib/types'
import type { RenderProps } from './renderers'

const STATUSES: Status[] = ['ok', 'warn', 'bad', 'unknown']

export function CameraCard({ widget, data }: RenderProps) {
  const { t } = useTranslation()
  const item = data?.items?.[0]
  const meta = data?.meta ?? {}
  const interval = Math.max(5, Number(meta.interval ?? 30) || 30)
  const wantsLive = meta.live === true
  // '' while live runs; 'unsupported' stays, 'error' is retried after half a minute.
  const [liveFailed, setLiveFailed] = useState<'' | 'unsupported' | 'error'>('')
  const failLive = useCallback((reason: 'unsupported' | 'error') => setLiveFailed(reason), [])
  useEffect(() => {
    setLiveFailed('')
  }, [widget.id, wantsLive])
  useEffect(() => {
    if (liveFailed !== 'error') return
    const timer = window.setTimeout(() => setLiveFailed(''), 30_000)
    return () => window.clearTimeout(timer)
  }, [liveFailed])
  if (!item) {
    return <div className="flex-1 flex items-center justify-center text-sm text-muted">{meta.empty ? tLabel(String(meta.empty)) : t('card.nothing')}</div>
  }
  const live = wantsLive && !liveFailed
  const status: Status = STATUSES.includes(item.status as Status) ? (item.status as Status) : 'unknown'
  const state = String(item.subtitle ?? '')
  const title = String(item.title ?? '')
  return (
    <div className="relative flex-1 min-h-0 overflow-hidden bg-black" data-testid="camera">
      {live ? <LiveVideo url={videoUrl(widget.id)} onFail={failLive} /> : <Snapshot url={mediaUrl(widget.id, String(item.art ?? ''))} interval={interval} title={title} />}
      <div className="absolute inset-x-0 bottom-0 flex items-center gap-2 px-2.5 py-1.5 bg-gradient-to-t from-black/75 to-transparent text-white">
        <span className="dot" data-status={status} />
        <span className="text-[12px] font-medium truncate">{title}</span>
        {state ? <span className="text-[11px] text-white/70 truncate">{tLabel(state)}</span> : null}
        {live ? <span className="ml-auto text-[10px] uppercase tracking-wide text-white/80" data-testid="live-badge">{t('card.liveVideo')}</span> : null}
        {wantsLive && liveFailed ? <span className="ml-auto text-[10px] text-white/70 truncate">{t(liveFailed === 'unsupported' ? 'card.liveUnsupported' : 'card.liveFailed')}</span> : null}
      </div>
    </div>
  )
}

/** A still picture, fetched through the server again every ``interval`` seconds; the browser keeps the old one until the new one is there. */
function Snapshot({ url, interval, title }: { url: string; interval: number; title: string }) {
  const { t } = useTranslation()
  const [stamp, setStamp] = useState(() => Date.now())
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    if (!url) return
    const timer = window.setInterval(() => setStamp(Date.now()), interval * 1000)
    return () => window.clearInterval(timer)
  }, [url, interval])
  if (!url) {
    return <div className="absolute inset-0 flex items-center justify-center text-3xl font-semibold text-white/30">{title.slice(0, 2).toUpperCase()}</div>
  }
  const src = `${url}${url.includes('?') ? '&' : '?'}t=${stamp}`
  return (
    <>
      <img src={src} alt="" className={`absolute inset-0 w-full h-full object-contain ${failed ? 'opacity-0' : ''}`} onLoad={() => setFailed(false)} onError={() => setFailed(true)} data-testid="snapshot" />
      {failed ? <div className="absolute inset-0 flex items-center justify-center text-sm text-white/70">{t('card.noImage')}</div> : null}
    </>
  )
}

/** Live video: the FLV bytes from the server, demuxed in the browser by mpegts.js. Anything that goes wrong hands the card back to snapshots. */
function LiveVideo({ url, onFail }: { url: string; onFail: (reason: 'unsupported' | 'error') => void }) {
  const video = useRef<HTMLVideoElement>(null)
  useEffect(() => {
    let player: { destroy: () => void } | null = null
    let cancelled = false
    void (async () => {
      try {
        const mpegts = (await import('mpegts.js')).default
        if (cancelled || !video.current) return
        if (!mpegts.isSupported()) {
          onFail('unsupported')
          return
        }
        // Video only: the card is muted anyway, and a camera's audio track is the usual reason a live picture stalls.
        const created = mpegts.createPlayer(
          { type: 'flv', isLive: true, url, hasAudio: false, hasVideo: true },
          // A second of buffer absorbs the jitter of a camera on Wi-Fi; chasing keeps the delay from growing past a few seconds.
          { enableWorker: false, enableStashBuffer: false, liveBufferLatencyChasing: true, liveBufferLatencyMaxLatency: 5, liveBufferLatencyMinRemain: 1, autoCleanupSourceBuffer: true },
        )
        created.on(mpegts.Events.ERROR, () => onFail('error'))
        created.attachMediaElement(video.current)
        created.load()
        player = created
        // A refused play() (autoplay policy, interrupted load) is not a broken stream.
        await Promise.resolve(created.play()).catch(() => undefined)
      } catch {
        onFail('error')
      }
    })()
    return () => {
      cancelled = true
      try {
        player?.destroy()
      } catch {
        // the player is already gone
      }
    }
  }, [url, onFail])
  return <video ref={video} muted autoPlay playsInline className="absolute inset-0 w-full h-full object-contain" data-testid="live" />
}
