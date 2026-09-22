import type { WidgetData } from './types'

/** The name a card's big number is kept under when its adapter declares no metric. */
export const HEADLINE = 'headline'

/**
 * What is written down for a card: the metrics its adapter declares, or else
 * its big number. The server's rule, `history.recorded` in
 * `backend/app/services/history.py`, applied to the answers the stream pushes,
 * so the line grows between two loads of the board the same way it was stored.
 */
export function recordedMetrics(data: WidgetData | undefined): Record<string, number> {
  if (!data || data.error) return {}
  if (data.metrics && Object.keys(data.metrics).length) return data.metrics
  const value = data.primary?.value
  return typeof value === 'number' && Number.isFinite(value) ? { [HEADLINE]: value } : {}
}
