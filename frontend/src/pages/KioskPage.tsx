import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useParams } from 'react-router-dom'

import { get, post, setKioskToken } from '../api/client'
import type { BoardWithLive } from '../api/types'
import { BackgroundLayer } from '../components/BackgroundLayer'
import { BoardGrid } from '../components/BoardGrid'
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
export function KioskPage() {
  const { t } = useTranslation()
  const { token = '' } = useParams()
  const live = useLive()
  const [pageIndex, setPageIndex] = useState(0)
  const [dimmed, setDimmed] = useState(false)
  const [pending, setPending] = useState<{ widgetId: number; action: Action } | null>(null)
  useEffect(() => {
    setKioskToken(token)
    document.documentElement.dataset.theme = 'dark'
    return () => setKioskToken(null)
  }, [token])

  const board = useQuery({ queryKey: ['kiosk', token], queryFn: () => get<BoardWithLive>('/kiosk'), enabled: Boolean(token), refetchInterval: 5 * 60_000 })
  const history = useQuery({ queryKey: ['kiosk-history', token, board.data?.slug], queryFn: () => get<Record<string, Record<string, [number, number][]>>>(`/boards/${board.data?.slug}/history`), enabled: Boolean(board.data) })
  const data = board.data
  useEffect(() => {
    if (data?.live) live.setSnapshot(data.live)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])
  useEffect(() => {
    if (!history.data) return
    for (const [id, series] of Object.entries(history.data)) live.setSeries(Number(id), series)
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
  const widgets: WidgetView[] = useMemo(() => (page?.widgets ?? []).map((w) => (w.health ? { ...w, health: { ...w.health, ...(live.health[w.id] ?? {}) } } : w)), [page, live.health])

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
          data={live.data}
          series={live.series}
          canAct={canAct}
          onAction={(widgetId, action) => (action.confirm ? setPending({ widgetId, action }) : run(widgetId, action))}
        />
      </main>
      <Confirm
        open={pending !== null}
        title={pending ? `${pending.action.label}?` : ''}
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
