/**
 * The connections already made, as the page lists them: what needs a look first.
 *
 * Every number of the summary is a filter, and the list puts the failing
 * connections at the top, then those with a newer release, then the rest by
 * name. Kept apart from the page so the order can be tested without drawing it.
 */
import type { AdapterSpec, Integration } from '../../../api/types'

/** What ``GET /integrations/versions`` says about one connection. */
export interface VersionReading {
  running: string | null
  newest: string | null
  url: string
  problem: string
  state: 'behind' | 'current' | 'unknown'
  major: boolean
  upstream: string
  /** The service could not be asked at all. */
  unread: boolean
  /** Whether GitHub may be asked: the switch Check for updates under System, About. */
  asked: boolean
}

export interface OwnRow {
  integration: Integration
  /** The adapter's category, as the catalog groups it. */
  category: string
  /** Switched on, real, and its last answer was an error. */
  failing: boolean
  /** A newer release than the one it runs. A failing one is counted as failing only. */
  behind: boolean
  reading?: VersionReading
  /** The description of its kind is gone (KARTEN-3 EC-6). */
  missing: boolean
}

/** Whether the description of the kind of a connection is gone (KARTEN-3 EC-6): the server says so, or the adapters do not know the kind. */
export function missingKind(integration: Integration, adapters: AdapterSpec[] | undefined): boolean {
  return integration.missing === true || (adapters !== undefined && !adapters.some((adapter) => adapter.kind === integration.kind))
}

export type OwnFilter = 'all' | 'failing' | 'updates' | 'cardless' | 'muted'

/** The summary, in the order it is shown; each one filters the list. */
export const FILTERS: { id: OwnFilter; test: (row: OwnRow) => boolean; tone?: 'bad' | 'warn' }[] = [
  { id: 'all', test: () => true },
  { id: 'failing', test: (row) => row.failing, tone: 'bad' },
  { id: 'updates', test: (row) => row.behind, tone: 'warn' },
  { id: 'cardless', test: (row) => row.integration.widget_count === 0 },
  { id: 'muted', test: (row) => row.integration.muted },
]

export function rowsOf(integrations: Integration[], adapters: AdapterSpec[], versions: Record<string, VersionReading> | undefined): OwnRow[] {
  const categories = new Map(adapters.map((adapter) => [adapter.kind, adapter.category]))
  return integrations.map((integration) => {
    // ⚠️ A connection that is switched off or invents its data keeps the error
    // of its last real answer; it is not failing now, so it does not go red.
    const failing = integration.enabled && !integration.demo && Boolean(integration.last_error)
    const reading = versions?.[String(integration.id)]
    return { integration, category: categories.get(integration.kind) ?? 'other', failing, behind: !failing && reading?.state === 'behind', reading, missing: missingKind(integration, adapters) }
  })
}

/** Lower case and without accents, so "fotos" finds "Fotos" and "fritz" finds "FRITZ!Box". */
export function folded(text: string): string {
  return text
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/ß/g, 'ss')
}

/** Every word of the query somewhere in the haystack, in any order. */
export function matches(haystack: string, query: string): boolean {
  const hay = folded(haystack)
  return folded(query)
    .split(/\s+/)
    .filter(Boolean)
    .every((word) => hay.includes(word))
}

/** Failing first, then behind, then by name. */
export function rank(row: OwnRow): number {
  return row.failing ? 0 : row.behind ? 1 : 2
}

export function visible(rows: OwnRow[], filter: OwnFilter, query: string, categoryName: (category: string) => string): OwnRow[] {
  const test = (FILTERS.find((one) => one.id === filter) ?? FILTERS[0]).test
  return rows
    .filter(test)
    .filter(({ integration, category }) => matches(`${integration.name} ${integration.label} ${integration.kind} ${categoryName(category)} ${integration.last_error}`, query))
    .sort((a, b) => rank(a) - rank(b) || a.integration.name.localeCompare(b.integration.name, undefined, { sensitivity: 'base' }))
}

export interface OwnGroup {
  category: string
  rows: OwnRow[]
  failing: number
  updates: number
}

/** The same rows under their categories, in the catalog's order; a category with none is left out. */
export function grouped(rows: OwnRow[], order: readonly string[]): OwnGroup[] {
  const by = new Map<string, OwnRow[]>()
  for (const row of rows) by.set(row.category, [...(by.get(row.category) ?? []), row])
  const place = (category: string) => (order.includes(category) ? order.indexOf(category) : order.length)
  return [...by.entries()]
    .sort(([a], [b]) => place(a) - place(b) || a.localeCompare(b))
    .map(([category, list]) => ({ category, rows: list, failing: list.filter((row) => row.failing).length, updates: list.filter((row) => row.behind).length }))
}

const VIEW_KEY = 'nexdeck.integrations.view'

/** List or by category, as this browser last chose it. */
export function storedView(): 'list' | 'category' {
  try {
    return localStorage.getItem(VIEW_KEY) === 'category' ? 'category' : 'list'
  } catch {
    // A private window or blocked storage: the list, as it always was.
    return 'list'
  }
}

export function storeView(view: 'list' | 'category'): void {
  try {
    localStorage.setItem(VIEW_KEY, view)
  } catch {
    // Not kept, and nothing else depends on it.
  }
}
