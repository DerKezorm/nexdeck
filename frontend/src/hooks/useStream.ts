import { useEffect, useRef } from 'react'

import { streamUrl } from '../api/client'
import type { WidgetData } from '../lib/types'
import { useLive } from '../stores/live'
import { useNotices } from '../stores/notices'

interface Options {
  board?: string
  onBoardChanged?: () => void
  onLayout?: (payload: { page_id: number; layouts: Record<string, unknown[]> }) => void
  enabled?: boolean
}

/**
 * Keeps one EventSource open for the board and feeds the live store.
 * Reconnects with a small backoff; the browser does most of that itself.
 */
export function useStream({ board, onBoardChanged, onLayout, enabled = true }: Options) {
  const callbacks = useRef({ onBoardChanged, onLayout })
  useEffect(() => {
    callbacks.current = { onBoardChanged, onLayout }
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
