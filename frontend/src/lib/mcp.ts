/**
 * AI from outside (MCP): what the keys, the rights and the approval requests
 * look like on the wire, and the small rules the pages share.
 *
 * The server owns every decision. What is worked out here only decides what
 * to offer: a right that cannot be set is greyed out with its reason, and a
 * request that has been answered shows no buttons. The server refuses the
 * same things again.
 */
import { del, post } from '../api/client'
import { useNotices } from '../stores/notices'
import type { Fact } from './assistant'

export type McpLevel = 'read' | 'act'
export type McpRight = 'allow' | 'ask' | 'deny'
export type McpGroup = 'read' | 'act' | 'admin'

export interface McpStatus {
  allowed: boolean
  max_level: McpLevel
  oauth_allowed: boolean
  /** Public address of the endpoint, `/api/mcp` included. */
  endpoint: string
}

export interface McpTool {
  name: string
  group: McpGroup
  level: McpLevel
  description: string
  default_right: McpRight
  /** Switched off for every key by the administrator. */
  blocked: boolean
  admin_only: boolean
}

export interface McpKey {
  id: number
  name: string
  prefix: string
  /** `oauth` for a connected program; anything else is a key made by hand. */
  kind: string
  level: McpLevel
  /** Board ids, or null for every board the account may see. */
  boards: number[] | null
  /** Only what differs from the tool's default. */
  tool_rights: Record<string, McpRight>
  created_at: string
  last_used_at: string | null
  expires_at: string | null
  revoked: boolean
  /** Name of the connected program, `oauth` keys only. */
  client?: string | null
  /** The account, in the administrator's list. */
  user?: string | { username?: string; name?: string } | null
}

export interface McpCreated {
  key: McpKey
  /** The secret. Shown once and never stored in the clear. */
  token: string
}

export type McpRequestStatus = 'waiting' | 'approved' | 'declined' | 'expired' | 'failed'

export interface McpRequest {
  id: number
  key_name: string
  tool: string
  card_id: number
  card: string
  board: string
  action: string
  label: string
  danger: boolean
  params: Record<string, unknown>
  impact: Fact[]
  status: McpRequestStatus | string
  created_at: string
  expires_at: string
  result: unknown
}

export interface McpAdminSettings {
  allowed: boolean
  max_level: McpLevel
  oauth_allowed: boolean
  blocked_tools: string[]
}

export const EXPIRIES: (number | null)[] = [30, 90, 365, null]

export const GROUPS: McpGroup[] = ['read', 'act', 'admin']

/** The name of the account in the administrator's list, whichever shape the server sends. */
export function ownerOf(key: McpKey): string {
  const user = key.user
  if (!user) return ''
  return typeof user === 'string' ? user : (user.username ?? user.name ?? '')
}

/** Whether a key has run out, judged by the clock of this browser; the server judges again. */
export function expiredKey(key: McpKey, now = Date.now()): boolean {
  return !!key.expires_at && new Date(key.expires_at).getTime() <= now
}

/** Why a tool cannot be set on this key, or an empty string when it can. */
export type Reason = '' | 'blocked' | 'adminOnly' | 'level'

export interface Setting {
  reason: Reason
  options: McpRight[]
  value: McpRight
}

/**
 * What one row of "Rights per tool" offers.
 *
 * Only the tools that press something ask. A tool that merely looks (the
 * reading ones and the administration ones) is allowed or denied: there is
 * nothing to approve about looking, and the server refuses ``ask`` for them. The shown value is the key's own entry, else the
 * tool's default.
 */
export function settingOf(tool: McpTool, key: McpKey, rights: Record<string, McpRight>, admin: boolean): Setting {
  const options: McpRight[] = tool.group === 'act' ? ['allow', 'ask', 'deny'] : ['allow', 'deny']
  const own = rights[tool.name]
  const value = own && options.includes(own) ? own : options.includes(tool.default_right) ? tool.default_right : 'deny'
  const reason: Reason = tool.blocked ? 'blocked' : tool.admin_only && !admin ? 'adminOnly' : tool.level === 'act' && key.level === 'read' ? 'level' : ''
  return { reason, options, value }
}

/** The map to store: only what differs from the defaults, and what a greyed-out row already held stays as it was. */
export function rightsToStore(tools: McpTool[], key: McpKey, chosen: Record<string, McpRight>, admin: boolean): Record<string, McpRight> {
  const out: Record<string, McpRight> = {}
  for (const tool of tools) {
    const setting = settingOf(tool, key, chosen, admin)
    const value = setting.reason ? key.tool_rights[tool.name] : setting.value
    if (value && value !== tool.default_right) out[tool.name] = value
  }
  return out
}

export function addCommand(endpoint: string, token: string): string {
  return `claude mcp add --transport http nexdeck ${endpoint} --header "Authorization: Bearer ${token}"`
}

export function jsonConfig(endpoint: string, token: string): string {
  return JSON.stringify({ mcpServers: { nexdeck: { type: 'http', url: endpoint, headers: { Authorization: `Bearer ${token}` } } } }, null, 2)
}

/**
 * What a tool does, said for a person in the language on screen. The server's
 * text is written for the program, in English, and stays as it is there; it
 * stands in for a tool this browser has no words for.
 */
export function toolText(t: (key: string, options?: Record<string, unknown>) => string, tool: McpTool): string {
  return t(`mcp.tool.${tool.name}`, { defaultValue: tool.description })
}

/** The request a notice points at (`/mcp/requests/<id>`), or null for any other link. */
export function requestIdOf(link: string): number | null {
  const match = /^\/mcp\/requests\/(\d+)$/.exec(link)
  return match ? Number(match[1]) : null
}

/** Whether the answer can still be given: waiting, and the ten minutes not over by this browser's clock. */
export function openRequest(request: McpRequest, now = Date.now()): boolean {
  return request.status === 'waiting' && new Date(request.expires_at).getTime() > now
}

/** The text a request's result should show, whatever shape the server put there. */
export function resultText(result: unknown): string {
  if (result === null || result === undefined || result === '') return ''
  if (typeof result === 'string') return result
  // A press that worked answers with a message, one that could not run with an error.
  for (const field of ['message', 'error']) {
    const text = typeof result === 'object' ? (result as Record<string, unknown>)[field] : undefined
    if (typeof text === 'string') return text
  }
  return JSON.stringify(result, null, 2)
}

/**
 * Answers a request, then marks its notice as read: the bell stops counting a
 * question that has been answered, whichever place it was answered from.
 */
export async function decide(id: number, verb: 'approve' | 'decline'): Promise<{ status: string; result: unknown }> {
  const answer = await post<{ status: string; result: unknown }>(`/mcp/requests/${id}/${verb}`)
  const notices = useNotices.getState()
  const unread = notices.notices.filter((notice) => !notice.read_at && notice.link === `/mcp/requests/${id}`).map((notice) => notice.id)
  if (unread.length) await notices.markRead(unread).catch(() => undefined)
  return answer
}

export async function revokeKey(id: number, admin = false): Promise<void> {
  await del(admin ? `/mcp/admin/keys/${id}` : `/mcp/keys/${id}`)
}
