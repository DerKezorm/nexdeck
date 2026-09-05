/**
 * The API client: one fetch wrapper, typed helpers, and the error shape the
 * server uses everywhere (``{code, message}``).
 */
export class ApiError extends Error {
  code: string
  status: number
  hint?: string

  constructor(status: number, code: string, message: string, hint?: string) {
    super(message)
    this.status = status
    this.code = code
    this.hint = hint
  }
}

const BASE = ((globalThis as { __NEXDECK_BASE__?: string }).__NEXDECK_BASE__ ?? '') + '/api/v1'

let kioskToken: string | null = null

export function setKioskToken(token: string | null) {
  kioskToken = token
}

export function kioskHeaders(): Record<string, string> {
  return kioskToken ? { 'X-Kiosk-Token': kioskToken } : {}
}

/**
 * An image of a widget's service, fetched through the server. Adapters hand
 * out ``proxy:/path`` so no token ever sits in an image address; anything
 * else (a full URL, a data URL) is used as it is.
 */
export function mediaUrl(widgetId: number, art: string | null | undefined): string {
  if (!art) return ''
  if (!art.startsWith('proxy:')) return art
  const params = new URLSearchParams({ path: art.slice(6) })
  if (kioskToken) params.set('kiosk', kioskToken)
  return `${BASE}/widgets/${widgetId}/image?${params.toString()}`
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown; raw?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>), ...kioskHeaders() }
  const method = (init.method ?? 'GET').toUpperCase()
  if (method !== 'GET' && method !== 'HEAD') headers['X-Nexdeck-Request'] = '1'
  let body = init.body
  if (init.json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(init.json)
  }
  const response = await fetch(BASE + path, { ...init, method, headers, body, credentials: 'same-origin' })
  if (response.status === 204) return undefined as T
  if (init.raw) return response as unknown as T
  const text = await response.text()
  let data: unknown
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = null
  }
  if (!response.ok) {
    const detail = (data as { detail?: { code?: string; message?: string; hint?: string } } | null)?.detail
    const flat = data as { code?: string; message?: string } | null
    throw new ApiError(response.status, detail?.code ?? flat?.code ?? 'error', detail?.message ?? flat?.message ?? `HTTP ${response.status}`, detail?.hint)
  }
  return data as T
}

export const get = <T>(path: string) => api<T>(path)
export const post = <T>(path: string, json?: unknown) => api<T>(path, { method: 'POST', json })
export const patch = <T>(path: string, json?: unknown) => api<T>(path, { method: 'PATCH', json })
export const put = <T>(path: string, json?: unknown) => api<T>(path, { method: 'PUT', json })
export const del = <T = void>(path: string, json?: unknown) => api<T>(path, { method: 'DELETE', json })

export async function upload(path: string, file: File, fields: Record<string, string> = {}): Promise<unknown> {
  const form = new FormData()
  form.append('file', file)
  const query = new URLSearchParams(fields).toString()
  return api(path + (query ? `?${query}` : ''), { method: 'POST', body: form })
}

/** Opens an EventSource on the stream endpoint, kiosk token included. */
export function streamUrl(board?: string): string {
  const params = new URLSearchParams()
  if (board) params.set('board', board)
  if (kioskToken) params.set('kiosk', kioskToken)
  const query = params.toString()
  return `${BASE}/stream${query ? `?${query}` : ''}`
}
