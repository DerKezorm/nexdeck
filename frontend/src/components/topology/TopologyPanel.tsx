import { Cable, Inbox, X } from 'lucide-react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { levelOf, utilisation, type TopoClient, type TopoLink, type TopoNode } from '../../lib/topology'
import { ICONS } from './TopologyCanvas'
import type { Words } from './words'

const LEVEL_BAR = { calm: 'var(--nd-accent)', busy: 'var(--nd-warn)', full: 'var(--nd-bad)' } as const

export interface FoundItem {
  node: TopoNode
  parent: TopoNode | undefined
  link: TopoLink | undefined
}

function Head({ icon, title, sub, onClose }: { icon: ReactNode; title: string; sub: string; onClose: () => void }) {
  const { t } = useTranslation()
  return (
    <header className="flex items-center gap-3 p-4 border-b border-line">
      <span className="w-10 h-10 rounded-xl grid place-items-center bg-accent-soft text-accent shrink-0">{icon}</span>
      <div className="min-w-0 flex-1">
        <h3 className="font-semibold leading-tight break-words">{title}</h3>
        <p className="text-xs text-muted mt-0.5 break-words">{sub}</p>
      </div>
      <button type="button" className="btn btn-icon btn-flat self-start" onClick={onClose} aria-label={t('common.close')}>
        <X size={16} />
      </button>
    </header>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h4 className="text-[11px] uppercase tracking-wider text-faint font-semibold mb-2">{title}</h4>
      {children}
    </section>
  )
}

function Bar({ share, colour }: { share: number | null; colour?: string }) {
  return (
    <div className="h-1 rounded bg-line-strong overflow-hidden">
      <i className="block h-full rounded transition-[width] duration-500" style={{ width: `${Math.min(100, Math.max(share === null ? 0 : 1, (share ?? 0) * 100))}%`, background: colour ?? LEVEL_BAR[levelOf(share)] }} />
    </div>
  )
}

/** One link in a device's list: who is on the other end, the port here, both directions and their age. */
export function LinkRow({ link, other, here, words, age, onPick }: { link: TopoLink; other: string; here: string; words: Words; age: number | null; onPick: () => void }) {
  const { t } = useTranslation()
  return (
    <button type="button" className="w-full text-left grid gap-1 p-2.5 rounded-xl bg-surface-hover border border-transparent hover:border-[var(--nd-accent-glow)]" onClick={onPick}>
      <span className="flex justify-between gap-2 text-[13px]">
        <span className="min-w-0 break-words">{other}</span>
        <span className="text-xs text-muted text-right shrink-0">
          {[here, words.speed(link.speed)].filter(Boolean).join(' · ')}
        </span>
      </span>
      <span className="flex gap-3 text-xs font-mono">
        {link.state === 'down' ? (
          <span className="text-bad">{t('topology.disconnected')}</span>
        ) : (
          <>
            <span className="text-accent">▼ {words.bits(link.down)}</span>
            <span style={{ color: 'var(--nd-c-violet)' }}>▲ {words.bits(link.up)}</span>
            <span className="ml-auto text-muted">{words.ago(age)}</span>
          </>
        )}
      </span>
      <Bar share={link.state === 'down' ? 0 : utilisation(link)} />
    </button>
  )
}

export function NodePanel(props: {
  node: TopoNode
  links: TopoLink[]
  nodeName: (id: string) => string
  path: string[]
  clients: { client: TopoClient; placed: boolean }[]
  parentLink: TopoLink | undefined
  words: Words
  ageOf: (link: TopoLink) => number | null
  editing: boolean
  onPickLink: (id: string) => void
  onAddClient: (id: string) => void
  onRemove: () => void
  onClose: () => void
}) {
  const { t } = useTranslation()
  const { node, words } = props
  const Icon = ICONS[node.kind === 'client' ? (node.client_kind ?? 'other') : node.kind]
  const client = node.kind === 'client'
  const facts: [string, string][] = client
    ? [
        [t('topology.facts.port'), props.parentLink ? `${props.nodeName(props.parentLink.a)}, ${words.port(props.parentLink.port_a)}` : '–'],
        [t('topology.facts.ip'), String(node.facts.ip || '–')],
      ]
    : Object.entries(node.facts)
        .filter(([, value]) => value !== '' && value !== null && value !== undefined)
        .map(([key, value]) => [t(`topology.facts.${key}`, { defaultValue: key }), words.fact(key, value)])
  return (
    <>
      <Head icon={Icon ? <Icon size={22} /> : null} title={node.name} sub={node.model} onClose={props.onClose} />
      <div className="flex-1 min-h-0 overflow-y-auto p-4 grid gap-4 content-start">
        {node.kind !== 'internet' && (
          <div className="flex flex-wrap gap-1.5">
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11.5px] font-semibold bg-surface-hover border border-line-strong ${node.status === 'offline' ? 'text-bad' : 'text-ok'}`}>● {node.status === 'offline' ? t('topology.offline') : t('topology.online')}</span>
            {client && <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11.5px] font-semibold bg-surface-hover border border-line-strong text-muted">{t('topology.client')}</span>}
            {node.every !== null && <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11.5px] font-semibold bg-surface-hover border border-line-strong text-muted">{t('topology.rhythmShort', { seconds: node.every })}</span>}
          </div>
        )}
        <Section title={client ? t('topology.client') : t('topology.device')}>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-[13px]">
            {facts.map(([label, value]) => (
              <div key={label} className="contents">
                <dt className="text-muted">{label}</dt>
                <dd className="text-right break-words">{value}</dd>
              </div>
            ))}
          </dl>
        </Section>
        {props.links.length > 0 && (
          <Section title={t('topology.connections', { count: props.links.length })}>
            <div className="grid gap-1.5">
              {props.links.map((link) => {
                const otherId = link.a === node.id ? link.b : link.a
                const port = link.a === node.id ? link.port_a : link.port_b
                return (
                  <LinkRow
                    key={link.id}
                    link={link}
                    other={props.nodeName(otherId)}
                    here={words.port(port, link.kind)}
                    words={words}
                    age={props.ageOf(link)}
                    onPick={() => props.onPickLink(link.id)}
                  />
                )
              })}
            </div>
          </Section>
        )}
        {props.clients.length > 0 && (
          <Section title={t('topology.wiredClients', { count: props.clients.length })}>
            <div className="grid gap-1.5">
              {props.clients.map(({ client: one, placed }) => (
                <ClientRow key={one.id} client={one} placed={placed} words={words} onAdd={() => props.onAddClient(one.id)} />
              ))}
            </div>
          </Section>
        )}
        {node.kind === 'ap' && <p className="text-xs text-faint">{t('topology.wifiStays', { count: node.wifi_clients ?? 0 })}</p>}
        {props.path.length > 1 && (
          <Section title={t('topology.wayOut')}>
            <div className="flex flex-wrap items-center gap-1 text-[12.5px]">
              {props.path.map((id, index) => (
                <span key={id} className="contents">
                  {index > 0 && <span className="text-faint">→</span>}
                  <span className="px-2 py-0.5 rounded-lg bg-surface-hover">{props.nodeName(id)}</span>
                </span>
              ))}
            </div>
          </Section>
        )}
        {props.editing && node.kind !== 'internet' && node.kind !== 'gateway' && (
          <div className="grid gap-2">
            <button type="button" className="btn text-bad justify-self-start" onClick={props.onRemove}>
              {t('topology.remove')}
            </button>
            <p className="text-xs text-faint">{client ? t('topology.removeClient') : t('topology.removeDevice')}</p>
          </div>
        )}
      </div>
    </>
  )
}

export function ClientRow({ client, placed, words, onAdd }: { client: TopoClient; placed: boolean; words: Words; onAdd: () => void }) {
  const { t } = useTranslation()
  const Icon = ICONS[client.kind] ?? ICONS.other
  return (
    <div className={`flex items-center gap-2.5 p-2.5 rounded-xl border border-line-strong ${placed ? 'opacity-60' : ''}`}>
      <Icon size={20} className={placed ? 'text-muted shrink-0' : 'text-accent shrink-0'} />
      <span className="grid min-w-0 flex-1">
        <b className="text-[13px] font-semibold break-words">{client.name}</b>
        <small className="text-xs text-muted truncate">{[words.port(client.port), client.ip].filter(Boolean).join(' · ')}</small>
      </span>
      {placed ? (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11.5px] font-semibold bg-surface-hover border border-line-strong text-muted shrink-0">{t('topology.onPlan')}</span>
      ) : (
        <button type="button" className="btn btn-accent shrink-0 !py-1 !px-2.5 text-xs" onClick={onAdd}>
          {t('topology.place')}
        </button>
      )}
    </div>
  )
}

export function LinkPanel(props: { link: TopoLink; nodeName: (id: string) => string; words: Words; age: number | null; meterEvery: number | null; onClose: () => void }) {
  const { t } = useTranslation()
  const { link, words } = props
  const a = props.nodeName(link.a)
  const b = props.nodeName(link.b)
  const meter = props.nodeName(link.meter)
  const kind = link.kind === 'wifi' ? t('topology.wireless') : link.kind === 'wan' ? t('topology.internetLine') : t('topology.cable')
  const history = link.history
  const max = Math.max(link.speed ? link.speed * 0.05 : 1, ...history.down, ...history.up) * 1.1
  const line = (values: number[]) => values.map((value, i) => `${(320 - (values.length - 1 - i) * (320 / 59)).toFixed(1)},${(78 - (value / max) * 74).toFixed(1)}`).join(' ')
  const ring = Math.min(1, Math.max(0, (props.age ?? 0) / (props.meterEvery || 60)))
  return (
    <>
      <Head icon={<Cable size={22} />} title={`${a} ↔ ${b}`} sub={`${kind} · ${words.speed(link.speed)}`} onClose={props.onClose} />
      <div className="flex-1 min-h-0 overflow-y-auto p-4 grid gap-4 content-start">
        {link.state === 'down' ? (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11.5px] font-semibold bg-surface-hover border border-line-strong text-bad justify-self-start">● {t('topology.disconnected')}</span>
        ) : (
          <div className="flex items-center gap-2 p-2.5 rounded-xl bg-surface-hover text-[12.5px] text-muted">
            <svg width="18" height="18" viewBox="0 0 20 20" className="shrink-0" aria-hidden="true">
              <circle cx="10" cy="10" r="8" fill="none" style={{ stroke: 'var(--nd-border-strong)' }} strokeWidth="3" />
              <circle cx="10" cy="10" r="8" fill="none" style={{ stroke: 'var(--nd-accent)' }} strokeWidth="3" strokeDasharray={`${(ring * 50.3).toFixed(1)} 51`} transform="rotate(-90 10 10)" />
            </svg>
            <span>
              {t('topology.asOf')} <b className="font-mono font-medium text-[var(--nd-text)]">{words.ago(props.age)}</b> ·{' '}
              {props.meterEvery !== null ? t('topology.rhythm', { name: meter, seconds: props.meterEvery }) : t('topology.rhythmUnknown', { name: meter })}
            </span>
          </div>
        )}
        <Section title={t('topology.ports')}>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-[13px]">
            <dt className="text-muted">{a}</dt>
            <dd className="text-right">{words.port(link.port_a, link.kind) || '–'}</dd>
            <dt className="text-muted">{b}</dt>
            <dd className="text-right">{words.port(link.port_b, link.kind) || '–'}</dd>
          </dl>
        </Section>
        <div className="grid gap-3">
          {[
            { from: a, to: b, value: link.down, colour: 'var(--nd-accent)' },
            { from: b, to: a, value: link.up, colour: 'var(--nd-c-violet)' },
          ].map((row) => (
            <div key={row.from} className="grid gap-1">
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[12.5px] text-muted break-words">
                  {row.from} → {row.to}
                </span>
                <b className="font-mono text-xl font-semibold shrink-0" style={{ color: row.colour }}>
                  {link.state === 'down' ? '–' : row.value === null ? t('topology.noValue') : words.bits(row.value)}
                </b>
              </div>
              <Bar share={link.speed && row.value !== null ? row.value / link.speed : null} colour={row.colour === 'var(--nd-accent)' ? undefined : row.colour} />
            </div>
          ))}
        </div>
        {history.down.length > 1 && (
          <Section title={t('topology.history', { count: history.down.length })}>
            <svg viewBox="0 0 320 80" preserveAspectRatio="none" className="w-full h-20 block" aria-hidden="true">
              <line x1="0" y1="78" x2="320" y2="78" style={{ stroke: 'var(--nd-border-strong)' }} />
              <polyline points={line(history.down)} fill="none" style={{ stroke: 'var(--nd-accent)' }} strokeWidth="1.8" vectorEffect="non-scaling-stroke" />
              <polyline points={line(history.up)} fill="none" style={{ stroke: 'var(--nd-c-violet)' }} strokeWidth="1.8" vectorEffect="non-scaling-stroke" />
            </svg>
          </Section>
        )}
        <Section title={t('topology.source')}>
          <p className="text-[12.5px] text-muted">{t('topology.sourceText', { device: meter, port: words.port(link.meter === link.a ? link.port_a : link.port_b, link.kind) || 'WAN' })}</p>
        </Section>
      </div>
    </>
  )
}

export function FoundPanel(props: {
  found: FoundItem[]
  hidden: FoundItem[]
  showHidden: boolean
  words: Words
  onToggleHidden: () => void
  onPlace: (id: string) => void
  onHide: (id: string) => void
  onShow: (id: string) => void
  onClose: () => void
}) {
  const { t } = useTranslation()
  const row = (item: FoundItem, hidden: boolean) => {
    const Icon = ICONS[item.node.kind] ?? ICONS.other
    return (
      <div key={item.node.id} className="flex items-center gap-2.5 p-2.5 rounded-xl border border-line-strong">
        <Icon size={20} className="text-accent shrink-0" />
        <span className="grid min-w-0 flex-1">
          <b className="text-[13px] font-semibold break-words">{item.node.name}</b>
          <small className="text-xs text-muted break-words">
            {[item.node.model, item.parent ? t('topology.hangsOn', { name: item.parent.name, port: props.words.port(item.link?.port_a, item.link?.kind) }) : ''].filter(Boolean).join(' · ')}
          </small>
        </span>
        {hidden ? (
          <button type="button" className="btn shrink-0 !py-1 !px-2.5 text-xs" onClick={() => props.onShow(item.node.id)}>
            {t('topology.show')}
          </button>
        ) : (
          <span className="grid gap-1 shrink-0">
            <button type="button" className="btn btn-accent !py-1 !px-2.5 text-xs" onClick={() => props.onPlace(item.node.id)}>
              {t('topology.place')}
            </button>
            <button type="button" className="btn !py-1 !px-2.5 text-xs" onClick={() => props.onHide(item.node.id)}>
              {t('topology.putAway')}
            </button>
          </span>
        )}
      </div>
    )
  }
  return (
    <>
      <Head icon={<Inbox size={22} />} title={t('topology.found')} sub={t('topology.foundHelp')} onClose={props.onClose} />
      <div className="flex-1 min-h-0 overflow-y-auto p-4 grid gap-4 content-start">
        {props.found.length > 0 ? <div className="grid gap-1.5">{props.found.map((item) => row(item, false))}</div> : <p className="text-[13px] text-muted">{t('topology.foundNone')}</p>}
        <p className="text-xs text-faint">{t('topology.placeHelp')}</p>
        {props.hidden.length > 0 && (
          <div className="grid gap-1.5">
            <button type="button" className="text-left text-[12.5px] text-muted" onClick={props.onToggleHidden} aria-expanded={props.showHidden}>
              {props.showHidden ? '▾' : '▸'} {t('topology.putAwayList', { count: props.hidden.length })}
            </button>
            {props.showHidden && props.hidden.map((item) => row(item, true))}
          </div>
        )}
      </div>
    </>
  )
}
