/**
 * What the Card shop (KARTEN-14) reads from the server, and the plain functions behind its list: search, filters, sorting.
 *
 * The texts of an entry (name, description, reason) are the author's own and plain text (KARTEN-13 EC-8): they are picked
 * in the viewer's language with `pickText` and drawn as text, never as HTML.
 */
import type { ImportDocument } from './cardExchange'
import type { CardText } from './cardText'
import type { CardForm } from './customCards'
import { pickText } from './cardText'

export type ShopCategory = 'media' | 'downloads' | 'network' | 'server' | 'smart_home' | 'other'
export const SHOP_CATEGORIES: ShopCategory[] = ['media', 'downloads', 'network', 'server', 'smart_home', 'other']

/** What a card can do to the service: only read, press buttons, or sign in with its own login. */
export type ShopClass = 'read' | 'buttons' | 'login'

export type ShopSort = 'thumbs' | 'new' | 'name'
export const SHOP_SORTS: ShopSort[] = ['thumbs', 'new', 'name']

export type ShopType = 'card' | 'integration'

/** Why an entry left the shop (KARTEN-15 AC-6). */
export type RemovedLevel = 'harmful' | 'not_useful' | 'withdrawn'

export interface ShopRemoved {
  level: RemovedLevel
  reason: string
  at: string
}

export interface ShopRead {
  kind: string
  path: string
}

export interface ShopButton {
  label: CardText
  method: string
  path: string
}

/** A kind of connection an entry needs, with its name and logo as people read them. */
export interface ShopNeed {
  kind: string
  label: string
  icon: string
}

/** A connection of this installation that fits an entry. */
export interface ShopConnection {
  id: number
  name: string
  kind: string
}

/** What stands installed of an entry here (KARTEN-14 EC-3, KARTEN-15 AC-1). */
export interface ShopInstalled {
  slug: string
  version: string
  update: boolean
  locally_changed: boolean
}

/** One entry of the catalog as the server hands it over: the catalog's own fields plus what depends on this installation. */
export interface ShopEntry {
  id: string
  author_id: string
  slug: string
  type: ShopType
  name: CardText
  description: string
  author: { id: string; login: string }
  version: string
  min_nexdeck: string | null
  category: ShopCategory
  requires: ShopNeed[]
  class: ShopClass
  reads: ShopRead[]
  buttons: ShopButton[]
  thumbs: number
  discussion: string | null
  based_on: string | null
  updated_at: string
  license: string | null
  removed: ShopRemoved | null
  /** nexdeck here is older than `min_nexdeck` (EC-2). */
  needs_newer: boolean
  /** At least one connection of a kind in `requires` exists here (the filter "Fits my connections"). */
  fits: boolean
  connections: ShopConnection[]
  installed: ShopInstalled | null
  images: { light: string; dark: string }
}

/** The detail of one entry (`GET /workshop/entries/{author}/{slug}`): the entry with the texts that are not in the list. */
export interface ShopDetail extends ShopEntry {
  readme: string | null
  changelog: string | null
  offered_integrations: ShopEntry[]
}

export interface ShopFilters {
  query: string
  fits: boolean
  category: ShopCategory | 'all'
  type: ShopType | 'all'
  sort: ShopSort
}

export const NO_FILTERS: ShopFilters = { query: '', fits: false, category: 'all', type: 'all', sort: 'thumbs' }

/** Whether any filter narrows the list (the search counts, the sorting does not). */
export function narrowed(filters: ShopFilters): boolean {
  return filters.query.trim() !== '' || filters.fits || filters.category !== 'all' || filters.type !== 'all'
}

/** The line that is searched: name, short name, author, description and the kinds of service. */
function haystack(entry: ShopEntry, lang: string): string {
  return [pickText(entry.name, lang), pickText(entry.name, 'en'), entry.slug, entry.author.login, entry.description, ...entry.requires.map((need) => need.label)].join(' ').toLowerCase()
}

/**
 * The entries to show: filtered, then sorted. Thumbs and "new" go from most to least, ties by name so the order stays
 * stable; names go with the viewer's language rules.
 */
export function shopList(entries: ShopEntry[], filters: ShopFilters, lang: string): ShopEntry[] {
  const needle = filters.query.trim().toLowerCase()
  const shown = entries.filter((entry) => {
    if (filters.fits && !entry.fits) return false
    if (filters.category !== 'all' && entry.category !== filters.category) return false
    if (filters.type !== 'all' && entry.type !== filters.type) return false
    return !needle || haystack(entry, lang).includes(needle)
  })
  const name = (entry: ShopEntry) => pickText(entry.name, lang) || entry.slug
  const byName = (a: ShopEntry, b: ShopEntry) => name(a).localeCompare(name(b), lang) || a.id.localeCompare(b.id)
  if (filters.sort === 'name') return shown.sort(byName)
  if (filters.sort === 'new') return shown.sort((a, b) => b.updated_at.localeCompare(a.updated_at) || byName(a, b))
  return shown.sort((a, b) => b.thumbs - a.thumbs || byName(a, b))
}

const FITS_KEY = 'nexdeck.shop.fits'

/** "Fits my connections" is on at first and remembered for this browser (KARTEN-14 EC-9). */
export function storedFits(): boolean {
  try {
    return localStorage.getItem(FITS_KEY) !== '0'
  } catch {
    return true
  }
}

export function rememberFits(on: boolean): void {
  try {
    localStorage.setItem(FITS_KEY, on ? '1' : '0')
  } catch {
    // storage may be unavailable
  }
}

/** The state of the switch (`GET /workshop/state`); it never asks GitHub. */
export interface ShopState {
  enabled: boolean
  repo: string
  token_set: boolean
  risk_acknowledged: boolean
  nexdeck_version: string
  catalog: { fetched_at: string; generated_at: string; count: number } | null
}

/** The catalog (`GET /workshop/catalog`). `warning` is set when the older remembered catalog is shown. */
export interface ShopCatalog {
  fetched_at: string
  generated_at: string
  entries: ShopEntry[]
  warning: { code: string; message: string } | null
}

/** One update waiting for an installed card (`GET /workshop/updates`). */
export interface ShopUpdateRow {
  slug: string
  ref: string
  name: CardText
  installed_version: string
  new_version: string
  needs_newer: boolean
  min_nexdeck: string | null
  locally_changed: boolean
}

export interface ShopRemovedRow {
  slug: string
  ref: string
  name: CardText
  level: RemovedLevel
  reason: string
  at: string
}

export interface ShopUpdates {
  enabled: boolean
  catalog_known: boolean
  updates: ShopUpdateRow[]
  removed: ShopRemovedRow[]
}

export interface ShopButtonText {
  id: string
  label: CardText
  method: string
  path: string
  send?: string
  body?: unknown
  where?: string
}

/** What an update changes (`GET /workshop/updates/{slug}`, KARTEN-15 AC-2). */
export interface ShopUpdate {
  slug: string
  name: CardText
  ref: string
  installed_version: string
  new_version: string
  needs_newer: boolean
  min_nexdeck: string | null
  changelog: string | null
  locally_changed: boolean
  permissions: {
    requires: { added: string[]; removed: string[] }
    requests: { added: { id: string; path: string }[]; changed: { id: string; before: string; after: string }[]; removed: { id: string; path: string }[] }
    buttons: { added: ShopButtonText[]; changed: { before: ShopButtonText; after: ShopButtonText }[]; removed: ShopButtonText[] }
  }
  buttons_to_confirm: string[]
  connection_changed: boolean
  placed_on: number
}

export const SHOP_STATE_KEY = ['workshop-state']
export const SHOP_CATALOG_KEY = ['workshop-catalog']
export const SHOP_UPDATES_KEY = ['workshop-updates']

/** The path of an entry in the routes: `{author}/{slug}`, each part encoded. */
export function entryPath(entry: { id: string }): string {
  return entry.id.split('/').map(encodeURIComponent).join('/')
}

/** Whether a removed entry still counts for a list: only the ones installed here are shown (the others left the shop). */
export function visible(entry: ShopEntry): boolean {
  return entry.removed === null || entry.installed !== null
}

/** The part of an entry's wording that names the kind of fault; the rest is the server's own sentence. */
export const SHOP_PROBLEM_CODES = ['github_unreachable', 'github_rejected', 'github_rate_limited', 'catalog_invalid', 'catalog_empty'] as const

/** What installing would do (`POST /workshop/entries/{author}/{slug}/install/check`). */
export interface ShopInstallCheck {
  entry: ShopEntry
  ok: boolean
  documents: ImportDocument[]
  missing_integrations: string[]
  offered_integrations: ShopEntry[]
  risk_acknowledged: boolean
}

/** What an install answers (`POST /workshop/entries/{author}/{slug}/install`). */
export interface ShopInstalledAnswer {
  slug: string | null
  integration: string | null
  missing_integrations: string[]
}

/**
 * The form a previewed card is drawn with. The answer of the preview carries the finished values and not the form, so it is
 * read off them: blocks are a builder, rows are a list (a wall of pictures when a row has one), several numbers are
 * stats, and a single number is a value.
 */
export function previewForm(data: { primary?: unknown; secondary?: unknown[]; items?: { art?: unknown }[]; meta?: Record<string, unknown> }): CardForm {
  if (data.meta && 'blocks' in data.meta) return 'builder'
  if (data.meta && 'empty' in data.meta) return (data.items ?? []).some((one) => Boolean(one.art)) ? 'posters' : 'list'
  return (data.secondary ?? []).length > 0 ? 'stats' : 'value'
}
