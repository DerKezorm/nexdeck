/**
 * Moving one entry of a list to another place.
 *
 * Its own function, because the same three lines are wrong in three different
 * ways when they are written inside a drag handler: an index that shifts once
 * the entry has been taken out, a move onto its own place that rewrites the
 * list for nothing, and an index off the end that silently drops the entry.
 */
export function moved<T>(list: readonly T[], from: number, to: number): T[] {
  const next = [...list]
  if (from < 0 || from >= next.length || to < 0 || to >= next.length || from === to) return next
  const [one] = next.splice(from, 1)
  next.splice(to, 0, one)
  return next
}
