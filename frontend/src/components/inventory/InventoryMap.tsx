/**
 * The inventory as a map (agreed on 25.10.2026): one column per machine, its
 * containers and guests below it, and beside each what runs in it, the way a
 * folder tree reads. A dashed name is only proposed, a red dot is down; a name
 * leads to its diagnosis. Containers nothing runs in wait behind a switch.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { diagnosisPath } from '../../lib/diagnosis'
import { columns, type Inventory, type InventoryNode, type Placed, type Slot } from '../../lib/inventory'

function Dot({ node }: { node: InventoryNode }) {
  return <span className="dot flex-none" data-status={node.down ? 'bad' : node.demo ? 'unknown' : 'ok'} aria-hidden="true" />
}

function Name({ node, className = '' }: { node: InventoryNode; className?: string }) {
  return (
    <Link className={`min-w-0 truncate hover:underline ${className}`} to={diagnosisPath(node.ref)} title={node.name}>
      {node.name}
    </Link>
  )
}

export function InventoryMap({ inventory }: { inventory: Inventory }) {
  const { t } = useTranslation()
  const [all, setAll] = useState(false)
  const { columns: machines, loose } = columns(inventory)
  const hidden = machines.reduce((sum, one) => sum + one.empty.length, 0)

  const service = (one: Placed) => (
    <li key={one.node.ref} className={`flex items-center gap-1.5 text-[12.5px] ${one.proposed ? 'text-muted' : ''}`} data-testid="inventory-service" data-proposed={one.proposed || undefined}>
      <span className="flex-none text-faint" aria-hidden="true">◂</span>
      <Dot node={one.node} />
      <Name node={one.node} className={one.proposed ? 'italic underline decoration-dashed underline-offset-2' : ''} />
      {one.proposed ? <span className="flex-none text-[11px] text-faint">{t('inventory.proposedMark')}</span> : null}
      {one.tiles ? <span className="chip flex-none !py-0 text-[10px]">{t('inventory.withTile', { count: one.tiles })}</span> : null}
    </li>
  )
  const slot = (one: Slot) => (
    <li key={one.node.ref} className="py-1" data-testid="inventory-slot">
      <div className="flex items-center gap-1.5 text-[13px]">
        <Dot node={one.node} />
        <Name node={one.node} className="font-medium" />
        <span className="flex-none text-[11px] text-faint">{t(`inventory.kind.${one.node.kind}`)}</span>
      </div>
      {one.services.length ? <ul className="ml-4 mt-0.5 flex flex-col gap-0.5 border-l border-line pl-2">{one.services.map(service)}</ul> : null}
    </li>
  )

  return (
    <div data-testid="inventory-map">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <p className="flex-1 text-[12px] text-muted">{t('inventory.mapHelp')}</p>
        {hidden ? (
          <button type="button" className="btn h-8" aria-pressed={all} onClick={() => setAll(!all)}>
            {all ? t('inventory.onlyUsed') : t('inventory.showAll', { count: hidden })}
          </button>
        ) : null}
      </div>
      <div className="grid items-start gap-3 [grid-template-columns:repeat(auto-fill,minmax(250px,1fr))]">
        {machines.map((machine) => (
          <section key={machine.host.ref} className="min-w-0 rounded-xl border border-line p-3" data-testid="inventory-column">
            {/* The machine by its own name (docker-live), the connection that reads it below (Portainer). */}
            <h3 className="mb-1.5 flex items-center gap-1.5 text-[14px] font-semibold">
              <Dot node={machine.host} />
              <Name node={{ ...machine.host, name: machine.host.machine || machine.host.name }} />
            </h3>
            <p className="mb-2 truncate text-[11px] text-faint">
              {[machine.host.machine && machine.host.machine !== machine.host.name ? machine.host.name : t('inventory.kind.integration'), machine.host.detail].filter(Boolean).join(' · ')}
            </p>
            {machine.direct.length ? (
              <div className="mb-1">
                <p className="text-[11px] text-faint">{t('inventory.direct')}</p>
                <ul className="ml-1 flex flex-col gap-0.5">{machine.direct.map(service)}</ul>
              </div>
            ) : null}
            {!machine.slots.length && !machine.direct.length && !all ? (
              <p className="text-[12px] text-muted">{t('inventory.nothingKnown', { count: machine.empty.length })}</p>
            ) : null}
            <ul className="flex flex-col">
              {machine.slots.map(slot)}
              {all ? machine.empty.map(slot) : null}
            </ul>
          </section>
        ))}
      </div>
      {loose.length ? (
        <section className="mt-4" data-testid="inventory-loose">
          <h3 className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-faint">{t('inventory.loose')}</h3>
          <ul className="flex flex-wrap gap-1.5">
            {loose.map((one) => (
              <li key={one.node.ref} className="chip inline-flex items-center gap-1.5 text-[12px]">
                <Dot node={one.node} />
                <Name node={one.node} />
                {one.tiles ? <span className="text-[10px] text-faint">{t('inventory.withTile', { count: one.tiles })}</span> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  )
}
