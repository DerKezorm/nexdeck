/**
 * What sharing a card in the Card shop reads from the server (KARTEN-16): the GitHub sign-in, the check before sharing,
 * and "My submissions". The words of the author (names, descriptions) are plain text and are never put in as HTML.
 */
import { ApiError } from '../api/client'

export type ShareKind = 'card' | 'integration'

/** The categories of the Workshop, in the order the form lists them. */
export const SHARE_CATEGORIES = ['media', 'downloads', 'network', 'server', 'smart_home', 'other'] as const
export type ShareCategory = (typeof SHARE_CATEGORIES)[number]

export const GITHUB_KEY = ['workshop-github']
export const SUBMISSIONS_KEY = ['workshop-submissions']

/** A code waiting to be typed on github.com. */
export interface GithubPending {
  user_code: string
  verification_uri: string
  expires_in: number
  interval: number
}

export interface GithubState {
  signed_in: boolean
  login: string | null
  github_id: string | null
  until: string | null
  pending: GithubPending | null
}

export type PollAnswer = { status: 'pending'; interval: number } | { status: 'expired' | 'denied' | 'none' } | ({ status: 'signed_in' } & GithubState)

export interface ShareProblem {
  code: string
  message: string
  path: string
}

export interface ShareCheck {
  type: ShareKind
  slug: string
  name: string
  version: string
  problems: ShareProblem[]
  warnings: { real_values: { path: string; value: string }[] }
  signed_in: boolean
  login: string | null
  /** A new entry, or the next version of one of this account's entries. */
  mode: 'new' | 'update'
  previous_version: string | null
  based_on: string | null
  removed: { level: string; reason: string } | null
  daily: { used: number; max: number; reached: boolean } | null
  /** Why GitHub could not tell more (the repository is private, nobody answers); the rest of the check stands. */
  github: { code: string; message: string } | null
  suggested: { description: string; category: string }
  reads: { label: string; path: string }[]
  repo: string
}

export interface ShareSent {
  issue: { number: number; url: string; state: string }
  created: boolean
  changed: boolean
  update: boolean
}

export interface ShareFile {
  filename: string
  text: string
  link: string
}

export type SubmissionState = 'checking' | 'failed' | 'waiting' | 'in_shop' | 'removed' | 'closed'

export interface SubmissionRow {
  issue: number
  url: string
  slug: string
  type: ShareKind
  update: boolean
  created_at: string
  state: SubmissionState
  reasons: string[]
  removed: { level: string; reason: string; at: string } | null
  entry: { id: string; version: string; thumbs: number; discussion: string | null } | null
  local: boolean
}

export interface Submissions {
  signed_in: boolean
  login: string | null
  items: SubmissionRow[]
  catalog_known: boolean
}

/** The codes of the server that have a sentence of the interface of their own; any other shows the server's English. */
export const SHARE_FAILURES = [
  'github_login_needed',
  'github_unreachable',
  'github_rate_limited',
  'github_rejected',
  'github_login_failed',
  'device_flow_off',
  'repo_no_access',
  'daily_limit',
  'already_sending',
  'not_resendable',
  'no_such_card',
] as const

/** The problems a rejected request carries. */
export function shareProblems(failure: unknown): ShareProblem[] {
  if (!(failure instanceof ApiError)) return []
  const list = failure.detail?.problems
  return Array.isArray(list) ? (list as ShareProblem[]) : []
}

/** The codes of problems that have a sentence of the interface of their own. */
export const SHARE_PROBLEMS = [
  'card_needs_demo',
  'card_needs_english',
  'entry_removed',
  'version_not_higher',
  'not_yours',
  'description',
  'category',
  'license',
  'changes',
  'secret_in_text',
  'too_long',
] as const

/** Where the card is to be changed again after a failed check: the editor of the card or of the connection. */
export function editorPath(kind: ShareKind, slug: string, resend?: number): string {
  const base = kind === 'card' ? `/system/custom-cards/${encodeURIComponent(slug)}/edit` : `/system/custom-cards/integrations/${encodeURIComponent(slug)}/edit`
  return resend ? `${base}?resend=${resend}` : base
}
