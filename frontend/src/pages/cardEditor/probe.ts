/**
 * The answer of a probe (KARTEN-9 AC-3, EC-1) as the server sends it, and what the editor reads from it: the nodes
 * shown, the lists in it, the fields of one row, and whether a path finds anything.
 *
 * ⚠️ A probe holds the service's own data. It lives in this tab only, in the editor's memory: never in the draft in
 * the browser, never in the card (EC-4). Only "Use this answer as demo data" makes data of it, disguised (AC-10).
 */

export type ProbeType = 'object' | 'array' | 'string' | 'number' | 'bool' | 'null'

/** One node of the tree. `path` is a JMESPath from the top of the answer, `@` for the top itself. */
export interface ProbeNode {
  key: string | number | null
  path: string
  type: ProbeType
  value?: string | number | boolean | null
  children?: ProbeNode[]
  /** How many entries of this list or fields of this object were left out (EC-1). */
  more?: number
  /** A text cut to 200 characters. */
  truncated?: boolean
}

export interface ProbeAnswer {
  tree: ProbeNode
  nodes: number
  cut: boolean
}

/** A probe of one request: under way, answered, or failed with the reason a card would show (EC-2). */
export type ProbeState =
  | { status: 'loading'; path: string }
  | { status: 'done'; path: string; integrationId: number; answer: ProbeAnswer }
  | { status: 'failed'; path: string; code: string; message: string; hint?: string }

/** Every node, depth first, in the order the tree shows them. */
export function everyNode(tree: ProbeNode): ProbeNode[] {
  const found: ProbeNode[] = []
  const walk = (node: ProbeNode) => {
    found.push(node)
    node.children?.forEach(walk)
  }
  walk(tree)
  return found
}

/** The lists of the answer, the top first: what rows of a list or a wall of pictures can come from (AC-5). */
export function listsOf(tree: ProbeNode): ProbeNode[] {
  return everyNode(tree).filter((node) => node.type === 'array')
}

/**
 * The fields of one row of a list, as paths inside the row (`series.title`), the row itself as `@` when the rows are
 * plain values. Read from the rows shown, so a field only some rows have is offered as well.
 */
export function rowFieldsOf(list: ProbeNode): { path: string; type: ProbeType; value?: ProbeNode['value'] }[] {
  const found = new Map<string, { path: string; type: ProbeType; value?: ProbeNode['value'] }>()
  for (const row of list.children ?? []) {
    const prefix = row.path
    for (const node of everyNode(row)) {
      if (node === row && row.type !== 'object' && row.type !== 'array') {
        if (!found.has('@')) found.set('@', { path: '@', type: node.type, value: node.value })
        continue
      }
      if (node === row || node.type === 'object') continue
      // A list inside a row is a field too (its length can be counted), its own rows are not.
      const inner = node.path.slice(prefix.length).replace(/^\./, '')
      if (/\[\d+\]/.test(inner)) continue
      if (!found.has(inner)) found.set(inner, { path: inner, type: node.type, value: node.value })
    }
  }
  return [...found.values()]
}

/** The nearest list a node is a row of, or lies inside a row of; `null` for a node outside every list. */
export function enclosingList(tree: ProbeNode, target: ProbeNode): ProbeNode | null {
  let found: ProbeNode | null = null
  const walk = (node: ProbeNode, lists: ProbeNode[]): boolean => {
    if (node === target) {
      found = lists[lists.length - 1] ?? null
      return true
    }
    const inside = node.type === 'array' ? [...lists, node] : lists
    return (node.children ?? []).some((child) => walk(child, inside))
  }
  walk(tree, [])
  return found
}

/** The node at a path the server wrote, if the tree shows it. */
export function nodeAt(tree: ProbeNode, path: string): ProbeNode | null {
  return everyNode(tree).find((node) => node.path === path) ?? null
}

/**
 * Whether a plain path (`records[0].series.title`, `"a b".c`, `@`) leads to a node of the tree, inside `from`.
 * `null` when it cannot tell: the path is an expression, or it runs into a part the tree left out.
 */
export function pathFinds(from: ProbeNode, path: string): boolean | null {
  const parts = splitPath(path)
  if (parts === null) return null
  let node: ProbeNode = from
  for (const part of parts) {
    const children = node.children ?? []
    const next = children.find((child) => child.key === part)
    if (next) {
      node = next
      continue
    }
    // Left out of a long list or a wide object: not known to be missing.
    if (node.more) return null
    return false
  }
  return true
}

const NAME = /^[A-Za-z_][\w]*/
const QUOTED = /^"((?:[^"\\]|\\.)*)"/

/** A plain path split into its names and positions; `null` for anything that is more than a path. */
export function splitPath(path: string): (string | number)[] | null {
  let rest = path.trim()
  if (rest === '@' || rest === '') return []
  const parts: (string | number)[] = []
  let first = true
  while (rest) {
    const index = /^\[(\d+)\]/.exec(rest)
    if (index) {
      parts.push(Number(index[1]))
      rest = rest.slice(index[0].length)
      first = false
      continue
    }
    if (!first) {
      if (!rest.startsWith('.')) return null
      rest = rest.slice(1)
    }
    const quoted = QUOTED.exec(rest)
    const name = quoted ? null : NAME.exec(rest)
    if (quoted) {
      try {
        parts.push(JSON.parse(quoted[0]) as string)
      } catch {
        return null
      }
      rest = rest.slice(quoted[0].length)
    } else if (name) {
      parts.push(name[0])
      rest = rest.slice(name[0].length)
    } else {
      return null
    }
    first = false
  }
  return parts
}

/** The answer as plain data again, as far as the tree shows it. */
export function valueOf(node: ProbeNode): unknown {
  if (node.type === 'object') return Object.fromEntries((node.children ?? []).map((child) => [String(child.key), valueOf(child)]))
  if (node.type === 'array') return (node.children ?? []).map(valueOf)
  return node.value ?? null
}
