/**
 * Ticking a box in a note: the n-th checkbox the card draws is the n-th task
 * line of the source, `- [ ]` or `- [x]`, outside fenced code, where Markdown
 * draws no boxes.
 */
const TASK = /^(\s*(?:[-*+]|\d+[.)])\s+\[)([ xX])(\])(?=\s|$)/
const FENCE = /^\s*(```|~~~)/

/** The source with the n-th box flipped, or null when there is no such box. */
export function toggleTask(source: string, index: number): string | null {
  const lines = source.split('\n')
  let fenced = false
  let seen = 0
  for (let at = 0; at < lines.length; at += 1) {
    if (FENCE.test(lines[at])) {
      fenced = !fenced
      continue
    }
    if (fenced || !TASK.test(lines[at])) continue
    if (seen === index) {
      lines[at] = lines[at].replace(TASK, (_all, before: string, mark: string, after: string) => `${before}${mark === ' ' ? 'x' : ' '}${after}`)
      return lines.join('\n')
    }
    seen += 1
  }
  return null
}

/** The longest note the server takes; `NOTE_LIMIT` in `backend/app/schemas.py`. */
export const NOTE_LIMIT = 20_000
