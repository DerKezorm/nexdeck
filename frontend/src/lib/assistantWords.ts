/**
 * The chat's own words (roadmap M3): an answer's paragraphs, lists and bold,
 * and the day headings of the history. Only the panel needs them, and it is
 * loaded the first time the chat opens, so they stay out of the board's first
 * load.
 */

/** Which day heading a conversation goes under in the list. */
export function dayGroup(at: string, now: Date = new Date()): 'today' | 'yesterday' | 'week' | 'older' {
  const then = new Date(at)
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const day = 24 * 60 * 60 * 1000
  if (then.getTime() >= start) return 'today'
  if (then.getTime() >= start - day) return 'yesterday'
  if (then.getTime() >= start - 6 * day) return 'week'
  return 'older'
}

/**
 * The few marks an answer may carry: paragraphs, "- " list items and
 * **bold**. Parsed into pieces, never into HTML: what a model writes is not
 * trusted as markup.
 */
export type Block = { kind: 'p'; parts: Part[] } | { kind: 'ul'; items: Part[][] }
export type Part = { text: string; bold: boolean }

export function inline(text: string): Part[] {
  const pieces = text.split('**')
  // An odd number of marks leaves the last one as it was written.
  const closed = pieces.length % 2 === 1 ? pieces.length : pieces.length - 1
  const parts: Part[] = []
  pieces.forEach((piece, index) => {
    const shown = index >= closed ? `**${piece}` : piece
    if (shown) parts.push({ text: shown, bold: index < closed && index % 2 === 1 })
  })
  return parts
}

export function blocks(text: string): Block[] {
  const out: Block[] = []
  for (const chunk of text.split(/\n\s*\n/)) {
    const lines = chunk.split('\n').map((line) => line.trimEnd()).filter((line) => line.trim())
    let paragraph: string[] = []
    const flush = () => {
      if (paragraph.length) out.push({ kind: 'p', parts: inline(paragraph.join(' ')) })
      paragraph = []
    }
    for (const line of lines) {
      const item = /^\s*(?:[-*•]|\d+[.)])\s+(.*)$/.exec(line)
      if (item) {
        flush()
        const last = out[out.length - 1]
        if (last?.kind === 'ul') last.items.push(inline(item[1]))
        else out.push({ kind: 'ul', items: [inline(item[1])] })
      } else paragraph.push(line.trim())
    }
    flush()
  }
  return out
}
