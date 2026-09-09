/**
 * Has the board caught up with what a save wrote?
 *
 * ⚠️ Asked by comparing, not by waiting for a request to come back. A board
 * fetch already in flight when Save is pressed answers with what the server
 * had before the save, and react-query hands that in-flight promise to the
 * next `refetch()` rather than starting a new request. A card released
 * against that answer blinks back to its old self for a moment, which is the
 * fault this page keeps being reported for.
 */

/** The four things a settings sheet writes. Nothing else decides this. */
export interface Settings {
  title?: string
  icon?: string
  link?: string | null
  options?: Record<string, unknown> | null
}

/**
 * ⚠️ Key order is not the same on both sides: one object was built in the
 * browser, the other came back as JSON. Plain `JSON.stringify` would call two
 * identical option sets different and leave the draft standing until its
 * timeout.
 */
function stable(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value ?? null)
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, one]) => one !== undefined)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
  return `{${entries.map(([key, one]) => `${JSON.stringify(key)}:${stable(one)}`).join(',')}}`
}

export function sameSettings(carried: Settings, draft: Settings): boolean {
  return (
    (carried.title ?? '') === (draft.title ?? '') &&
    (carried.icon ?? '') === (draft.icon ?? '') &&
    (carried.link ?? '') === (draft.link ?? '') &&
    stable(carried.options ?? {}) === stable(draft.options ?? {})
  )
}
