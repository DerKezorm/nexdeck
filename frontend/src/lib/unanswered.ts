/**
 * Which blanks of an action still need somebody to fill them in.
 *
 * A card with its own field (MeTube's address) fills its blank before it hands
 * the action over, so nothing is left and the press goes straight through. A
 * row whose request has no target folder hands over two pick lists nobody has
 * answered yet, and those open the sheet.
 */
import type { Action, Ask } from './types'

export function unanswered(action: Action): Ask[] {
  const given = action.params ?? {}
  return (action.asks ?? []).filter((blank) => {
    const value = given[blank.name]
    return value === undefined || value === null || String(value).trim() === ''
  })
}

/**
 * The value a pick list starts on.
 *
 * ⚠️ Only when there is exactly one thing to pick. Pre-selecting the first of
 * several would turn "nobody chose" into "somebody chose the first folder",
 * and the title would land there without anyone having decided it. Nexview's
 * own approval page is built around exactly that mistake not happening.
 */
export function startingValue(blank: Ask): string {
  if (blank.kind === 'choice' && blank.options?.length === 1) return blank.options[0].value
  return ''
}
