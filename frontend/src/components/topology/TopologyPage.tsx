import { useQuery } from '@tanstack/react-query'
import { Check, Inbox, Monitor, Network, Plus, Settings2, SlidersHorizontal } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, get, put } from '../../api/client'
import {
  freeSpot,
  pathUp,
  treeLayout,
  utilisation,
  type TopoAnswer,
  type TopoLayout,
  type TopoLink,
  type TopoNode,
} from '../../lib/topology'
import { Dialog, Spinner } from '../ui'
import { cardWidth, LABEL_FONT, textWidth, TopologyCanvas, type FlowMode, type LabelMode, type PlanNode, type Selection } from './TopologyCanvas'
import { ClientRow, FoundPanel, LinkPanel, NodePanel, type FoundItem } from './TopologyPanel'
import { TopologyList } from './TopologyList'
import { useWords } from './words'

interface Props {
  pageId: number
  editing: boolean
  canEdit: boolean
  onAddPage: () => void
  onSettings: () => void
  onDone: () => void
}

interface View {
  straight: boolean
  flow: FlowMode
  labels: LabelMode
}

const VIEW_KEY = 'nexdeck.topology.view'
const DEFAULT_VIEW: View = { straight: false, flow: 'dots', labels: 'all' }
/** How often the browser asks; the server reads the console at most every ten seconds anyway. */
const POLL_MS = 10_000

function readView(): View {
  try {
    const stored = JSON.parse(localStorage.getItem(VIEW_KEY) ?? '{}') as Partial<View>
    return {
      straight: typeof stored.straight === 'boolean' ? stored.straight : DEFAULT_VIEW.straight,
      flow: stored.flow === 'dashes' || stored.flow === 'still' || stored.flow === 'dots' ? stored.flow : DEFAULT_VIEW.flow,
      labels: stored.labels === 'load' || stored.labels === 'off' || stored.labels === 'all' ? stored.labels : DEFAULT_VIEW.labels,
    }
  } catch {
    return DEFAULT_VIEW
  }
}

function useNarrow(): boolean {
  const query = '(max-width: 639px)'
  const [narrow, setNarrow] = useState(() => window.matchMedia?.(query)?.matches ?? false)
  useEffect(() => {
    const list = window.matchMedia?.(query)
    if (!list) return
    const change = () => setNarrow(list.matches)
    list.addEventListener?.('change', change)
    return () => list.removeEventListener?.('change', change)
  }, [])
  return narrow
}

/**
 * A topology page: the network of one UniFi connection as a plan. Every
 * network device stands on it from the start; clients join one by one, and
 * devices UniFi reports later wait under "Found". The arrangement belongs to
 * the page and is saved for everyone; how it is drawn belongs to the browser.
 */
export function TopologyPage({ pageId, editing, canEdit, onAddPage, onSettings, onDone }: Props) {
  const { t } = useTranslation()
  const words = useWords()
  const narrow = useNarrow()
  const answer = useQuery({
    queryKey: ['topology', pageId],
    queryFn: () => get<TopoAnswer>(`/pages/${pageId}/topology`),
    refetchInterval: POLL_MS,
  })
  const receivedAt = answer.dataUpdatedAt
  const data = answer.data?.data ?? null
  const problem = answer.data?.problem ?? null

  // -- the arrangement, saved a moment after the last change ------------------

  const [layout, setLayout] = useState<TopoLayout | null>(null)
  const version = useRef(0)
  const timer = useRef<number | undefined>(undefined)
  const waiting = useRef<TopoLayout | null>(null)
  const [note, setNote] = useState<{ text: string; undo?: () => void; level?: 'error' } | null>(null)
  const clearNote = useCallback(() => setNote(null), [])

  useEffect(() => {
    const server = answer.data
    if (!server) return
    // ⚠️ Not over a change of our own still waiting to be saved; and only a
    // version that moved on, or the first one. See ``put_layouts`` for why a
    // browser keeps the version it last saw.
    if (waiting.current) return
    if (layout === null || server.version > version.current) {
      version.current = server.version
      setLayout(server.layout)
    }
  }, [answer.data, layout])

  // Stable for the life of the query, so ``flush`` stays the same function.
  const refetch = answer.refetch
  // ⚠️ One save at a time: a second change while the first save was still on
  // its way carried the same version, was refused as somebody else's, and the
  // page dropped the change it had just made (found on the home page first).
  const inflight = useRef<Promise<void>>(Promise.resolve())
  const flush = useCallback(() => {
    const run = inflight.current.then(async () => {
      const next = waiting.current
      if (!next) return
      window.clearTimeout(timer.current)
      try {
        const saved = await put<{ layout: TopoLayout; version: number }>(`/pages/${pageId}/topology`, {
          placed: next.placed, clients: next.clients, hidden: next.hidden, positions: next.positions, version: version.current,
        })
        if (waiting.current === next) waiting.current = null
        version.current = saved.version
      } catch (failure) {
        waiting.current = null
        if (failure instanceof ApiError && failure.status === 409) {
          setNote({ text: t('topology.movedOn') })
          version.current = 0
          setLayout(null)
          void refetch()
        } else setNote({ text: t('topology.saveFailed'), level: 'error' })
      }
    })
    inflight.current = run
    return run
  }, [pageId, t, refetch])

  const save = useCallback(
    (next: TopoLayout, at = 500) => {
      setLayout(next)
      if (!canEdit) return
      waiting.current = next
      window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => void flush(), at)
    },
    [canEdit, flush],
  )
  // What waits is saved when the page goes, not lost.
  useEffect(() => () => void flush(), [flush])

  // -- a clock for the ages ----------------------------------------------------

  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const tick = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(tick)
  }, [])
  const ageOf = useCallback((link: TopoLink) => (link.age === null ? null : link.age + Math.max(0, now - receivedAt) / 1000), [now, receivedAt])

  // -- what stands on the plan --------------------------------------------------

  const nodeById = useMemo(() => new Map((data?.nodes ?? []).map((node) => [node.id, node])), [data])
  const clientById = useMemo(() => new Map((data?.clients ?? []).map((client) => [client.id, client])), [data])
  const wiredAt = useMemo(() => {
    const count = new Map<string, number>()
    for (const client of data?.clients ?? []) count.set(client.at, (count.get(client.at) ?? 0) + 1)
    return count
  }, [data])

  const shown = useMemo(() => {
    if (!data || !layout) return { nodes: [] as TopoNode[], links: [] as TopoLink[] }
    const placed = new Set(layout.placed.filter((id) => nodeById.has(id)))
    const nodes: TopoNode[] = data.nodes.filter((node) => placed.has(node.id))
    for (const id of layout.clients) {
      const client = clientById.get(id)
      if (!client || !placed.has(client.at)) continue
      nodes.push({
        id: client.id, name: client.name, model: client.ip ? `${t('topology.client')} · ${client.ip}` : t('topology.client'),
        kind: 'client', client_kind: client.kind, status: nodeById.get(client.at)?.status ?? 'ok', every: null, facts: { ip: client.ip },
      })
    }
    const on = new Set(nodes.map((node) => node.id))
    const links = [...data.links, ...data.client_links].filter((link) => on.has(link.a) && on.has(link.b))
    return { nodes, links }
  }, [data, layout, nodeById, clientById, t])

  // ⚠️ Measured with the page's own fonts: before they arrive the canvas measures a fallback
  // that is narrower, and the second line of a card ended in "…".
  const [fonts, setFonts] = useState(() => (typeof document === 'undefined' || !document.fonts ? true : document.fonts.status === 'loaded'))
  useEffect(() => {
    if (fonts || typeof document === 'undefined' || !document.fonts) return
    let gone = false
    void document.fonts.ready.then(() => !gone && setFonts(true))
    return () => {
      gone = true
    }
  }, [fonts])
  const widths = useMemo(() => {
    const out = new Map<string, number>()
    for (const node of shown.nodes) out.set(node.id, cardWidth(node.name, words.sub(node, wiredAt.get(node.id) ?? 0)))
    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps -- ``fonts`` is why it is measured again
  }, [shown.nodes, words, wiredAt, fonts])
  const widthOf = useCallback((id: string) => widths.get(id) ?? 150, [widths])

  // Devices without a place get one: the whole tree on a new page, a free spot
  // under their parent later. Saved only by someone who may edit.
  const positions = useMemo(() => {
    const kept = { ...(layout?.positions ?? {}) }
    const missing = shown.nodes.filter((node) => !kept[node.id])
    if (missing.length === 0) return kept
    if (missing.length === shown.nodes.length) return treeLayout(shown.nodes.map((node) => node.id), shown.links, widthOf)
    for (const node of missing) {
      const up = shown.links.find((link) => link.b === node.id)
      const parent = up ? kept[up.a] : undefined
      const taken = Object.entries(kept).map(([id, [x, y]]) => ({ x, y, w: widthOf(id) }))
      kept[node.id] = freeSpot(parent ?? [120, 100], taken, widthOf(node.id))
    }
    return kept
  }, [layout, shown, widthOf])
  useEffect(() => {
    if (!layout) return
    // ``save`` writes only for someone who may edit; for everyone else it only draws.
    if (shown.nodes.some((node) => !layout.positions[node.id])) save({ ...layout, positions }, 1500)
  }, [positions, layout, shown.nodes, save])

  const [dragged, setDragged] = useState<{ id: string; x: number; y: number } | null>(null)
  const planNodes: PlanNode[] = useMemo(
    () =>
      shown.nodes.map((node) => {
        const [x, y] = dragged?.id === node.id ? [dragged.x, dragged.y] : (positions[node.id] ?? [0, 0])
        return {
          id: node.id, name: node.name, sub: words.sub(node, wiredAt.get(node.id) ?? 0), kind: node.kind, clientKind: node.client_kind,
          status: node.status, x, y, w: widthOf(node.id),
        }
      }),
    [shown.nodes, positions, dragged, words, wiredAt, widthOf],
  )

  // -- found and put away --------------------------------------------------------

  const foundItems = useMemo(() => {
    if (!data || !layout) return { found: [] as FoundItem[], hidden: [] as FoundItem[] }
    const placed = new Set(layout.placed)
    const hidden = new Set(layout.hidden)
    const item = (node: TopoNode): FoundItem => {
      const link = data.links.find((one) => one.b === node.id)
      return { node, link, parent: link ? nodeById.get(link.a) : undefined }
    }
    const off = data.nodes.filter((node) => !placed.has(node.id))
    return { found: off.filter((node) => !hidden.has(node.id)).map(item), hidden: off.filter((node) => hidden.has(node.id)).map(item) }
  }, [data, layout, nodeById])

  // -- selection -------------------------------------------------------------------

  const [selected, setSelected] = useState<Selection | { type: 'found' }>(null)
  const [showHidden, setShowHidden] = useState(false)
  const lit = useMemo(() => {
    if (!selected || selected.type === 'found') return null
    if (selected.type === 'link') {
      const link = shown.links.find((one) => one.id === selected.id)
      return link ? { nodes: new Set([link.a, link.b]), links: new Set([link.id]) } : null
    }
    const way = pathUp(selected.id, shown.links)
    const nodes = new Set(way.nodes)
    const links = new Set(way.links)
    for (const link of shown.links) {
      if (link.a === selected.id || link.b === selected.id) {
        links.add(link.id)
        nodes.add(link.a)
        nodes.add(link.b)
      }
    }
    return { nodes, links }
  }, [selected, shown.links])

  const nameOf = useCallback((id: string) => nodeById.get(id)?.name ?? clientById.get(id)?.name ?? (id === 'internet' ? 'Internet' : id), [nodeById, clientById])

  // -- changing the plan -------------------------------------------------------------

  const taken = () => planNodes.map((node) => ({ x: node.x, y: node.y, w: node.w }))
  const place = (id: string) => {
    if (!layout || !data) return
    const link = data.links.find((one) => one.b === id)
    const parent = link ? positions[link.a] : undefined
    if (link && !parent) {
      setNote({ text: t('topology.parentMissing', { name: nameOf(id), parent: nameOf(link.a) }) })
      return
    }
    const node = nodeById.get(id)
    const spot = freeSpot(parent ?? [120, 100], taken(), node ? cardWidth(node.name, words.sub(node, wiredAt.get(id) ?? 0)) : 150)
    save({ ...layout, placed: [...layout.placed, id], hidden: layout.hidden.filter((one) => one !== id), positions: { ...positions, [id]: spot } })
    setNote({ text: link ? t('topology.placed', { name: nameOf(id), parent: nameOf(link.a) }) : t('topology.placedAlone', { name: nameOf(id) }) })
  }
  const addClient = (id: string) => {
    const client = clientById.get(id)
    if (!layout || !client) return
    const parent = positions[client.at]
    if (!parent) {
      setNote({ text: t('topology.parentMissing', { name: client.name, parent: nameOf(client.at) }) })
      return
    }
    const spot = freeSpot(parent, taken(), cardWidth(client.name, client.ip ? `${t('topology.client')} · ${client.ip}` : t('topology.client')))
    save({ ...layout, clients: [...layout.clients, id], positions: { ...positions, [id]: spot } })
    setNote({ text: t('topology.placed', { name: client.name, parent: nameOf(client.at) }) })
  }
  const remove = (id: string) => {
    if (!layout) return
    const client = clientById.has(id) && layout.clients.includes(id)
    const { [id]: _gone, ...rest } = positions
    save(client ? { ...layout, clients: layout.clients.filter((one) => one !== id), positions: rest } : { ...layout, placed: layout.placed.filter((one) => one !== id), positions: rest })
    setSelected(null)
    setNote({ text: client ? t('topology.removedClient', { name: nameOf(id) }) : t('topology.removedDevice', { name: nameOf(id) }) })
  }
  const [fitBump, setFitBump] = useState(0)
  const arrange = () => {
    if (!layout) return
    const before = positions
    save({ ...layout, positions: treeLayout(shown.nodes.map((node) => node.id), shown.links, widthOf) })
    setFitBump((n) => n + 1)
    setNote({
      text: t('topology.treeDone'),
      undo: () => {
        save({ ...layout, positions: before })
        setFitBump((n) => n + 1)
      },
    })
  }

  // -- reading out a link -------------------------------------------------------------

  const labelText = useCallback(
    (link: TopoLink): ReactNode => {
      if (link.state === 'down') return t('topology.disconnected')
      return (
        <>
          <tspan style={{ fill: 'var(--nd-accent)' }}>▼ </tspan>
          <tspan>{words.bits(link.down)}</tspan>
          <tspan dx={8} style={{ fill: 'var(--nd-c-violet)' }}>
            ▲{' '}
          </tspan>
          <tspan>{words.bits(link.up)}</tspan>
          <tspan dx={8} style={{ fill: 'var(--nd-text-faint)' }}>
            {Math.round(ageOf(link) ?? 0)} s
          </tspan>
        </>
      )
    },
    [t, words, ageOf],
  )
  const labelWidth = useCallback(
    (link: TopoLink) =>
      link.state === 'down'
        ? Math.ceil(textWidth(t('topology.disconnected'), LABEL_FONT)) + 18
        : Math.ceil(textWidth(`▼ ${words.bits(link.down)}▲ ${words.bits(link.up)}${Math.round(link.age ?? 0) + 99} s`, LABEL_FONT)) + 18 + 16,
    [t, words],
  )
  const tooltip = useCallback(
    (link: TopoLink) => (
      <>
        <b className="block mb-1 text-[12.5px]">
          {nameOf(link.a)} ↔ {nameOf(link.b)}
        </b>
        {link.state === 'down' ? (
          <span>{t('topology.disconnected')}</span>
        ) : (
          <div className="grid gap-0.5">
            <span className="flex justify-between gap-3">
              <span>→ {nameOf(link.b)}</span>
              <span className="font-mono text-accent">{words.bits(link.down)}</span>
            </span>
            <span className="flex justify-between gap-3">
              <span>→ {nameOf(link.a)}</span>
              <span className="font-mono" style={{ color: 'var(--nd-c-violet)' }}>
                {words.bits(link.up)}
              </span>
            </span>
            <span className="flex justify-between gap-3">
              <span>{t('topology.load')}</span>
              <span className="font-mono">{t('topology.ofSpeed', { share: words.share(utilisation(link)), speed: words.speed(link.speed) })}</span>
            </span>
            <span className="mt-1 pt-1 border-t border-line text-muted">{t('topology.measuredAt', { age: words.ago(ageOf(link)), device: nameOf(link.meter) })}</span>
          </div>
        )}
      </>
    ),
    [nameOf, t, words, ageOf],
  )

  // -- what the browser chose --------------------------------------------------------

  const [view, setView] = useState<View>(readView)
  const [viewOpen, setViewOpen] = useState(false)
  const choose = (next: Partial<View>) => {
    const merged = { ...view, ...next }
    setView(merged)
    try {
      localStorage.setItem(VIEW_KEY, JSON.stringify(merged))
    } catch {
      /* not remembered, still shown */
    }
  }

  const [clientsOpen, setClientsOpen] = useState(false)
  const [clientQuery, setClientQuery] = useState('')

  // -- the page ------------------------------------------------------------------------

  if (answer.isLoading || (!answer.data && !answer.isError)) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-32 text-muted text-sm">
        <Spinner />
        {t('topology.loading')}
      </div>
    )
  }
  if (answer.isError || problem || !data || !layout) {
    const code = problem?.code ?? 'unexpected'
    return (
      <div className="flex items-center justify-center p-6 py-24">
        <div className="glass rounded-2xl p-6 max-w-lg text-center grid gap-2">
          <Network className="mx-auto text-accent" size={28} />
          <h2 className="font-semibold">{t('topology.problemTitle')}</h2>
          <p className="text-sm text-muted">{t(`topology.problems.${code}`, { defaultValue: problem?.message ?? t('topology.problems.unexpected') })}</p>
          {problem?.hint && <p className="text-xs text-faint">{t(`topology.hints.${code}`, { defaultValue: problem.hint })}</p>}
          {/* What the console said, word for word: "HTTP 429" tells more than any translation. */}
          {problem?.message && <p className="text-[11px] text-faint font-mono">{problem.message}</p>}
          {editing && <EditBar found={0} onFound={() => undefined} onClients={() => undefined} onTree={() => undefined} onAddPage={onAddPage} onSettings={onSettings} onDone={onDone} plain />}
        </div>
      </div>
    )
  }

  const devices = data.nodes.filter((node) => node.kind !== 'internet')
  const stale = data.stale ?? null
  const offline = devices.filter((node) => node.status === 'offline').length
  const wan = data.links.find((link) => link.kind === 'wan')
  const linkOf = (id: string) => [...data.links, ...data.client_links].find((link) => link.id === id)
  const panelNode = selected?.type === 'node' ? shown.nodes.find((node) => node.id === selected.id) : undefined
  const panelLink = selected?.type === 'link' ? linkOf(selected.id) : undefined

  const panel = selected?.type === 'found' ? (
    <FoundPanel
      found={foundItems.found}
      hidden={foundItems.hidden}
      showHidden={showHidden}
      words={words}
      onToggleHidden={() => setShowHidden((v) => !v)}
      onPlace={(id) => (canEdit ? place(id) : setNote({ text: t('topology.readOnly') }))}
      onHide={(id) => canEdit && save({ ...layout, hidden: [...layout.hidden, id] })}
      onShow={(id) => canEdit && save({ ...layout, hidden: layout.hidden.filter((one) => one !== id) })}
      onClose={() => setSelected(null)}
    />
  ) : panelNode ? (
    <NodePanel
      node={panelNode}
      links={shown.links.filter((link) => link.a === panelNode.id || link.b === panelNode.id)}
      nodeName={nameOf}
      path={pathUp(panelNode.id, shown.links).nodes}
      clients={(data.clients ?? []).filter((client) => client.at === panelNode.id).map((client) => ({ client, placed: layout.clients.includes(client.id) }))}
      parentLink={shown.links.find((link) => link.b === panelNode.id)}
      words={words}
      ageOf={ageOf}
      editing={editing && canEdit}
      onPickLink={(id) => setSelected({ type: 'link', id })}
      onAddClient={(id) => (canEdit ? addClient(id) : setNote({ text: t('topology.readOnly') }))}
      onRemove={() => remove(panelNode.id)}
      onClose={() => setSelected(null)}
    />
  ) : panelLink ? (
    <LinkPanel link={panelLink} nodeName={nameOf} words={words} age={ageOf(panelLink)} meterEvery={nodeById.get(panelLink.meter)?.every ?? null} onClose={() => setSelected(null)} />
  ) : null

  const chips = (
    <div className="flex flex-wrap gap-1.5" data-no-picture>
      {wan && (
        <span className="glass-strong rounded-full px-2.5 py-1 text-[12.5px] text-muted whitespace-nowrap">
          WAN <b className="font-mono text-[var(--nd-text)]">▼ {words.bits(wan.down)}</b> <b className="font-mono text-[var(--nd-text)]">▲ {words.bits(wan.up)}</b>
        </span>
      )}
      <span className="glass-strong rounded-full px-2.5 py-1 text-[12.5px] text-muted whitespace-nowrap">
        {t('topology.devices')} <b className="text-[var(--nd-text)]">{devices.length - offline} / {devices.length}</b>
        {offline > 0 && <span className="text-bad"> · {t('topology.offlineCount', { count: offline })}</span>}
      </span>
      {stale && (
        <span className="glass-strong rounded-full px-2.5 py-1 text-[12.5px] text-bad whitespace-nowrap" title={stale.message} data-topology-stale>
          {t('topology.stale', { age: words.ago(Math.max(0, (now - receivedAt) / 1000 + stale.for_seconds)) })}
        </span>
      )}
      {foundItems.found.length > 0 && (
        <button type="button" className="glass-strong rounded-full px-2.5 py-1 text-[12.5px] text-accent whitespace-nowrap border border-[var(--nd-accent-glow)]" onClick={() => setSelected({ type: 'found' })}>
          {t('topology.found')} <span className="ml-1 inline-grid place-items-center min-w-[18px] h-[18px] px-1 rounded-full bg-accent text-on-accent text-[11px] font-semibold">{foundItems.found.length}</span>
        </button>
      )}
    </div>
  )

  const clientsDialog = (
    <Dialog open={clientsOpen} onClose={() => setClientsOpen(false)} title={t('topology.clientsTitle')} footer={<button type="button" className="btn btn-accent" onClick={() => setClientsOpen(false)}>{t('common.done')}</button>}>
      <div className="grid gap-3">
        <p className="text-sm text-muted">{t('topology.clientsHelp')}</p>
        <input className="input" autoFocus value={clientQuery} placeholder={t('topology.clientSearch')} aria-label={t('topology.clientSearch')} onChange={(event) => setClientQuery(event.target.value)} />
        {(() => {
          const query = clientQuery.trim().toLowerCase()
          const groups = shown.nodes
            .filter((node) => node.kind === 'switch' || node.kind === 'gateway')
            .map((node) => ({ node, clients: data.clients.filter((client) => client.at === node.id && (!query || client.name.toLowerCase().includes(query) || client.ip.includes(query))) }))
            .filter((group) => group.clients.length > 0)
          if (groups.length === 0) return <p className="text-sm text-muted">{t('topology.noClient')}</p>
          return groups.map((group) => (
            <div key={group.node.id} className="grid gap-1.5">
              <h5 className="text-xs font-semibold text-muted flex justify-between mt-1">
                <span>{group.node.name}</span>
                <span>{group.clients.length}</span>
              </h5>
              {group.clients.map((client) => (
                <ClientRow key={client.id} client={client} placed={layout.clients.includes(client.id)} words={words} onAdd={() => addClient(client.id)} />
              ))}
            </div>
          ))
        })()}
        <p className="text-xs text-faint">{t('topology.wifiStaysAll')}</p>
      </div>
    </Dialog>
  )

  const noteBox = note && (
    <div className="fixed left-1/2 -translate-x-1/2 bottom-24 md:bottom-20 z-50 glass-strong rounded-xl px-4 py-2.5 shadow-xl flex items-center gap-3 text-sm max-w-[calc(100vw-2rem)]" role="status">
      <span className={note.level === 'error' ? 'text-bad' : ''}>{note.text}</span>
      {note.undo && (
        <button
          type="button"
          className="btn btn-flat !py-1 text-accent"
          onClick={() => {
            note.undo?.()
            setNote(null)
          }}
        >
          {t('topology.undo')}
        </button>
      )}
    </div>
  )

  if (narrow) {
    return (
      <div className="px-3 pt-3 pb-4 grid gap-3" data-topology-page>
        {chips}
        <TopologyList nodes={planNodes} links={shown.links} words={words} ageOf={ageOf} onPick={(id) => setSelected({ type: 'node', id })} />
        <p className="text-xs text-faint flex items-center gap-1.5">
          <Monitor size={13} /> {t('topology.phoneHint')}
        </p>
        {panel && (
          <div className="fixed inset-x-2 bottom-2 z-50 max-h-[72dvh] glass-strong rounded-2xl shadow-2xl flex flex-col overflow-hidden" role="dialog" aria-modal="false">
            {panel}
          </div>
        )}
        {clientsDialog}
        {noteBox}
        <NoteTimer note={note} onDone={clearNote} />
      </div>
    )
  }

  return (
    <div className="relative h-[calc(100dvh-3rem)]" data-topology-page>
      <TopologyCanvas
        nodes={planNodes}
        links={shown.links}
        editing={editing && canEdit}
        selected={selected?.type === 'found' ? null : selected}
        lit={lit}
        straight={view.straight}
        flow={view.flow}
        labels={view.labels}
        labelText={labelText}
        labelWidth={labelWidth}
        tooltip={tooltip}
        onSelect={setSelected}
        onMove={(id, x, y) => setDragged({ id, x, y })}
        onMoveEnd={(id) => {
          if (dragged && dragged.id === id) save({ ...layout, positions: { ...positions, [id]: [dragged.x, dragged.y] } })
          setDragged(null)
        }}
        fitKey={`${pageId}:${fitBump}:${planNodes.length > 0}`}
        ariaLabel={t('topology.plan')}
        controls={
          <div className="relative" data-plan-controls>
            <button type="button" className="btn btn-icon glass-strong" onClick={() => setViewOpen((v) => !v)} aria-label={t('topology.view')} title={t('topology.view')} aria-expanded={viewOpen}>
              <SlidersHorizontal size={15} />
            </button>
            {viewOpen && (
              <div className="absolute right-0 bottom-11 w-72 glass-strong rounded-2xl p-3 grid gap-2.5 shadow-xl text-xs text-muted">
                <Choice label={t('topology.lines')} value={view.straight ? 'straight' : 'curved'} options={[['curved', t('topology.curved')], ['straight', t('topology.straight')]]} onChange={(value) => choose({ straight: value === 'straight' })} />
                <Choice label={t('topology.flow')} value={view.flow} options={[['dots', t('topology.dots')], ['dashes', t('topology.dashes')], ['still', t('topology.still')]]} onChange={(value) => choose({ flow: value as FlowMode })} />
                <Choice label={t('topology.values')} value={view.labels} options={[['all', t('topology.valuesAll')], ['load', t('topology.valuesLoad')], ['off', t('topology.valuesOff')]]} onChange={(value) => choose({ labels: value as LabelMode })} />
                <p className="text-faint">{t('topology.viewHelp')}</p>
              </div>
            )}
          </div>
        }
      />
      <div className="absolute top-3 left-3 right-3 flex flex-wrap items-start gap-2 pointer-events-none [&>*]:pointer-events-auto">{chips}</div>
      <div className={`absolute left-3 bottom-3 ${editing ? 'hidden' : 'hidden lg:flex'} flex-wrap items-center gap-x-3.5 gap-y-1 glass-strong rounded-xl px-3 py-2 text-xs text-muted max-w-[calc(100%-15rem)]`} data-no-picture>
        <span>{t('topology.legend')}</span>
        <Swatch colour="var(--nd-accent)" label={t('topology.calm')} level="calm" />
        <Swatch colour="var(--nd-warn)" label={t('topology.busy')} level="busy" />
        <Swatch colour="var(--nd-bad)" label={t('topology.full')} level="full" />
        <Swatch colour="repeating-linear-gradient(90deg,var(--nd-unknown) 0 5px,transparent 5px 9px)" label={t('topology.disconnected')} level="down" />
      </div>
      {panel && (
        <aside className={`absolute top-3 right-3 ${editing && canEdit ? 'bottom-24' : 'bottom-16'} w-[370px] max-w-[calc(100%-1.5rem)] glass-strong rounded-2xl shadow-2xl flex flex-col overflow-hidden z-10`} data-no-picture>
          {panel}
        </aside>
      )}
      {editing && canEdit && (
        <EditBar
          found={foundItems.found.length}
          onFound={() => setSelected({ type: 'found' })}
          onClients={() => setClientsOpen(true)}
          onTree={arrange}
          onAddPage={onAddPage}
          onSettings={onSettings}
          onDone={onDone}
        />
      )}
      {clientsDialog}
      {noteBox}
      <NoteTimer note={note} onDone={clearNote} />
    </div>
  )
}

function NoteTimer({ note, onDone }: { note: unknown; onDone: () => void }) {
  useEffect(() => {
    if (!note) return
    const timer = window.setTimeout(onDone, 6000)
    return () => window.clearTimeout(timer)
  }, [note, onDone])
  return null
}

function Swatch({ colour, label, level }: { colour: string; label: string; level: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <i className="inline-block w-[18px] h-1 rounded" style={{ background: colour }} data-swatch={level} />
      {label}
    </span>
  )
}

function Choice({ label, value, options, onChange }: { label: string; value: string; options: [string, string][]; onChange: (value: string) => void }) {
  return (
    <div className="grid gap-1">
      <span>{label}</span>
      <span className="inline-flex p-0.5 rounded-lg bg-surface-hover gap-0.5" role="radiogroup" aria-label={label}>
        {options.map(([key, text]) => (
          <button
            key={key}
            type="button"
            role="radio"
            aria-checked={value === key}
            className={`flex-1 px-2.5 py-1 rounded-md text-[12.5px] ${value === key ? 'bg-[var(--nd-surface-strong)] text-[var(--nd-text)] shadow' : 'text-muted'}`}
            onClick={() => onChange(key)}
          >
            {text}
          </button>
        ))}
      </span>
    </div>
  )
}

function EditBar(props: {
  found: number
  onFound: () => void
  onClients: () => void
  onTree: () => void
  onAddPage: () => void
  onSettings: () => void
  onDone: () => void
  plain?: boolean
}) {
  const { t } = useTranslation()
  return (
    <div
      className={
        props.plain
          ? 'mt-3 flex flex-wrap justify-center gap-1'
          : 'fixed bottom-20 md:bottom-6 left-1/2 -translate-x-1/2 z-40 max-w-[calc(100vw-1rem)] glass-strong rounded-full px-2 py-1.5 flex items-center gap-1 shadow-2xl'
      }
      data-no-picture
    >
      {!props.plain && (
        <>
          <button type="button" className="btn btn-flat whitespace-nowrap" onClick={props.onFound} aria-label={t('topology.found')}>
            <Inbox size={15} /> <span className="hidden sm:inline">{t('topology.found')}</span>
            {props.found > 0 && <span className="inline-grid place-items-center min-w-[18px] h-[18px] px-1 rounded-full bg-accent text-on-accent text-[11px] font-semibold">{props.found}</span>}
          </button>
          <button type="button" className="btn btn-flat whitespace-nowrap" onClick={props.onClients} aria-label={t('topology.clients')}>
            <Monitor size={15} /> <span className="hidden sm:inline">{t('topology.clients')}</span>
          </button>
          <button type="button" className="btn btn-flat whitespace-nowrap" onClick={props.onTree} aria-label={t('topology.tree')}>
            <Network size={15} /> <span className="hidden md:inline">{t('topology.tree')}</span>
          </button>
          <span className="w-px h-5 bg-line mx-0.5" aria-hidden="true" />
        </>
      )}
      <button type="button" className="btn btn-flat whitespace-nowrap" onClick={props.onAddPage} aria-label={t('board.addPage')}>
        <Plus size={15} /> <span className="hidden lg:inline">{t('board.addPage')}</span>
      </button>
      <button type="button" className="btn btn-flat whitespace-nowrap" onClick={props.onSettings} aria-label={t('board.settings')}>
        <Settings2 size={15} /> <span className="hidden lg:inline">{t('board.settings')}</span>
      </button>
      <button type="button" className="btn btn-accent rounded-full" onClick={props.onDone}>
        <Check size={15} /> {t('common.done')}
      </button>
    </div>
  )
}
