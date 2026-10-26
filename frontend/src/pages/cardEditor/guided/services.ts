/**
 * The services of the first step (D2): one entry per kind, never per connection. A card names the kind it reads
 * (`requires`) and works with every connection of that kind; the connections only decide what can be tried here.
 */
import type { Integration } from '../../../api/types'
import { categoryRank } from '../../../lib/adapterCategories'
import type { CardSource } from '../../../lib/customCards'

export interface ServiceKind extends CardSource {
  category: string
  /** The switched-on connections of this kind, as the editor can try the card with them. */
  connections: Integration[]
}

export interface ServiceGroups {
  /** Kinds with at least one connection of the person. */
  connected: ServiceKind[]
  /** Every other kind a card can read, by category and then by name. */
  others: ServiceKind[]
}

const byName = (a: ServiceKind, b: ServiceKind) => a.label.localeCompare(b.label, undefined, { sensitivity: 'base' })

/** Split the kinds a card can read into those the person has a connection of and the rest. */
export function serviceGroups(sources: CardSource[], integrations: Integration[]): ServiceGroups {
  const mine = new Map<string, Integration[]>()
  for (const one of integrations) if (one.enabled !== false) mine.set(one.kind, [...(mine.get(one.kind) ?? []), one])
  const all = sources.map((one) => ({ ...one, category: one.category || 'other', connections: mine.get(one.kind) ?? [] }))
  return {
    connected: all.filter((one) => one.connections.length).sort(byName),
    others: all.filter((one) => !one.connections.length).sort((a, b) => categoryRank(a.category) - categoryRank(b.category) || byName(a, b)),
  }
}

/** Those whose name, kind or category contains the words typed (the category as it reads on screen). */
export function matchingServices(list: ServiceKind[], query: string, categoryLabel: (category: string) => string): ServiceKind[] {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  if (!words.length) return list
  return list.filter((one) => {
    const text = `${one.label} ${one.kind} ${one.category} ${categoryLabel(one.category)}`.toLowerCase()
    return words.every((word) => text.includes(word))
  })
}

/** Consecutive runs of one category, in the order given. */
export function byCategory(list: ServiceKind[]): [string, ServiceKind[]][] {
  const groups: [string, ServiceKind[]][] = []
  for (const one of list) {
    const last = groups[groups.length - 1]
    if (last && last[0] === one.category) last[1].push(one)
    else groups.push([one.category, [one]])
  }
  return groups
}
