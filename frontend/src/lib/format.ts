export function formatValue(value: number | string | null | undefined, unit = ''): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'number') {
    const text = Math.abs(value) >= 1000 ? Math.round(value).toLocaleString() : trimNumber(value)
    return unit ? `${text}${unit.startsWith('/') || unit.startsWith(' ') ? ' ' : ''}${unit}` : text
  }
  return unit ? `${value} ${unit}` : String(value)
}

function trimNumber(value: number): string {
  if (Number.isInteger(value)) return String(value)
  return value.toFixed(Math.abs(value) < 10 ? 1 : 0)
}

export function timeAgo(seconds: number | null | undefined, now = Date.now() / 1000): string {
  if (!seconds) return ''
  const delta = Math.max(0, Math.round(now - seconds))
  if (delta < 60) return `${delta}s`
  if (delta < 3600) return `${Math.round(delta / 60)}m`
  if (delta < 86400) return `${Math.round(delta / 3600)}h`
  return `${Math.round(delta / 86400)}d`
}

export function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value))
}

/** Where service logos come from: the server proxies and caches them. */
export function iconUrl(icon: string | undefined | null): string | null {
  if (!icon) return null
  if (icon.startsWith('http') || icon.startsWith('/') || icon.startsWith('data:')) return icon
  const base = (globalThis as { __NEXDECK_ICON_BASE__?: string }).__NEXDECK_ICON_BASE__ ?? '/api/v1/icons/'
  return `${base}${encodeURIComponent(icon)}.svg`
}
