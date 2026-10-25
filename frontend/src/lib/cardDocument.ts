/**
 * The text of a custom card as one YAML document, the one truth of the card editor (KARTEN-9, KARTEN-10).
 *
 * Every field of the editor reads and writes this document by path; the YAML view is its text. A change made in
 * the editor is written back so that every line it does not touch stays exactly as the author wrote it, comments
 * and order included (KARTEN-10 AC-4, EC-1, EC-2): the change is made on the document, both the old and the new
 * document are written out, and only the lines that differ between those two are carried into the author's text.
 *
 * What a definition may not be is refused here with the line it happens on, before the server is asked: tabs
 * for indenting (EC-7), anchors, aliases and more than one document (EC-3).
 */
import {
  isAlias,
  isMap,
  isNode,
  isScalar,
  isSeq,
  LineCounter,
  parseAllDocuments,
  visit,
  type Document,
  type Node,
  type ToStringOptions,
} from 'yaml'

/** Where a part of the card sits: keys of maps and positions in lists, from the top. */
export type CardPath = readonly (string | number)[]

/** What the local check can find, before the server sees the text. */
export type LocalCode = 'yaml_empty' | 'yaml_syntax' | 'yaml_tab' | 'yaml_anchor' | 'yaml_alias' | 'yaml_documents' | 'yaml_not_map'

/** One thing wrong with the text as YAML. `reason` is the parser's own English words, only for `yaml_syntax`. */
export interface LocalProblem {
  code: LocalCode
  line: number | null
  reason?: string
}

/** A text that reads as one card document. */
export interface CardDoc {
  text: string
  doc: Document.Parsed
  lines: LineCounter
}

export type Parsed = { ok: true; card: CardDoc } | { ok: false; problems: LocalProblem[] }

/** A tab anywhere in the indentation of a line. YAML indents with spaces only. */
const TAB_INDENT = /^[ ]*\t|^[ ]*-[ \t]*\t/

/** The text as one card document, or every reason it is not one, each at its line. */
export function parseCard(text: string): Parsed {
  if (!text.trim()) return { ok: false, problems: [{ code: 'yaml_empty', line: null }] }

  const tabs: LocalProblem[] = []
  text.split('\n').forEach((line, index) => {
    if (TAB_INDENT.test(line)) tabs.push({ code: 'yaml_tab', line: index + 1 })
  })
  if (tabs.length) return { ok: false, problems: tabs }

  const lines = new LineCounter()
  const docs = parseAllDocuments(text, { lineCounter: lines, prettyErrors: true, uniqueKeys: true })
  if (!Array.isArray(docs) || docs.length === 0) return { ok: false, problems: [{ code: 'yaml_empty', line: null }] }
  const lineAt = (offset: number | undefined) => (offset === undefined ? null : lines.linePos(offset).line)
  if (docs.length > 1) return { ok: false, problems: [{ code: 'yaml_documents', line: lineAt(docs[1].range[0]) }] }

  const doc = docs[0]
  const problems: LocalProblem[] = doc.errors.map((failure) => ({
    code: 'yaml_syntax' as const,
    line: failure.linePos?.[0]?.line ?? null,
    // The parser says "… at line 3, column 1:" and then quotes the line; the line has a place of its own here.
    reason: failure.message.split('\n')[0].replace(/ at line \d+, column \d+:?$/, ''),
  }))
  if (problems.length) return { ok: false, problems }

  visit(doc, {
    Node(_, node) {
      if (isAlias(node)) problems.push({ code: 'yaml_alias', line: lineAt(node.range?.[0]) })
      // ⚠️ The node of an anchored list begins on the line below its anchor; the anchor itself is what is named.
      else if (node.anchor) {
        const at = text.indexOf(`&${node.anchor}`)
        problems.push({ code: 'yaml_anchor', line: lineAt(at >= 0 ? at : node.range?.[0]) })
      }
    },
  })
  if (problems.length) return { ok: false, problems }
  if (!isMap(doc.contents)) return { ok: false, problems: [{ code: 'yaml_not_map', line: lineAt(doc.contents?.range?.[0]) ?? 1 }] }
  return { ok: true, card: { text, doc, lines } }
}

// -- writing ---------------------------------------------------------------------------------------------------------

/**
 * How this author writes YAML, so that the lines the editor writes look like the ones around them: the indent, and
 * whether a list under a key is indented (`requests:\n  - id:`) or not (`requests:\n- id:`).
 *
 * ⚠️ `lineWidth: 0`: the library folds long strings at 80 characters by default, which rewrote every long path
 * of a card on the first change.
 */
export function writingOf(text: string): ToStringOptions {
  const rows = text.split('\n')
  let indentSeq = true
  let indent = 2
  let found = false
  for (let index = 0; index < rows.length - 1 && !found; index += 1) {
    const head = /^( *)[^\s#-][^#]*:\s*(#.*)?$/.exec(rows[index])
    if (!head) continue
    const next = rows.slice(index + 1).find((row) => row.trim() && !row.trim().startsWith('#'))
    if (!next) break
    const own = head[1].length
    const deeper = /^( *)/.exec(next)![1].length
    if (/^ *- /.test(next) || /^ *-$/.test(next)) {
      indentSeq = deeper > own
      if (deeper > own) indent = deeper - own
      found = true
    } else if (deeper > own) {
      indent = deeper - own
    }
  }
  const padded = (text.match(/[{[] [^\s}\]]/g) ?? []).length
  const tight = (text.match(/[{[][^\s}\]]/g) ?? []).length
  return {
    indent: Math.min(Math.max(indent, 1), 8),
    indentSeq,
    lineWidth: 0,
    minContentWidth: 0,
    flowCollectionPadding: padded > tight,
  }
}

/** One stretch of lines that differs: `a[aStart, aEnd)` became `b[bStart, bEnd)`. */
interface Hunk {
  aStart: number
  aEnd: number
  bStart: number
  bEnd: number
}

/** Beyond this many differing lines the careful way is not worth it, and the document is written out whole. */
const MOST_EDITS = 2000

/** The lines that differ between two texts (Myers' algorithm), or `null` when they differ too much. */
export function diffLines(a: readonly string[], b: readonly string[]): Hunk[] | null {
  // Equal at both ends is the common case and costs nothing to take off first.
  let head = 0
  while (head < a.length && head < b.length && a[head] === b[head]) head += 1
  let tail = 0
  while (tail < a.length - head && tail < b.length - head && a[a.length - 1 - tail] === b[b.length - 1 - tail]) tail += 1
  const n = a.length - head - tail
  const m = b.length - head - tail
  if (n === 0 && m === 0) return []
  if (n === 0 || m === 0) return [{ aStart: head, aEnd: head + n, bStart: head, bEnd: head + m }]

  const max = n + m
  const offset = max
  let v = new Int32Array(2 * max + 2)
  const trace: Int32Array[] = []
  let done = -1
  for (let d = 0; d <= Math.min(max, MOST_EDITS); d += 1) {
    trace.push(v.slice())
    for (let k = -d; k <= d; k += 2) {
      let x = k === -d || (k !== d && v[offset + k - 1] < v[offset + k + 1]) ? v[offset + k + 1] : v[offset + k - 1] + 1
      let y = x - k
      while (x < n && y < m && a[head + x] === b[head + y]) {
        x += 1
        y += 1
      }
      v[offset + k] = x
      if (x >= n && y >= m) {
        done = d
        break
      }
    }
    if (done >= 0) break
  }
  if (done < 0) return null

  // Walk back through the trace and collect the steps that are not a match.
  const steps: ('a' | 'b')[] = []
  const matches: [number, number][] = []
  let x = n
  let y = m
  for (let d = done; d > 0; d -= 1) {
    v = trace[d]
    const k = x - y
    const fromBelow = k === -d || (k !== d && v[offset + k - 1] < v[offset + k + 1])
    const prevK = fromBelow ? k + 1 : k - 1
    const prevX = v[offset + prevK]
    const prevY = prevX - prevK
    while (x > prevX && y > prevY) {
      x -= 1
      y -= 1
      matches.push([x, y])
    }
    steps.push(fromBelow ? 'b' : 'a')
    x = prevX
    y = prevY
  }
  while (x > 0 && y > 0) {
    x -= 1
    y -= 1
    matches.push([x, y])
  }
  matches.reverse()

  // Between two matches lies a hunk.
  const hunks: Hunk[] = []
  let ai = 0
  let bi = 0
  for (const [ma, mb] of [...matches, [n, m] as [number, number]]) {
    if (ma > ai || mb > bi) hunks.push({ aStart: head + ai, aEnd: head + ma, bStart: head + bi, bEnd: head + mb })
    ai = ma + 1
    bi = mb + 1
  }
  return hunks
}

/**
 * Three texts merged line by line: `ours` is the author's text, `base` the same document as the library writes it,
 * `theirs` the changed document as the library writes it. What the author wrote differently from the library stays,
 * the change comes in; where both touch the same lines, the change wins there. `null` when the texts differ too much.
 */
export function mergeLines(base: string, ours: string, theirs: string): string | null {
  const a = base.split('\n')
  const o = ours.split('\n')
  const t = theirs.split('\n')
  const fromOurs = diffLines(a, o)
  const fromTheirs = diffLines(a, t)
  if (!fromOurs || !fromTheirs) return null

  type Side = { hunk: Hunk; lines: string[]; theirs: boolean }
  const all: Side[] = [
    ...fromOurs.map((hunk) => ({ hunk, lines: o, theirs: false })),
    ...fromTheirs.map((hunk) => ({ hunk, lines: t, theirs: true })),
  ].sort((one, two) => one.hunk.aStart - two.hunk.aStart || one.hunk.aEnd - two.hunk.aEnd)

  const out: string[] = []
  let at = 0
  let index = 0
  while (index < all.length) {
    // A region is every hunk that overlaps the first one. Lines inserted right beside a changed line count as
    // overlapping, so that a line written by the library never lands beside one the author indented differently;
    // two changed lines that only touch stay apart.
    const inserts = (hunk: Hunk) => hunk.aStart === hunk.aEnd
    const region = [all[index]]
    let end = all[index].hunk.aEnd
    let endInserts = inserts(all[index].hunk)
    index += 1
    while (index < all.length) {
      const next = all[index].hunk
      if (!(next.aStart < end || (next.aStart === end && (endInserts || inserts(next))))) break
      region.push(all[index])
      if (next.aEnd >= end) {
        endInserts = next.aEnd === end ? endInserts || inserts(next) : inserts(next)
        end = next.aEnd
      }
      index += 1
    }
    const start = region[0].hunk.aStart
    out.push(...a.slice(at, start))
    const winner = region.some((one) => one.theirs) ? region.filter((one) => one.theirs) : region
    let cursor = start
    for (const { hunk, lines } of winner) {
      out.push(...a.slice(cursor, hunk.aStart), ...lines.slice(hunk.bStart, hunk.bEnd))
      cursor = hunk.aEnd
    }
    out.push(...a.slice(cursor, end))
    at = end
  }
  out.push(...a.slice(at))
  return out.join('\n')
}

/**
 * The card after `change`, with every line the change does not touch exactly as it was (KARTEN-10 AC-4).
 *
 * ⚠️ The merged text is read back and must write out exactly like the changed document; if it does not (a line the
 * author indented differently next to a new one, say), the changed document is taken as the library writes it. Correct
 * first, tidy second.
 */
export function changeCard(card: CardDoc, change: (doc: Document.Parsed) => void): CardDoc {
  const options = writingOf(card.text)
  const base = card.doc.toString(options)
  const next = card.doc.clone()
  change(next)
  const theirs = next.toString(options)
  if (theirs === base) return card
  const merged = mergeLines(base, card.text, theirs)
  if (merged !== null) {
    const again = parseCard(merged)
    if (again.ok && again.card.doc.toString(options) === theirs) return again.card
  }
  const plain = parseCard(theirs)
  if (!plain.ok) throw new Error('The changed card does not read back.')
  return plain.card
}

// -- reading and changing by path ------------------------------------------------------------------------------------

function nodeAt(doc: Document, path: CardPath): unknown {
  return path.length === 0 ? doc.contents : doc.getIn(path as (string | number)[], true)
}

/** The part at `path` as plain data (strings, numbers, lists, objects), `undefined` when there is none. */
export function readAt(card: CardDoc, path: CardPath): unknown {
  const node = nodeAt(card.doc, path)
  if (node === undefined || node === null) return node ?? undefined
  return isNode(node) ? (node as Node).toJS(card.doc) : node
}

/**
 * Set the part at `path`. Maps on the way that are missing are made. A plain value over a plain value keeps the
 * node, so its comment and its quotes stay (KARTEN-10 EC-1).
 */
export function setAt(doc: Document, path: CardPath, value: unknown): void {
  if (path.length === 0) throw new Error('A card is always a map; set a part of it.')
  // ⚠️ A plain value goes in as it is: the map then puts it into the scalar that stands there. Made into a node first,
  // it would replace that scalar and lose its quotes and its comment.
  const plain = value === null || typeof value !== 'object'
  doc.setIn(path as (string | number)[], plain || isNode(value) ? value : doc.createNode(value))
}

/** Remove the part at `path`, and the comment above it with it (KARTEN-10 EC-2). Nothing happens when it is missing. */
export function deleteAt(doc: Document, path: CardPath): void {
  if (path.length === 0) return
  if (doc.hasIn(path as (string | number)[])) doc.deleteIn(path as (string | number)[])
}

/**
 * A value written short (`value: queue.total`) becomes its long form (`value: {path: queue.total}`), so that a label
 * or a unit can be set on it. A value already long stays as it is.
 */
export function expandValueRef(doc: Document, path: CardPath): void {
  const node = nodeAt(doc, path)
  if (isScalar(node) && typeof node.value === 'string') {
    const map = doc.createNode({ path: node.value })
    if (node.commentBefore) map.commentBefore = node.commentBefore
    if (node.comment) map.comment = node.comment
    doc.setIn(path as (string | number)[], map)
  }
}

/** The line a part starts on, its key's line for a field; `null` when it is not there. */
export function lineOf(card: CardDoc, path: CardPath): number | null {
  if (path.length === 0) return 1
  const parent = nodeAt(card.doc, path.slice(0, -1))
  const last = path[path.length - 1]
  let start: number | undefined
  if (isMap(parent)) {
    const pair = parent.items.find((item) => (isScalar(item.key) ? item.key.value : item.key) === last)
    start = isNode(pair?.key) ? (pair.key as Node).range?.[0] : undefined
  } else if (isSeq(parent) && typeof last === 'number') {
    const item = parent.items[last]
    start = isNode(item) ? (item as Node).range?.[0] : undefined
  }
  return start === undefined ? null : card.lines.linePos(start).line
}

// -- what the editor shows -------------------------------------------------------------------------------------------

/**
 * What the editor has fields for. `any` takes the part whole (a text in several languages, the demo answers);
 * `keys` a map with these keys (`scalar`: or a plain value, the short form of a value); `items` a list of such
 * parts; `test` a plain value the editor can show only in some forms.
 */
export type Shown =
  | 'any'
  | { keys: Record<string, Shown>; scalar?: boolean }
  | { items: Shown }
  | { test: (value: unknown) => boolean }

/** A path written plainly (`data.items`, `records[0]`, `"a b".c`), which the Look step picks from the data tree. */
export const PLAIN_PATH = /^(@|[A-Za-z_][\w-]*|"[^"]+")(\.([A-Za-z_][\w-]*|"[^"]+")|\[\d+\])*$/

const RULE: Shown = { keys: { value: 'any', formula: 'any', op: 'any', than: 'any', then: 'any' } }
const ROWS: Shown = {
  keys: {
    select: { test: (value) => typeof value === 'string' && PLAIN_PATH.test(value.trim()) },
    filter: { items: { keys: { field: 'any', op: 'any', value: 'any' } } },
    sort: { keys: { field: 'any', desc: 'any' } },
    limit: 'any',
  },
}
const VALUE: Shown = {
  scalar: true,
  keys: {
    path: 'any',
    formula: 'any',
    template: 'any',
    total: { keys: { fn: 'any', rows: ROWS, field: 'any' } },
    label: 'any',
    unit: 'any',
    format: 'any',
    digits: 'any',
    rules: { items: RULE },
  },
}

/**
 * Everything the editor of this version shows. A step that learns a new part adds it here; whatever is not here
 * is shown as "Adjusted in YAML" and is saved as it stands (KARTEN-9 AC-12).
 */
export const EDITOR_SHOWS: Shown = {
  keys: {
    'nexdeck-card': 'any',
    slug: 'any',
    name: 'any',
    version: 'any',
    min_nexdeck: 'any',
    author: 'any',
    description: 'any',
    category: 'any',
    requires: 'any',
    requests: { items: { keys: { id: 'any', path: 'any', every: 'any' } } },
    rules: { items: RULE },
    demo: 'any',
    size: 'any',
    min_size: 'any',
    form: 'any',
    value: VALUE,
    stats: { items: VALUE },
    rows: ROWS,
    item: { keys: { title: VALUE, subtitle: VALUE, value: VALUE, status: { items: RULE }, link: VALUE, image: VALUE } },
    empty: 'any',
  },
}

/** A part of the card the editor has no field for. */
export interface AdjustedPart {
  path: CardPath
  line: number | null
}

/** The parts of the card that only the YAML view shows (KARTEN-9 AC-12), in the order they stand. */
export function adjustedInYaml(card: CardDoc, shows: Shown = EDITOR_SHOWS): AdjustedPart[] {
  const found: AdjustedPart[] = []
  const walk = (node: unknown, shown: Shown, path: (string | number)[]) => {
    if (shown === 'any') return
    if ('test' in shown) {
      const value = isNode(node) ? (node as Node).toJS(card.doc) : node
      if (!shown.test(value)) found.push({ path, line: lineOf(card, path) })
      return
    }
    if ('items' in shown) {
      if (isSeq(node)) node.items.forEach((item, index) => walk(item, shown.items, [...path, index]))
      return
    }
    if (isMap(node)) {
      for (const pair of node.items) {
        const key = isScalar(pair.key) ? pair.key.value : pair.key
        if (typeof key !== 'string' && typeof key !== 'number') continue
        const inner = shown.keys[String(key)]
        if (inner === undefined) found.push({ path: [...path, key], line: lineOf(card, [...path, key]) })
        else walk(pair.value, inner, [...path, key])
      }
    }
    // Anything else of the wrong shape is the server's to name; it is not a part the editor leaves alone.
  }
  walk(card.doc.contents, shows, [])
  return found
}

/** A path as people read it: `item.title`, `stats[1].label`. */
export function pathText(path: CardPath): string {
  return path.reduce<string>((text, part) => (typeof part === 'number' ? `${text}[${part}]` : text ? `${text}.${part}` : part), '')
}
