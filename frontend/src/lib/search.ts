/**
 * The bar that leaves the house.
 *
 * nexdeck's own bar finds boards, cards and settings. These few lines are the
 * other half: a typed word handed to a search engine or to a service that is
 * already connected. A shortcut in front picks one of them, so `!y cats` goes
 * straight to YouTube instead of showing every target at once.
 */
export interface SearchTarget {
  name: string
  /** Carries `{query}`; the words go in there, encoded. */
  url: string
  prefix: string
  icon: string
}

export interface SearchSettings {
  enabled: boolean
  targets: SearchTarget[]
}

/** The address to open. The words are encoded, so a `&` cannot add a parameter. */
export function searchUrl(target: SearchTarget, query: string): string {
  return target.url.replaceAll('{query}', encodeURIComponent(query.trim()))
}

/**
 * A query split into the target it names and the rest.
 *
 * `!y cats` picks the target whose shortcut is `y` and searches for `cats`.
 * Without a shortcut, or with one nobody has, every target stays on offer and
 * the whole text is the query.
 */
export function pickTarget(targets: SearchTarget[], query: string): { chosen: SearchTarget | null; rest: string } {
  const match = /^!([a-z0-9]{1,6})(?:\s+([\s\S]*))?$/i.exec(query.trim())
  if (!match) return { chosen: null, rest: query }
  const wanted = match[1].toLowerCase()
  const chosen = targets.find((target) => target.prefix.toLowerCase() === wanted) ?? null
  return chosen ? { chosen, rest: (match[2] ?? '').trim() } : { chosen: null, rest: query }
}
