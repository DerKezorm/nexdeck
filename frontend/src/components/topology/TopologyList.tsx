import { useTranslation } from 'react-i18next'

import type { TopoLink } from '../../lib/topology'
import type { PlanNode } from './TopologyCanvas'
import { ICONS } from './TopologyCanvas'
import type { Words } from './words'

/**
 * The plan on a phone: the same tree as an indented list, each device with the
 * traffic on the line it hangs on. A plan of twenty cards is too small to read
 * at that width, and too fiddly to touch.
 */
export function TopologyList({ nodes, links, words, ageOf, onPick }: { nodes: PlanNode[]; links: TopoLink[]; words: Words; ageOf: (link: TopoLink) => number | null; onPick: (id: string) => void }) {
  const { t } = useTranslation()
  const present = new Set(nodes.map((node) => node.id))
  const uplink = new Map<string, TopoLink>()
  const kids = new Map<string, string[]>()
  for (const link of links) {
    if (!present.has(link.a) || !present.has(link.b)) continue
    uplink.set(link.b, link)
    kids.set(link.a, [...(kids.get(link.a) ?? []), link.b])
  }
  const byId = new Map(nodes.map((node) => [node.id, node]))
  const rows: { node: PlanNode; depth: number }[] = []
  const seen = new Set<string>()
  const walk = (id: string, depth: number) => {
    const node = byId.get(id)
    if (!node || seen.has(id)) return
    seen.add(id)
    rows.push({ node, depth })
    for (const child of kids.get(id) ?? []) walk(child, depth + 1)
  }
  for (const node of nodes) if (!uplink.has(node.id)) walk(node.id, 0)
  for (const node of nodes) walk(node.id, 0)

  return (
    <ul className="grid gap-1.5" aria-label={t('topology.plan')} data-topology-list>
      {rows.map(({ node, depth }) => {
        const Icon = ICONS[node.kind === 'client' ? (node.clientKind ?? 'other') : node.kind] ?? ICONS.other
        const link = uplink.get(node.id)
        const offline = node.status === 'offline'
        return (
          <li key={node.id} style={{ paddingLeft: Math.min(depth, 6) * 14 }}>
            <button type="button" className="w-full text-left glass rounded-xl px-3 py-2.5 flex items-center gap-3" onClick={() => onPick(node.id)}>
              <span className={`w-9 h-9 rounded-lg grid place-items-center shrink-0 ${offline ? 'text-bad' : 'bg-accent-soft text-accent'}`}>
                <Icon size={18} />
              </span>
              <span className="min-w-0 flex-1 grid">
                <span className="text-[13.5px] font-semibold break-words">{node.name}</span>
                <span className="text-xs text-muted break-words">{node.sub}</span>
                {link && (
                  <span className="text-xs font-mono mt-0.5 flex flex-wrap gap-x-3">
                    {link.state === 'down' ? (
                      <span className="text-bad">{t('topology.disconnected')}</span>
                    ) : (
                      <>
                        <span className="text-accent">▼ {words.bits(link.down)}</span>
                        <span style={{ color: 'var(--nd-c-violet)' }}>▲ {words.bits(link.up)}</span>
                        <span className="text-faint">{words.ago(ageOf(link))}</span>
                      </>
                    )}
                  </span>
                )}
              </span>
              <span className={`w-2 h-2 rounded-full shrink-0 ${offline ? 'bg-bad' : 'bg-ok'}`} aria-hidden="true" />
            </button>
          </li>
        )
      })}
    </ul>
  )
}
