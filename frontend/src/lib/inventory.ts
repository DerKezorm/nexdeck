/**
 * The inventory (roadmap M5): what runs on what, as the server lists it, laid
 * out as a tree for the list and in columns, one per machine, for the map.
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
  /** For a connection that is a machine: what the machine is called (docker-live), not what the connection is called (Portainer). */
  machine?: string
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

/** A service on the map: what hangs on a container, a guest or a host, and whether only proposed. */
export interface Placed {
  node: InventoryNode
  proposed: boolean
  /** App tiles that hang on this connection and need no box of their own. */
  tiles: number
}

/** One container or guest in a column, with what runs in it. */
export interface Slot {
  node: InventoryNode
  services: Placed[]
}

/** One machine: an engine or a hypervisor, with its containers and guests. */
export interface Column {
  host: InventoryNode
  /** What runs straight on the machine, without a container. */
  direct: Placed[]
  slots: Slot[]
  /** Containers and guests nothing is known to run in, left out unless asked for. */
  empty: Slot[]
}

/**
 * The map (agreed on 25.10.2026): one column per machine, its containers and
 * guests below it, and beside each what runs in it. An app tile that hangs on
 * its connection is folded into it; what runs on nothing known stands apart.
 *
 * ⚠️ Measured on a real homelab the day before: 95 boxes in rows, lines from
 * Portainer across all of them, most of the map out of sight.
 */
export function columns(inventory: Inventory): { columns: Column[]; loose: Placed[] } {
  const byRef = new Map(inventory.nodes.map((node) => [node.ref, node]))
  const live = inventory.relations.filter((one) => one.state !== 'rejected' && byRef.has(one.child) && byRef.has(one.parent))
  // A tile on its connection is part of it, not a service of its own.
  const folded = new Map<string, number>()
  const tileOn = new Set<string>()
  for (const one of live) {
    if (one.state === 'on' && byRef.get(one.child)?.kind === 'tile' && byRef.get(one.parent)?.kind === 'integration') {
      folded.set(one.parent, (folded.get(one.parent) ?? 0) + 1)
      tileOn.add(one.child)
    }
  }
  const services = (ref: string): Placed[] =>
    live
      .filter((one) => one.parent === ref && !tileOn.has(one.child))
      .map((one) => ({ node: byRef.get(one.child) as InventoryNode, proposed: one.state === 'suggested', tiles: folded.get(one.child) ?? 0 }))
      .sort((a, b) => Number(a.proposed) - Number(b.proposed) || a.node.name.localeCompare(b.node.name))

  const out: Column[] = []
  const shown = new Set<string>()
  for (const host of inventory.nodes.filter((node) => node.kind === 'integration')) {
    const things = inventory.nodes.filter((node) => node.parent === host.ref)
    const direct = services(host.ref)
    if (things.length === 0 && direct.length === 0) continue
    const slots: Slot[] = []
    const empty: Slot[] = []
    for (const node of things.sort((a, b) => a.name.localeCompare(b.name))) {
      const slot = { node, services: services(node.ref) }
      ;(slot.services.length ? slots : empty).push(slot)
      // A proposal stands where it is proposed, dashed, and not once more among the loose ones.
      for (const one of slot.services) shown.add(one.node.ref)
    }
    for (const one of direct) shown.add(one.node.ref)
    shown.add(host.ref)
    out.push({ host, direct, slots, empty })
  }
  out.sort((a, b) => (a.host.machine || a.host.name).localeCompare(b.host.machine || b.host.name))
  const loose = inventory.nodes
    .filter((node) => (node.kind === 'integration' || node.kind === 'tile') && !shown.has(node.ref) && !tileOn.has(node.ref))
    .map((node) => ({ node, proposed: false, tiles: folded.get(node.ref) ?? 0 }))
    .sort((a, b) => a.node.name.localeCompare(b.node.name))
  return { columns: out, loose }
}
