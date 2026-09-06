import type { BoardView, WidgetData, WidgetView } from '../lib/types'

export interface User {
  id: number
  username: string
  display_name: string
  role: 'admin' | 'user' | 'guest'
  locale: string
  theme: 'dark' | 'light' | 'system'
  start_board_id: number | null
  disabled: boolean
  seen_version: string
  has_password: boolean
  auth_kind: string
  /** Address of the profile picture, or null while the account has none. */
  avatar_url: string | null
  /** Where a password reset would go; empty while none is stored. */
  email: string
}

export interface SetupStatus {
  needs_setup: boolean
  version: string
  demo: boolean
  providers: { slug: string; label: string }[]
}

export interface BoardSummary {
  id: number
  slug: string
  name: string
  icon: string
  owner_id: number | null
  /** Name of the owner; empty when the account is gone. */
  owner_name: string
  permission: 'view' | 'edit' | 'act' | 'owner'
  provisioned: boolean
  position: number
  /** Whether the board stands in the menu at the top. */
  in_menu: boolean
  pages: { id: number; name: string; slug: string; widget_count: number }[]
  widget_count: number
}

export interface FieldSpec {
  name: string
  label: string
  /** `integrations` is a list of connection numbers; `options` names the kinds that may be picked. */
  type: 'text' | 'password' | 'url' | 'number' | 'bool' | 'select' | 'integrations' | 'textarea' | 'timezone'
  required: boolean
  secret: boolean
  default: unknown
  help: string
  placeholder: string
  options: { value: string; label: string }[]
  helper?: string
}

export interface WidgetTypeSpec {
  kind: string
  label: string
  description: string
  renderer: string
  default_size: [number, number]
  min_size: [number, number]
  options: FieldSpec[]
  refresh_seconds: number
  metrics: string[]
  client_only: boolean
}

export interface AdapterSpec {
  kind: string
  label: string
  category: string
  description: string
  icon: string
  beta: boolean
  docs_url: string
  needs_integration: boolean
  fields: FieldSpec[]
  widgets: WidgetTypeSpec[]
}

export interface Integration {
  id: number
  kind: string
  label: string
  icon: string
  beta: boolean
  name: string
  config: Record<string, unknown>
  enabled: boolean
  demo: boolean
  /** Locked: only administrators may build cards on it, and only they see it listed. */
  admin_only: boolean
  last_ok_at: string | null
  last_error: string
  widget_count: number
  created_at: string
}

export interface Notice {
  id: number
  event: string
  level: 'info' | 'warn' | 'error'
  title: string
  body: string
  link: string
  created_at: string
  read_at: string | null
}

export interface ChannelKind {
  kind: string
  label: string
  help: string
  fields: FieldSpec[]
}

export interface Channel {
  id: number
  kind: string
  name: string
  config: Record<string, unknown>
  enabled: boolean
  events: string[]
  last_error: string
  created_at: string
}

export interface ApiToken {
  id: number
  name: string
  prefix: string
  created_at: string
  last_used_at: string | null
  token?: string
}

export interface KioskToken {
  id: number
  name: string
  prefix: string
  allow_actions: boolean
  cycle_seconds: number
  dim_from: string
  dim_to: string
  created_at: string
  last_used_at: string | null
  token?: string
  url?: string
}

export interface BoardWithLive extends BoardView {
  live: Record<string, WidgetData>
  kiosk?: { cycle_seconds: number; dim_from: string; dim_to: string; allow_actions: boolean; name: string }
}

export interface About {
  version: string
  demo: boolean
  public_url: string
  update_check: boolean
  default_locale: string
  counts: { boards: number; widgets: number; integrations: number; users: number }
  connections: number
  latest_version: string | null
  repo_url: string
  release_url: string
  issues_url: string
  website_url: string
  license: string
  /** When the update check last asked GitHub, or null while it never has. */
  checked_at: string | null
}

export interface Suggestion {
  container: string
  id: string
  image: string
  running: boolean
  name: string
  url: string
  icon: string
  group: string
  description: string
  labelled: boolean
}

export type { WidgetView }
