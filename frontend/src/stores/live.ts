import { create } from 'zustand'

import type { HealthView, WidgetData } from '../lib/types'

const SERIES_LIMIT = 120

interface LiveState {
  data: Record<number, WidgetData>
  series: Record<number, Record<string, number[]>>
  health: Record<number, Partial<HealthView>>
  logs: Record<number, { ts: number; line: string }[]>
  setSnapshot: (snapshot: Record<string, WidgetData>) => void
  applyWidget: (id: number, data: WidgetData) => void
  setSeries: (id: number, series: Record<string, [number, number][]>) => void
  applyHealth: (payload: { widget_id: number | null; ok: boolean; latency_ms: number; down_since: string | null; detail: string; bars?: (number | null)[] | null }) => void
  appendLog: (id: number, entry: { ts: number; line: string }, limit: number) => void
  setLogs: (id: number, entries: { ts: number; line: string }[]) => void
  forget: (id: number) => void
}

/** Live data of the open board: fed by the SSE stream, read by the cards. */
export const useLive = create<LiveState>((set) => ({
  data: {},
  series: {},
  health: {},
  logs: {},
  setSnapshot: (snapshot) =>
    set((state) => {
      const data = { ...state.data }
      const series = { ...state.series }
      for (const [key, value] of Object.entries(snapshot)) {
        const id = Number(key)
        data[id] = value
        if (value.metrics) series[id] = appendMetrics(series[id], value.metrics)
      }
      return { data, series }
    }),
  applyWidget: (id, value) =>
    set((state) => ({
      data: { ...state.data, [id]: value },
      series: value.metrics && !value.error ? { ...state.series, [id]: appendMetrics(state.series[id], value.metrics) } : state.series,
    })),
  setSeries: (id, incoming) =>
    set((state) => {
      const current: Record<string, number[]> = {}
      for (const [metric, points] of Object.entries(incoming)) {
        current[metric] = points.slice(-SERIES_LIMIT).map(([, value]) => value)
      }
      return { series: { ...state.series, [id]: { ...(state.series[id] ?? {}), ...current } } }
    }),
  applyHealth: (payload) =>
    set((state) => {
      if (payload.widget_id === null) return state
      const previous = state.health[payload.widget_id] ?? {}
      return {
        health: {
          ...state.health,
          [payload.widget_id]: {
            ...previous,
            last_ok: payload.ok,
            last_latency_ms: payload.latency_ms,
            down_since: payload.down_since,
            last_error: payload.ok ? '' : payload.detail,
            // Fresh bars ride along with every result; without them the tile
            // only moved when the board was loaded again.
            ...(Array.isArray(payload.bars) ? { bars: payload.bars } : {}),
          },
        },
      }
    }),
  appendLog: (id, entry, limit) =>
    set((state) => {
      const lines = [...(state.logs[id] ?? []), entry]
      return { logs: { ...state.logs, [id]: lines.slice(-limit) } }
    }),
  setLogs: (id, entries) => set((state) => ({ logs: { ...state.logs, [id]: entries } })),
  forget: (id) =>
    set((state) => {
      const data = { ...state.data }
      const series = { ...state.series }
      delete data[id]
      delete series[id]
      return { data, series }
    }),
}))

function appendMetrics(existing: Record<string, number[]> | undefined, metrics: Record<string, number>): Record<string, number[]> {
  const result: Record<string, number[]> = { ...(existing ?? {}) }
  for (const [name, value] of Object.entries(metrics)) {
    const points = [...(result[name] ?? []), value]
    result[name] = points.slice(-SERIES_LIMIT)
  }
  return result
}
