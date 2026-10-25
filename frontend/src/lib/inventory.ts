/**
 * The inventory (roadmap M5): what runs on what, as the server lists it, laid
 * out as a tree for the list and in rows for the map.
 */

export interface InventoryNode {
  ref: string
  kind: 'integration' | 'tile' | 'container' | 'guest'
  /** The adapter of a connection, such as ``plex``. */
  service: string
  name: string
  detail: string
  image?: string
  state?: string
  /** A host in its own right: a NAS, a hypervisor, a Docker engine. */
  host: boolean
  down: boolean
  /** The engine or hypervisor a container or a guest belongs to. */
  parent?: string
  demo?: boolean
}

export interface InventoryRelation {
  id: number
  child: string
  parent: string
  origin: 'auto' | 'manual' | 'suggested'
  state: 'on' | 'suggested' | 'rejected'
}

export interface Inventory {
  nodes: InventoryNode[]
  relations: InventoryRelation[]
}

export interface Branch {
  node: InventoryNode
  /** The relation that hangs it here; none for a container under its engine. */
  relation?: InventoryRelation
  children: Branch[]
}

/** What hangs directly on ``ref``: its things, and what was found or set to run on it. */
export function childrenOf(inventory: Inventory, ref: string): { node: InventoryNode; relation?: InventoryRelation }[] {
  const byRef = new Map(inventory.nodes.map((node) => [node.ref, node]))
  const out: { node: InventoryNode; relation?: InventoryRelation }[] = []
  for (const node of inventory.nodes) if (node.parent === ref) out.push({ node })
  for (const relation of inventory.relations) {
    const node = byRef.get(relation.child)
    if (relation.parent === ref && relation.state === 'on' && node) out.push({ node, relation })
  }
  return out.sort((a, b) => a.node.name.localeCompare(b.node.name))
}

/** What ``ref`` runs on directly. */
export function parentsOf(inventory: Inventory, ref: string): string[] {
  const own = inventory.nodes.find((node) => node.ref === ref)?.parent
  return [...(own ? [own] : []), ...inventory.relations.filter((one) => one.child === ref && one.state === 'on').map((one) => one.parent)]
}

/** The list: everything that runs on nothing at the top, with what runs on it below; what stands alone apart. */
export function tree(inventory: Inventory): { roots: Branch[]; unplaced: InventoryNode[] } {
  const grow = (node: InventoryNode, relation: InventoryRelation | undefined, path: Set<string>): Branch => ({
    node,
    relation,
    // ⚠️ The path guards against a circle the server refuses anyway: a list must never hang the page.
    children: path.has(node.ref) ? [] : childrenOf(inventory, node.ref).map((one) => grow(one.node, one.relation, new Set([...path, node.ref]))),
  })
  const top = inventory.nodes.filter((node) => parentsOf(inventory, node.ref).length === 0)
  const roots = top.filter((node) => node.host || childrenOf(inventory, node.ref).length > 0).map((node) => grow(node, undefined, new Set()))
  const unplaced = top.filter((node) => !node.host && childrenOf(inventory, node.ref).length === 0 && (node.kind === 'integration' || node.kind === 'tile'))
  return { roots: roots.sort((a, b) => a.node.name.localeCompare(b.node.name)), unplaced: unplaced.sort((a, b) => a.name.localeCompare(b.name)) }
}

export const NODE_WIDTH = 168
export const NODE_HEIGHT = 44
const ROW = 110
const GAP = 24
/** Boxes in one line of the map before it wraps. */
const PER_ROW = 7

/** Rows by how far down the chain each thing sits; what stands alone goes to the last row. */
export function layered(inventory: Inventory): Record<string, [number, number]> {
  const depth = new Map<string, number>()
  const walk = (ref: string, level: number, path: Set<string>) => {
    if (path.has(ref)) return
    if ((depth.get(ref) ?? -1) >= level) return
    depth.set(ref, level)
    for (const child of childrenOf(inventory, ref)) walk(child.node.ref, level + 1, new Set([...path, ref]))
  }
  const { roots, unplaced } = tree(inventory)
  for (const root of roots) walk(root.node.ref, 0, new Set())
  const deepest = Math.max(0, ...depth.values())
  for (const node of unplaced) depth.set(node.ref, deepest + 1)
  const rows = new Map<number, string[]>()
  for (const node of inventory.nodes) {
    const level = depth.get(node.ref)
    if (level === undefined) continue
    rows.set(level, [...(rows.get(level) ?? []), node.ref])
  }
  // Row by row from the top, each box under the middle of what it runs on, so
  // the lines do not cross; a long row wraps onto a second line of its own.
  const out: Record<string, [number, number]> = {}
  let y = GAP
  for (const level of [...rows.keys()].sort((a, b) => a - b)) {
    const under = (ref: string) => {
      const xs = parentsOf(inventory, ref).map((one) => out[one]?.[0]).filter((x): x is number => x !== undefined)
      return xs.length ? xs.reduce((sum, x) => sum + x, 0) / xs.length : Number.MAX_SAFE_INTEGER
    }
    const refs = (rows.get(level) ?? []).sort((a, b) => under(a) - under(b))
    const placed = refs.filter((ref) => under(ref) !== Number.MAX_SAFE_INTEGER)
    const loose = refs.filter((ref) => under(ref) === Number.MAX_SAFE_INTEGER)
    if (placed.length) {
      // Under the middle of its parents, pushed right only as far as the box before it needs.
      let next = GAP
      for (const ref of placed) {
        const x = Math.max(next, under(ref))
        out[ref] = [x, y]
        next = x + NODE_WIDTH + GAP
      }
      y += ROW
    }
    for (let at = 0; at < loose.length; at += PER_ROW) {
      loose.slice(at, at + PER_ROW).forEach((ref, index) => (out[ref] = [GAP + index * (NODE_WIDTH + GAP), y]))
      y += ROW
    }
  }
  return out
}
