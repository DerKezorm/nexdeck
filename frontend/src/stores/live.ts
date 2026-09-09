import { create } from 'zustand'

import type { HealthView, WidgetData } from '../lib/types'

const SERIES_LIMIT = 120

/**
 * Is this answer older than the one already on screen?
 *
 * ⚠️ Two roads carry the same card: the stream pushes each answer as it is
 * made, and every board request brings a snapshot of the whole board along.
 * They arrive in whatever order the network feels like. Measured on
 * 09.09.2026: saving a card sent the new answer over the stream 120 ms later,
 * and a board request that had started 40 ms **before** the save answered
 * 20 ms after that with the state from before it. The older snapshot won,
 * and the card sat there with the settings from before the save until
 * something refreshed it. On a clock, whose next fetch is an hour away, that
 * means until F5, which is exactly how this was reported.
 *
 * An answer with no time of its own is treated as newer, because it is: an
 * error card carries no fetch time and must be able to replace a good one.
 */
function older(current: WidgetData | undefined, incoming: WidgetData): boolean {
  const before = current?.updated_at
  const now = incoming.updated_at
  return typeof before === 'number' && typeof now === 'number' && now < before
}

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
        if (older(data[id], value)) continue
        data[id] = value
        if (value.metrics) series[id] = appendMetrics(series[id], value.metrics)
      }
      return { data, series }
    }),
  applyWidget: (id, value) =>
    set((state) => {
      if (older(state.data[id], value)) return state
      return {
        data: { ...state.data, [id]: value },
        series: value.metrics && !value.error ? { ...state.series, [id]: appendMetrics(state.series[id], value.metrics) } : state.series,
      }
    }),
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
