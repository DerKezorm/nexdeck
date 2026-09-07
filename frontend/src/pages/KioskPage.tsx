import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useParams } from 'react-router-dom'

import { get, openKioskSession, post } from '../api/client'
import type { BoardWithLive } from '../api/types'
import { BackgroundLayer } from '../components/BackgroundLayer'
import { BoardGrid } from '../components/BoardGrid'
import { tLabel } from '../i18n/texts'
import { Confirm, Spinner } from '../components/ui'
import { useStream } from '../hooks/useStream'
import type { Action, WidgetView } from '../lib/types'
import { useLive } from '../stores/live'

function withinWindow(from: string, to: string, now: Date): boolean {
  if (!from || !to) return false
  const minutes = now.getHours() * 60 + now.getMinutes()
  const [fh, fm] = from.split(':').map(Number)
  const [th, tm] = to.split(':').map(Number)
  const start = fh * 60 + fm
  const end = th * 60 + tm
  return start <= end ? minutes >= start && minutes < end : minutes >= start || minutes < end
}

/** The wall display: no bar, bigger cards, page cycling, night dimming. */
/** Well inside the day the cookie is good for, and cheap: one call. */
const RENEW_EVERY_MS = 6 * 60 * 60 * 1000

export function KioskPage() {
  const { t } = useTranslation()
  const { token = '' } = useParams()
  // The same reason as on the board page: a wall display runs for weeks, and
  // one subscription to the whole store repaints everything on every tick.
  const liveData = useLive((state) => state.data)
  const liveSeries = useLive((state) => state.series)
  const liveHealth = useLive((state) => state.health)
  const setSnapshot = useLive((state) => state.setSnapshot)
  const setSeriesFor = useLive((state) => state.setSeries)
  const [pageIndex, setPageIndex] = useState(0)
  const [dimmed, setDimmed] = useState(false)
  const [pending, setPending] = useState<{ widgetId: number; action: Action } | null>(null)
  const [admitted, setAdmitted] = useState(false)
  useEffect(() => {
    document.documentElement.dataset.theme = 'dark'
  }, [])
  useEffect(() => {
    // The token is handed in once and never appears in an address again.
    //
    // ⚠️ And handed in again every few hours. The cookie is good for a day,
    // the comment on the server says "renewed on the next load", and a wall
    // display does not load again: after twenty-four hours every fetch became
    // a 401 and nobody was standing in front of it to press F5. The token
    // itself does not change, so this is the same call on a timer.
    let current = true
    setAdmitted(false)
    if (!token) return
    const open = () =>
      openKioskSession(token).then(
        () => { if (current) setAdmitted(true) },
        () => { if (current) setAdmitted(false) },
      )
    void open()
    const timer = window.setInterval(() => void open(), RENEW_EVERY_MS)
    return () => {
      current = false
      window.clearInterval(timer)
    }
  }, [token])

  const board = useQuery({ queryKey: ['kiosk', token], queryFn: () => get<BoardWithLive>('/kiosk'), enabled: admitted, refetchInterval: 5 * 60_000 })
  const history = useQuery({ queryKey: ['kiosk-history', token, board.data?.slug], queryFn: () => get<Record<string, Record<string, [number, number][]>>>(`/boards/${board.data?.slug}/history`), enabled: Boolean(board.data) })
  const data = board.data
  useEffect(() => {
    if (data?.live) setSnapshot(data.live)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])
  useEffect(() => {
    if (!history.data) return
    for (const [id, series] of Object.entries(history.data)) setSeriesFor(Number(id), series)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [history.data])
  useStream({ board: data?.slug, enabled: Boolean(data), onBoardChanged: () => void board.refetch(), onConnected: () => void board.refetch() })

  const cycle = data?.kiosk?.cycle_seconds ?? 0
  useEffect(() => {
    if (!cycle || !data || data.pages.length < 2) return
    const id = window.setInterval(() => setPageIndex((i) => (i + 1) % data.pages.length), cycle * 1000)
    return () => window.clearInterval(id)
  }, [cycle, data])
  useEffect(() => {
    const check = () => setDimmed(withinWindow(data?.kiosk?.dim_from ?? '', data?.kiosk?.dim_to ?? '', new Date()))
    check()
    const id = window.setInterval(check, 30_000)
    return () => window.clearInterval(id)
  }, [data])

  const page = data?.pages[pageIndex % Math.max(1, data?.pages.length ?? 1)]
  const widgets: WidgetView[] = useMemo(() => (page?.widgets ?? []).map((w) => (w.health ? { ...w, health: { ...w.health, ...(liveHealth[w.id] ?? {}) } } : w)), [page, liveHealth])

  if (board.isLoading) {
    return (
      <div className="min-h-full flex items-center justify-center kiosk">
        <BackgroundLayer />
        <Spinner />
      </div>
    )
  }
  if (!data || !page) {
    return (
      <div className="min-h-full flex items-center justify-center p-6 kiosk">
        <BackgroundLayer />
        <div className="glass rounded-2xl p-6 text-center text-sm">{t('kiosk.invalid')}</div>
      </div>
    )
  }
  const canAct = Boolean(data.kiosk?.allow_actions)
  const run = (widgetId: number, action: Action) => void post(`/widgets/${widgetId}/actions/${action.id}`, { params: action.params ?? {} })
  return (
    <div className={`min-h-full kiosk ${dimmed ? 'dimmed' : ''} select-none`}>
      <BackgroundLayer background={data.background} />
      {data.pages.length > 1 && (
        <div className="fixed top-3 right-4 z-40 flex gap-1.5" aria-hidden="true">
          {data.pages.map((p, i) => (
            <button key={p.id} className={`w-2 h-2 rounded-full ${i === pageIndex % data.pages.length ? 'bg-accent' : 'bg-faint/50'}`} onClick={() => setPageIndex(i)} />
          ))}
        </div>
      )}
      <main className="max-w-[1800px] mx-auto px-4 pt-4 pb-6">
        <BoardGrid
          key={page.id}
          widgets={widgets}
          layouts={page.layouts}
          data={liveData}
          series={liveSeries}
          autoCompact={Boolean(data.settings?.compact)}
          canAct={canAct}
          onAction={(widgetId, action) => (action.confirm ? setPending({ widgetId, action }) : run(widgetId, action))}
        />
      </main>
      <Confirm
        open={pending !== null}
        // ⚠️ Translated, the way the board does it. The same button read
        // "Restart?" here and "Neu starten?" one screen away.
        title={pending ? `${tLabel(pending.action.label)}?` : ''}
        danger={pending?.action.danger}
        onCancel={() => setPending(null)}
        onConfirm={() => {
          if (pending) run(pending.widgetId, pending.action)
          setPending(null)
        }}
      />
    </div>
  )
}
