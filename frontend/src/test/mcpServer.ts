/**
 * A stand-in for the server in the MCP tests: answers `fetch` from a table of
 * "METHOD /path" to what the server would say, and writes down every call.
 * The shape follows the API contract between the pages and the backend
 * (`/api/v1/mcp/...`), so a page that asks for something else fails loudly.
 */
import { vi } from 'vitest'

import type { McpKey, McpRequest, McpStatus, McpTool } from '../lib/mcp'

export interface Call {
  method: string
  path: string
  body: unknown
}

export type Route = (body: unknown) => unknown

/** A refused answer in the app's own error shape. */
export function refusal(status: number, code: string, message: string): Response {
  return new Response(JSON.stringify({ detail: { code, message } }), { status, headers: { 'Content-Type': 'application/json' } })
}

export function serve(routes: Record<string, Route>): Call[] {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const method = (init?.method ?? 'GET').toUpperCase()
      const path = String(input).replace(/^.*\/api\/v1/, '')
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ method, path, body })
      const route = routes[`${method} ${path}`] ?? routes[`${method} ${path.split('?')[0]}`]
      if (!route) return refusal(404, 'not_found', `no route for ${method} ${path}`)
      const answer = route(body)
      if (answer instanceof Response) return answer
      return new Response(JSON.stringify(answer ?? {}), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }),
  )
  return calls
}

export const STATUS: McpStatus = { allowed: true, max_level: 'act', oauth_allowed: false, endpoint: 'https://deck.example.com/api/mcp' }

function tool(name: string, group: McpTool['group'], extra: Partial<McpTool> = {}): McpTool {
  return {
    name,
    group,
    level: group === 'act' ? 'act' : 'read',
    description: `${name} description`,
    default_right: group === 'read' ? 'allow' : group === 'act' ? 'ask' : 'deny',
    blocked: false,
    admin_only: group === 'admin',
    ...extra,
  }
}

export const TOOLS: McpTool[] = [
  tool('needs_attention', 'read'),
  tool('find_cards', 'read'),
  tool('press_button', 'act'),
  tool('diagnosis', 'admin'),
  tool('container_log', 'admin', { blocked: true }),
]

export function key(extra: Partial<McpKey> = {}): McpKey {
  return {
    id: 1,
    name: 'Laptop',
    prefix: 'ndm_AbCd',
    kind: 'key',
    level: 'read',
    boards: null,
    tool_rights: {},
    created_at: '2026-10-20T10:00:00Z',
    last_used_at: null,
    expires_at: null,
    revoked: false,
    ...extra,
  }
}

export function request(extra: Partial<McpRequest> = {}): McpRequest {
  return {
    id: 7,
    key_name: 'Laptop',
    tool: 'press_button',
    card_id: 4,
    card: 'Containers',
    board: 'Lab',
    action: 'restart',
    label: 'Restart',
    danger: false,
    params: { id: 'plex' },
    impact: [{ fact: 'streams', count: 2, names: ['Living room', 'Tablet'] }],
    status: 'waiting',
    created_at: new Date(Date.now() - 60_000).toISOString(),
    expires_at: new Date(Date.now() + 9 * 60_000).toISOString(),
    result: null,
    ...extra,
  }
}
