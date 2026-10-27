/**
 * The catalog of services one can connect, as the window "Add an integration" shows it.
 *
 * Kept apart from the window so the search and its order can be tested
 * without drawing two hundred tiles.
 */
import type { AdapterSpec, Integration } from '../../../api/types'
import { tAdapter } from '../../../i18n/texts'
import { folded } from './own'

export interface CatalogEntry {
  adapter: AdapterSpec
  /** How many connections of this service there are already. */
  connected: number
  /** Everything it is found by, folded. */
  haystack: string
}

/** What can be added here: everything that takes a connection, in the categories' order and by name within. */
export function entries(adapters: AdapterSpec[], integrations: Integration[], order: readonly string[], categoryName: (category: string) => string): CatalogEntry[] {
  const counts = new Map<string, number>()
  for (const integration of integrations) counts.set(integration.kind, (counts.get(integration.kind) ?? 0) + 1)
  const place = (category: string) => (order.includes(category) ? order.indexOf(category) : order.length)
  return adapters
    .filter((adapter) => adapter.needs_integration || adapter.optional_integration)
    // A custom card sits on a connection of another kind; it is not one to add.
    .filter((adapter) => adapter.kind !== 'custom')
    .sort((a, b) => place(a.category) - place(b.category) || a.label.localeCompare(b.label, undefined, { sensitivity: 'base' }))
    .map((adapter) => ({
      adapter,
      connected: counts.get(adapter.kind) ?? 0,
      // ⚠️ The technical name counts: somebody types "wol", "pbs" or "npm",
      // which none of the written-out names contain. The vendors count as
      // well: nobody searches for "SNMP", they search for the name printed on
      // their switch. And the description in the language on screen, so
      // "fotos" finds Immich for somebody reading German.
      haystack: folded(
        [adapter.kind, adapter.label, adapter.category, categoryName(adapter.category), adapter.description, tAdapter(adapter.description), ...(adapter.keywords ?? [])].join(' '),
      ),
    }))
}

function words(query: string): string[] {
  return folded(query).split(/\s+/).filter(Boolean)
}

/**
 * The entries that carry every word of the query, best first: a name that
 * starts with the first word, then a name that holds it, then the rest in
 * catalog order. Enter opens the first, so the first has to be the one meant.
 */
export function search(list: CatalogEntry[], query: string, hideBeta: boolean): CatalogEntry[] {
  const wanted = words(query)
  const hits = list.filter((entry) => (!hideBeta || !entry.adapter.beta) && wanted.every((word) => entry.haystack.includes(word)))
  if (!wanted.length) return hits
  const first = wanted[0]
  const score = (entry: CatalogEntry) => {
    const name = folded(entry.adapter.label)
    if (name.startsWith(first)) return 0
    if (name.includes(first)) return 1
    if (entry.adapter.kind.startsWith(first)) return 2
    return 3
  }
  // A stable sort keeps the catalog order within each score.
  return hits.map((entry, index) => ({ entry, index, score: score(entry) })).sort((a, b) => a.score - b.score || a.index - b.index).map(({ entry }) => entry)
}

/** Where the first word of the query sits in a name, to mark it; null where it does not, or where folding moved the letters. */
export function markIn(name: string, query: string): [number, number] | null {
  const first = words(query)[0]
  if (!first) return null
  const plain = folded(name)
  if (plain.length !== name.length) return null
  const at = plain.indexOf(first)
  return at < 0 ? null : [at, at + first.length]
}

/**
 * The choices on the left: all, already connected, then each category the
 * catalog has, with how many of the hits are in it. A category the search
 * empties stays, with its nought, so the list does not jump while typing.
 */
export function sections(all: CatalogEntry[], hits: CatalogEntry[]): { id: string; count: number }[] {
  const categories = [...new Set(all.map((entry) => entry.adapter.category))]
  return [
    { id: 'all', count: hits.length },
    { id: 'connected', count: hits.filter((entry) => entry.connected > 0).length },
    ...categories.map((id) => ({ id, count: hits.filter((entry) => entry.adapter.category === id).length })),
  ]
}

/** The hits under one of the choices on the left. */
export function within(hits: CatalogEntry[], section: string): CatalogEntry[] {
  if (section === 'all') return hits
  if (section === 'connected') return hits.filter((entry) => entry.connected > 0)
  return hits.filter((entry) => entry.adapter.category === section)
}

/** One sentence of a description for a tile: up to the first full stop that ends a sentence, the whole text if there is none. */
export function firstSentence(text: string): string {
  const end = /[.!?](\s|$)/.exec(text)
  return end ? text.slice(0, end.index + 1) : text
}
