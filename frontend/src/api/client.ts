/**
 * The API client: one fetch wrapper, typed helpers, and the error shape the
 * server uses everywhere (``{code, message}``).
 */
export class ApiError extends Error {
  code: string
  status: number
  hint?: string
  /** Everything else the server put in the detail: a ticket, a count, a name. */
  detail: Record<string, unknown>

  constructor(status: number, code: string, message: string, hint?: string, detail: Record<string, unknown> = {}) {
    super(message)
    this.status = status
    this.code = code
    this.hint = hint
    this.detail = detail
  }
}

const BASE = ((globalThis as { __NEXDECK_BASE__?: string }).__NEXDECK_BASE__ ?? '') + '/api/v1'

/** An address the server handed out (a profile picture, an upload), as the browser must call it. */
export function serverUrl(path: string): string {
  return ((globalThis as { __NEXDECK_BASE__?: string }).__NEXDECK_BASE__ ?? '') + path
}

/**
 * Opens the kiosk session. The token goes to the server once and comes back
 * as a signed, short-lived cookie.
 *
 * It used to be kept here and appended to every image, video and event
 * address, because none of those can set a header. A wall display makes a few
 * thousand such requests a day, and each one wrote the token into the reverse
 * proxy log, where it stays as long as the log does.
 */
export async function openKioskSession(token: string): Promise<void> {
  await api('/kiosk/session', { method: 'POST', json: { token } })
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
  return `${BASE}/widgets/${widgetId}/image?${params.toString()}`
}

/** The relayed live video of a camera widget. The kiosk cookie rides along by itself. */
export function videoUrl(widgetId: number): string {
  return `${BASE}/widgets/${widgetId}/stream`
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown; raw?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) }
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
    const { code, message, hint, detail } = readFailure(data, response.status)
    const flat = { code, message }
    // ⚠️ The one error the app cannot usefully show on the page it is on. The
    // installation wants a second factor from every account and this one has
    // none, so every other address answers 403 until it does. Without this the
    // app just breaks quietly, which is what the setting did for months.
    if (flat.code === 'two_factor_setup_required' && !window.location.pathname.startsWith('/settings')) {
      window.location.assign('/settings?factor=required')
    }
    throw new ApiError(response.status, code, message, hint, detail)
  }
  return data as T
}

/**
 * Ask for a file and hand it to the browser as a download.
 *
 * ⚠️ A POST, not a link. The one caller is the backup archive, whose password
 * travels in the body: in a query string it would sit in every reverse proxy
 * log between here and the server.
 */
/**
 * One reading of a failed answer, whatever shape it arrives in.
 *
 * ⚠️ There were four of them, and none knew what FastAPI sends for a body it
 * rejects: a 422 carries ``detail`` as a **list** of field errors, so every
 * one of the four fell through to "HTTP 422" and the person saw a number
 * instead of which field was wrong. The shapes in the wild are three:
 * nexdeck's own ``{detail: {code, message}}``, the flat ``{code, message}``
 * the 404 handler sends for an address that does not exist, and FastAPI's
 * validation list.
 */
export function readFailure(
  data: unknown,
  status: number,
): { code: string; message: string; hint?: string; detail: Record<string, unknown> } {
  const body = (data ?? {}) as { detail?: unknown; code?: string; message?: string }
  const detail = body.detail

  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const own = detail as { code?: string; message?: string; hint?: string }
    return {
      code: own.code ?? 'error',
      message: own.message ?? `HTTP ${status}`,
      hint: own.hint,
      detail: own as Record<string, unknown>,
    }
  }

  if (Array.isArray(detail)) {
    // FastAPI: [{loc: ['body', 'name'], msg: '...', type: '...'}]
    const said = detail
      .map((entry) => {
        const one = entry as { loc?: unknown[]; msg?: string }
        const field = Array.isArray(one.loc) ? one.loc.filter((part) => part !== 'body').join('.') : ''
        return field ? `${field}: ${one.msg ?? ''}`.trim() : (one.msg ?? '')
      })
      .filter(Boolean)
    return {
      code: 'invalid',
      message: said.length ? said.join('; ') : `HTTP ${status}`,
      detail: { fields: detail },
    }
  }

  if (typeof detail === 'string' && detail) {
    return { code: 'error', message: detail, detail: {} }
  }

  return {
    code: body.code ?? 'error',
    message: body.message ?? `HTTP ${status}`,
    detail: {},
  }
}

export async function downloadPost(path: string, filename: string, json: unknown): Promise<void> {
  const response = await api<Response>(path, { method: 'POST', json, raw: true })
  if (!response.ok) {
    const text = await response.text()
    let data: { detail?: { code?: string; message?: string } } | null
    try {
      data = text ? JSON.parse(text) : null
    } catch {
      data = null
    }
    const failure = readFailure(data, response.status)
    throw new ApiError(response.status, failure.code, failure.message, failure.hint, failure.detail)
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
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

/** Opens an EventSource on the stream endpoint. A kiosk is known by its cookie. */
export function streamUrl(board?: string): string {
  const params = new URLSearchParams()
  if (board) params.set('board', board)
  const query = params.toString()
  return `${BASE}/stream${query ? `?${query}` : ''}`
}
