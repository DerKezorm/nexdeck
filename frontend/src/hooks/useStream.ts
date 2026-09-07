import { useEffect, useRef } from 'react'

import { ApiError, get, streamUrl } from '../api/client'
import type { WidgetData } from '../lib/types'
import { forgetEverything } from '../stores/auth'
import { useLive } from '../stores/live'
import { useNotices } from '../stores/notices'

interface Options {
  board?: string
  onBoardChanged?: () => void
  onLayout?: (payload: { page_id: number; layouts: Record<string, unknown[]> }) => void
  /** Called whenever the stream (re)connects: reload the snapshot, so nothing
   *  that changed between the board request and the subscription is missed. */
  onConnected?: () => void
  enabled?: boolean
}

/**
 * Keeps one EventSource open for the board and feeds the live store.
 * Reconnects with a small backoff; the browser does most of that itself.
 */
export function useStream({ board, onBoardChanged, onLayout, onConnected, enabled = true }: Options) {
  const callbacks = useRef({ onBoardChanged, onLayout, onConnected })
  useEffect(() => {
    callbacks.current = { onBoardChanged, onLayout, onConnected }
  })
  const applyWidget = useLive((s) => s.applyWidget)
  const applyHealth = useLive((s) => s.applyHealth)
  const appendLog = useLive((s) => s.appendLog)
  const pushNotice = useNotices((s) => s.push)

  useEffect(() => {
    if (!enabled) return
    let source: EventSource | null = null
    let closed = false
    let retry = 1000

    const connect = () => {
      if (closed) return
      source = new EventSource(streamUrl(board))
      source.addEventListener('open', () => {
        retry = 1000
      })
      // The server's first event; widgets fetched between the board request
      // and this moment are only in a fresh snapshot.
      source.addEventListener('hello', () => callbacks.current.onConnected?.())
      source.addEventListener('widget', (event) => {
        const payload = JSON.parse((event as MessageEvent).data) as { id: number; data: WidgetData }
        applyWidget(payload.id, payload.data)
      })
      source.addEventListener('health', (event) => {
        applyHealth(JSON.parse((event as MessageEvent).data))
      })
      source.addEventListener('board', () => callbacks.current.onBoardChanged?.())
      source.addEventListener('layout', (event) => callbacks.current.onLayout?.(JSON.parse((event as MessageEvent).data)))
      source.addEventListener('log', (event) => {
        const payload = JSON.parse((event as MessageEvent).data) as { widget_id: number; line: string; ts: number }
        appendLog(payload.widget_id, { ts: payload.ts, line: payload.line }, 400)
      })
      source.addEventListener('notice', (event) => {
        pushNotice(JSON.parse((event as MessageEvent).data))
      })
      source.onerror = () => {
        source?.close()
        if (closed) return
        // ⚠️ An EventSource does not hand over the status code, so a session
        // that has run out looks exactly like a server that is restarting: the
        // browser reconnected for ever, every attempt was refused, and the
        // person in front of it saw a board that quietly stopped moving. One
        // ordinary request settles which of the two it is, and a 401 there
        // signs the session out through the usual path.
        void get('/auth/me').catch((failure) => {
          if (failure instanceof ApiError && failure.status === 401) {
            closed = true
            forgetEverything()
          }
        })
        if (closed) return
        window.setTimeout(connect, retry)
        retry = Math.min(30000, retry * 2)
      }
    }
    connect()
    return () => {
      closed = true
      source?.close()
    }
  }, [board, enabled, applyWidget, applyHealth, appendLog, pushNotice])
}
