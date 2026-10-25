import { useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, X } from 'lucide-react'
import { lazy, Suspense, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, del, get, post } from '../../api/client'
import { tree, type Branch, type Inventory, type InventoryNode } from '../../lib/inventory'
import { useLazyTexts } from '../../lib/lazyTexts'
import { SettingsCard } from './SettingsCard'

const InventoryMap = lazy(() => import('../../components/inventory/InventoryMap').then((module) => ({ default: module.InventoryMap })))

/**
 * What runs on what (roadmap M5): hosts with their containers and guests and
 * the services on them, what nexdeck proposes, and what stands alone. A list
 * and a map; both read the same inventory.
 */
export function InventorySettings() {
  const ready = useLazyTexts('inventory')
  return ready ? <Page /> : null
}

function Dot({ node }: { node: InventoryNode }) {
  return <span className="dot flex-none" data-status={node.down ? 'bad' : node.demo ? 'unknown' : 'ok'} />
}

function Page() {
  const { t } = useTranslation()
  const client = useQueryClient()
  const found = useQuery({ queryKey: ['inventory'], queryFn: () => get<Inventory>('/inventory') })
  const [view, setView] = useState<'list' | 'map'>('list')
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState('')
  const inventory = found.data

  const changed = async (work: () => Promise<unknown>) => {
    setFailure('')
    try {
      const answer = await work()
      if (answer && typeof answer === 'object' && 'nodes' in answer) client.setQueryData(['inventory'], answer)
      else await client.invalidateQueries({ queryKey: ['inventory'] })
    } catch (error) {
      setFailure(error instanceof ApiError ? error.message : t('errors.network'))
    }
  }
  const refresh = async () => {
    setBusy(true)
    await changed(() => post<Inventory>('/inventory/refresh'))
    setBusy(false)
  }

  const byRef = new Map((inventory?.nodes ?? []).map((node) => [node.ref, node]))
  const proposed = (inventory?.relations ?? []).filter((one) => one.state === 'suggested' && byRef.has(one.child) && byRef.has(one.parent))
  const { roots, unplaced } = inventory ? tree(inventory) : { roots: [], unplaced: [] }
  const places = (inventory?.nodes ?? []).filter((node) => node.host || node.kind === 'container' || node.kind === 'guest')

  const row = (branch: Branch, depth: number): React.ReactNode => (
    <li key={`${branch.node.ref}@${depth}@${branch.relation?.id ?? 0}`}>
      <div className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-surface-hover" style={{ paddingLeft: 8 + depth * 18 }} data-testid="inventory-row">
        <Dot node={branch.node} />
        <span className="min-w-0 flex-1 truncate text-sm">
          {branch.node.name}
          <span className="ml-2 text-[11px] text-faint">
            {t(`inventory.kind.${branch.node.kind}`)}
            {branch.node.detail ? ` · ${branch.node.detail}` : ''}
            {branch.node.down ? ` · ${t('inventory.down')}` : ''}
          </span>
        </span>
        {branch.relation && (
          <>
            <span className="chip !py-0 text-[10.5px]">{t(`inventory.origin.${branch.relation.origin}`)}</span>
            <button
              type="button"
              className="btn btn-icon btn-flat h-7 w-7"
              aria-label={t('inventory.remove', { name: branch.node.name })}
              onClick={() => void changed(() => del(`/relations/${branch.relation?.id}`))}
            >
              <X size={13} />
            </button>
          </>
        )}
      </div>
      {branch.children.length > 0 && <ul>{branch.children.map((child) => row(child, depth + 1))}</ul>}
    </li>
  )

  return (
    <SettingsCard title={t('inventory.title')} description={t('inventory.help')}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="flex rounded-lg bg-surface-hover p-0.5" role="group">
          {(['list', 'map'] as const).map((one) => (
            <button key={one} type="button" className={`rounded-md px-3 py-1 text-[12.5px] ${view === one ? 'bg-bg text-ink shadow-sm' : 'text-muted'}`} aria-pressed={view === one} onClick={() => setView(one)}>
              {t(`inventory.${one}`)}
            </button>
          ))}
        </span>
        <button type="button" className="btn ml-auto" disabled={busy} onClick={() => void refresh()}>
          <RefreshCw size={14} className={busy ? 'animate-spin' : ''} /> {busy ? t('inventory.refreshing') : t('inventory.refresh')}
        </button>
      </div>
      {failure && <p className="mb-2 text-[12.5px] text-bad" role="alert">{failure}</p>}

      {proposed.length > 0 && (
        <section className="mb-4 rounded-xl border border-accent/40 p-3" data-testid="inventory-proposed">
          <h3 className="mb-1.5 text-[12px] font-semibold uppercase tracking-wide text-faint">{t('inventory.suggestions')}</h3>
          <ul className="flex flex-col gap-1.5">
            {proposed.map((one) => (
              <li key={one.id} className="flex flex-wrap items-center gap-2 text-sm">
                <span className="flex-1">{t('inventory.suggestion', { child: byRef.get(one.child)?.name, parent: byRef.get(one.parent)?.name })}</span>
                <button type="button" className="btn btn-accent h-7" onClick={() => void changed(() => post(`/relations/${one.id}/confirm`))}>
                  {t('inventory.yes')}
                </button>
                <button type="button" className="btn h-7" onClick={() => void changed(() => del(`/relations/${one.id}`))}>
                  {t('inventory.no')}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {inventory && inventory.nodes.length === 0 && <p className="text-sm text-muted">{t('inventory.empty')}</p>}
      {inventory && view === 'list' && (
        <>
          {roots.length === 0 && inventory.nodes.length > 0 && <p className="mb-2 text-sm text-muted">{t('inventory.empty')}</p>}
          <ul className="mb-4">{roots.map((branch) => row(branch, 0))}</ul>
          {unplaced.length > 0 && (
            <section>
              <h3 className="mb-0.5 text-[12px] font-semibold uppercase tracking-wide text-faint">{t('inventory.unplaced')}</h3>
              <p className="mb-2 text-[12px] text-muted">{t('inventory.unplacedHelp')}</p>
              <ul className="flex flex-col">
                {unplaced.map((node) => (
                  <li key={node.ref} className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-surface-hover" data-testid="inventory-unplaced">
                    <Dot node={node} />
                    <span className="min-w-0 flex-1 truncate text-sm">
                      {node.name}
                      <span className="ml-2 text-[11px] text-faint">{node.detail}</span>
                    </span>
                    <select
                      className="input h-7 w-auto py-0 text-[12px]"
                      value=""
                      aria-label={`${t('inventory.runsOn')}: ${node.name}`}
                      onChange={(event) => {
                        const parent = event.target.value
                        if (parent) void changed(() => post('/relations', { child: node.ref, parent }))
                      }}
                    >
                      <option value="">{t('inventory.runsOn')} …</option>
                      {places.filter((place) => place.ref !== node.ref).map((place) => (
                        <option key={place.ref} value={place.ref}>
                          {place.name} · {t(`inventory.kind.${place.kind}`)}
                        </option>
                      ))}
                    </select>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
      {inventory && view === 'map' && (
        <Suspense fallback={<div className="h-[480px]" />}>
          <InventoryMap inventory={inventory} />
        </Suspense>
      )}
    </SettingsCard>
  )
}
