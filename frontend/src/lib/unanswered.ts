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

/** What is wrong with a typed number, as the key of the sentence that says so. */
export type NumberProblem = 'number' | 'whole' | 'range' | 'atLeast' | 'atMost' | 'step'

/**
 * Whether a typed value fits a `number` blank; `null` when it does, or when
 * nothing has been typed yet (that is "not filled in", not "wrong").
 *
 * ⚠️ The server checks the same things again before anything goes out. This
 * one exists so the person hears it at the field rather than from a refusal.
 * A whole `step` means whole numbers, and the steps count from `min` (or 0), as on the server.
 */
export function numberProblem(blank: Ask, raw: string): NumberProblem | null {
  if (blank.kind !== 'number' || raw.trim() === '') return null
  const value = Number(raw)
  if (!Number.isFinite(value)) return 'number'
  if (blank.step !== undefined && Number.isInteger(blank.step) && !Number.isInteger(value)) return 'whole'
  const low = blank.min !== undefined && value < blank.min
  const high = blank.max !== undefined && value > blank.max
  if (low || high) {
    if (blank.min !== undefined && blank.max !== undefined) return 'range'
    return low ? 'atLeast' : 'atMost'
  }
  // The steps count from the lowest value, or from 0 (as the server counts them).
  if (blank.step !== undefined && blank.step > 0) {
    const steps = (value - (blank.min ?? 0)) / blank.step
    if (Math.abs(steps - Math.round(steps)) > 1e-9) return 'step'
  }
  return null
}

/**
 * Whether pressing the action first opens the sheet.
 *
 * A confirmation asks for it, a blank nobody filled in needs it, and a
 * dangerous action asks even if its card forgot to say `confirm` (danger
 * includes it: the card cannot ask for less than the red button promises).
 */
export function needsSheet(action: Action): boolean {
  return Boolean(action.confirm || action.danger || unanswered(action).length)
}
